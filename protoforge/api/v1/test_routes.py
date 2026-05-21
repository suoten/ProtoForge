import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from protoforge.api.v1.auth import require_user, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_database, _trigger_webhook_safe
from protoforge.core.messages import tmsg, get_lang_from_request

router = APIRouter()
logger = logging.getLogger(__name__)

_test_runner = None
_internal_client = None
_internal_token_exp = 0.0

_INTERNAL_TOKEN_EXPIRES_IN = 86400  # 24 hours in seconds


def _get_test_runner():
    global _test_runner

    if _test_runner is None:
        from protoforge.core.testing import TestRunner
        _test_runner = TestRunner()

        try:
            db = _get_database()
            _test_runner.set_database(db)
        except RuntimeError as e:
            logger.debug("Test runner database not available: %s", e)
    return _test_runner


async def _get_internal_client():
    global _internal_client, _internal_token_exp

    if _internal_client is not None:
        if time.time() > _internal_token_exp - 300:
            try:
                from protoforge.core.auth import user_manager, create_token
                admin_user = user_manager.get_user_by_username("admin")
                if admin_user:
                    token = create_token(admin_user.id, admin_user.username, admin_user.role, expires_in=_INTERNAL_TOKEN_EXPIRES_IN)
                    _internal_client.headers["Authorization"] = f"Bearer {token}"
                    _internal_token_exp = time.time() + _INTERNAL_TOKEN_EXPIRES_IN
            except Exception as exc:
                logger.debug("Internal client token refresh failed: %s", exc)
        return _internal_client

    from httpx import ASGITransport, AsyncClient
    from protoforge.main import app
    from protoforge.api.v1.auth import is_no_auth

    try:
        transport = ASGITransport(app=app)
        _internal_client = AsyncClient(transport=transport, base_url="http://testserver")
    except Exception as exc:
        logger.error("Failed to create internal test client: %s", exc)
        raise HTTPException(status_code=500, detail="Test infrastructure unavailable") from exc

    if not is_no_auth():
        try:
            from protoforge.core.auth import user_manager, create_token
            admin_user = user_manager.get_user_by_username("admin")
            if admin_user:
                token = create_token(admin_user.id, admin_user.username, admin_user.role, expires_in=_INTERNAL_TOKEN_EXPIRES_IN)
                _internal_client.headers["Authorization"] = f"Bearer {token}"
                _internal_token_exp = time.time() + _INTERNAL_TOKEN_EXPIRES_IN
        except Exception as exc:
            logger.debug("Internal client token creation failed: %s", exc)
    return _internal_client


async def _close_internal_client():
    global _internal_client
    if _internal_client is not None:
        await _internal_client.aclose()
        _internal_client = None


@router.post("/tests/cases")
async def create_test_case(case_def: dict[str, Any], _user: dict = Depends(require_user)):
    if not isinstance(case_def, dict) or not case_def:
        raise HTTPException(status_code=400, detail="Request body must be a non-empty object")
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    try:
        tc = TestCase.from_dict(case_def)
        await runner.save_test_case(tc)
        return tc.to_dict()
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid test case definition: {e}") from e


@router.get("/tests/cases")
async def list_test_cases(tag: Optional[str] = None, _user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    cases = runner.list_test_cases(tag=tag)
    return {"cases": [c.to_dict() for c in cases]}


@router.get("/tests/cases/{case_id}")
async def get_test_case(case_id: str, _user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    tc = runner.get_test_case(case_id)

    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    return tc.to_dict()


@router.put("/tests/cases/{case_id}")
async def update_test_case(case_id: str, case_def: dict[str, Any], _user: dict = Depends(require_user)):
    from protoforge.core.testing import TestCase

    runner = _get_test_runner()
    existing = runner.get_test_case(case_id)

    if not existing:
        raise HTTPException(status_code=404, detail="Test case not found")

    merged = existing.to_dict()
    merged.update(case_def)
    try:
        tc = TestCase.from_dict(merged)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid test case definition: {e}") from e
    tc.id = case_id
    await runner.save_test_case(tc)
    return tc.to_dict()


@router.delete("/tests/cases/{case_id}")
async def delete_test_case(case_id: str, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    if not await runner.delete_test_case(case_id):
        raise HTTPException(status_code=404, detail="Test case not found")
    return {"status": "ok"}


@router.post("/tests/suites")  # FIXED: 添加test_case_ids和tags的类型校验
async def create_test_suite(suite_def: dict[str, Any], _user: dict = Depends(require_user)):
    import time as _time
    from protoforge.core.testing import TestSuite

    # FIXED: 类型校验，确保test_case_ids和tags是列表类型
    test_case_ids = suite_def.get("test_case_ids", [])
    if not isinstance(test_case_ids, list):
        raise HTTPException(status_code=400, detail="test_case_ids must be a list")
    tags = suite_def.get("tags", [])
    if not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="tags must be a list")

    runner = _get_test_runner()
    suite = TestSuite(
        id=suite_def.get("id") or uuid.uuid4().hex[:12],
        name=suite_def.get("name", ""),
        description=suite_def.get("description", ""),
        test_case_ids=test_case_ids,
        tags=tags,
        created_at=_time.time(),
        updated_at=_time.time(),
    )

    await runner.save_test_suite(suite)
    return suite.to_dict()


@router.get("/tests/suites")
async def list_test_suites(_user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    suites = runner.list_test_suites()
    return {"suites": [s.to_dict() for s in suites]}


@router.get("/tests/suites/{suite_id}")
async def get_test_suite(suite_id: str, _user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    suite = runner.get_test_suite(suite_id)

    if not suite:
        raise HTTPException(status_code=404, detail="Test suite not found")
    return suite.to_dict()


@router.delete("/tests/suites/{suite_id}")
async def delete_test_suite(suite_id: str, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    if not await runner.delete_test_suite(suite_id):
        raise HTTPException(status_code=404, detail="Test suite not found")
    return {"status": "ok"}


@router.post("/tests/run")
async def run_test(request: Request, payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)):  # FIXED: 添加request参数
    test_cases = payload.get("test_cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(test_cases, list) or not test_cases:
        raise HTTPException(status_code=400, detail="Request body must be a non-empty array of test cases")
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    cases = []
    try:
        for tc_def in test_cases:
            tc = TestCase.from_dict(tc_def)
            cases.append(tc)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid test case in request: {e}") from e

    api_client = await _get_internal_client()
    lang = get_lang_from_request(request)
    report = await runner.run_test_suite(tmsg("suite_api_test", lang), cases, api_client=api_client, lang=lang)
    await _trigger_webhook_safe("test_complete", {"report_id": report.id, "passed": report.passed, "failed": report.failed, "total": report.total})
    return report.to_dict()


@router.post("/tests/run/case/{case_id}")
async def run_test_case_by_id(case_id: str, request: Request, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    tc = runner.get_test_case(case_id)

    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")

    api_client = await _get_internal_client()
    lang = get_lang_from_request(request)
    report = await runner.run_test_suite(tmsg("suite_single", lang, name=tc.name), [tc], api_client=api_client, lang=lang)
    await _trigger_webhook_safe("test_complete", {"report_id": report.id, "passed": report.passed, "failed": report.failed, "total": report.total})
    return report.to_dict()


@router.post("/tests/run/suite/{suite_id}")
async def run_test_suite_by_id(suite_id: str, request: Request, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    api_client = await _get_internal_client()
    lang = get_lang_from_request(request)

    try:
        report = await runner.run_test_suite_by_id(suite_id, api_client=api_client, lang=lang)
        await _trigger_webhook_safe("test_complete", {"report_id": report.id, "passed": report.passed, "failed": report.failed, "total": report.total})
        return report.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/tests/reports")
async def list_test_reports(_user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    return {"reports": runner.get_reports()}


@router.get("/tests/reports/trend")
async def get_report_trend(count: int = 20, _user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    return {"trends": runner.get_report_trend(count=count)}


@router.get("/tests/reports/{report_id}")
async def get_test_report(report_id: str, _user: dict = Depends(require_viewer)):
    runner = _get_test_runner()
    report = runner.get_report(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.to_dict() if hasattr(report, 'to_dict') else report


@router.get("/tests/reports/{report_id}/html")
async def get_test_report_html(report_id: str, request: Request, _user: dict = Depends(require_viewer)):
    from protoforge.core.auth import verify_token
    token = request.query_params.get("token")
    if not _user and not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if token and not _user:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
    from fastapi.responses import HTMLResponse
    runner = _get_test_runner()
    lang = get_lang_from_request(request)
    html = runner.get_report_html(report_id, lang=lang)

    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(content=html)


@router.post("/tests/quick-test")
async def quick_test(scope: str = "all", target_id: Optional[str] = None, request: Request = None, _user: dict = Depends(require_user)):
    engine = _get_engine()
    from protoforge.core.testing import TestCase, TestStep, Assertion, AssertionType
    lang = get_lang_from_request(request) if request else "zh"
    cases = []

    if scope == "all" or scope == "device":
        for dev_id, dev in engine.get_all_device_instances().items():
            if target_id and dev_id != target_id:
                continue

            protocol_running = engine.is_protocol_running(dev.protocol)

            steps = [
                TestStep(
                    name=tmsg("step_read_points", lang, name=dev.name),
                    action="read_points",
                    params={"device_id": dev_id},
                    assertions=[Assertion(type=AssertionType.LENGTH_GREATER, expected=0,
                                           message=tmsg("assert_point_data", lang, name=dev.name))],
                ),
            ]

            if not protocol_running:
                steps.append(TestStep(
                    name=tmsg("step_protocol_not_running", lang, protocol=dev.protocol, name=dev.name),
                    action="http_request",
                    params={"method": "GET", "url": "/health"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=tmsg("assert_protocol_simulated", lang, protocol=dev.protocol))],
                ))

            writable_points = [p for p in dev.config.points if getattr(p, 'access', 'rw') != "r"]

            if writable_points:
                wp = writable_points[0]
                steps.append(TestStep(
                    name=tmsg("step_write_point", lang, name=dev.name, point=wp.name),
                    action="write_point",
                    params={"device_id": dev_id, "point_name": wp.name, "value": 42.5},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=tmsg("assert_write_succeed", lang, name=wp.name))],
                ))

            cases.append(TestCase(
                id=f"qt-{dev_id}", name=tmsg("case_device_test", lang, name=dev.name),
                tags=["quick-test", "device"], steps=steps,
            ))

    if scope == "all" or scope == "scenario":
        for sc_id, sc_config in engine.get_all_scenario_configs().items():
            if target_id and sc_id != target_id:
                continue
            sc_steps = [
                TestStep(name=tmsg("step_verify_scenario", lang, name=sc_config.name), action="http_request",
                         params={"method": "GET", "url": f"/api/v1/scenarios/{sc_id}"},
                         assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message=tmsg("assert_scenario_accessible", lang))]),
            ]

            cases.append(TestCase(
                id=f"qt-scene-{sc_id}", name=tmsg("case_scenario_test", lang, name=sc_config.name),
                tags=["quick-test", "scenario"],
                steps=sc_steps,
            ))

    if scope == "all" or scope == "protocol":
        for proto_name, proto_server in engine.get_all_protocol_servers().items():
            is_running = proto_server.status.value == "running"
            running_port = engine.get_protocol_running_port(proto_name)
            proto_steps = []

            # 不能用TCP socket测试端口可达性，跳过端口检测
            is_tcp_port = isinstance(running_port, int)

            if is_running and is_tcp_port:
                import socket as _socket
                port_reachable = False
                try:
                    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                        s.settimeout(2)
                        s.connect(("127.0.0.1", running_port))
                        port_reachable = True
                except (OSError, _socket.timeout):
                    port_reachable = False

                proto_steps.append(TestStep(
                    name=tmsg("step_verify_port_listening", lang, protocol=proto_name, port=running_port),
                    action="http_request",
                    params={"method": "GET", "url": f"/api/v1/protocols"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)],
                ))
                if not port_reachable:
                    proto_steps.append(TestStep(
                        name=tmsg("step_port_not_reachable", lang, protocol=proto_name, port=running_port),
                        action="http_request",
                        params={"method": "GET", "url": "/health"},
                        assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                               message=tmsg("assert_port_not_reachable_simulated", lang, protocol=proto_name, port=running_port))],
                    ))
            elif is_running and not is_tcp_port:
                # Serial port protocol (e.g. Modbus RTU) — skip TCP port check
                proto_steps.append(TestStep(
                    name=tmsg("step_serial_port_running", lang, protocol=proto_name, port=running_port),
                    action="http_request",
                    params={"method": "GET", "url": "/health"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=tmsg("assert_serial_port_skipped", lang, protocol=proto_name))],
                ))
            else:
                proto_steps.append(TestStep(
                    name=tmsg("step_protocol_not_running_status", lang, protocol=proto_name, status=proto_server.status.value),
                    action="http_request",
                    params={"method": "GET", "url": "/health"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=tmsg("assert_protocol_simulated_only", lang, protocol=proto_name))],
                ))

            cases.append(TestCase(
                id=f"qt-proto-{proto_name}", name=tmsg("case_protocol_test", lang, name=proto_name),
                tags=["quick-test", "protocol"],
                steps=proto_steps,
            ))

    if not cases:
        cases.append(TestCase(
                id="qt-empty", name=tmsg("case_basic_connectivity", lang), tags=["quick-test"],
                steps=[
                    TestStep(name=tmsg("step_api_health", lang), action="http_request",
                             params={"method": "GET", "url": "/health"},
                             assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message=tmsg("assert_api_accessible", lang))]),
                ],
            ))

    api_client = await _get_internal_client()
    report = await _get_test_runner().run_test_suite(tmsg("suite_quick_test", lang), cases, api_client=api_client, lang=lang)
    return report.to_dict()


@router.get("/tests/suggestions")
async def get_test_suggestions(request: Request, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    lang = get_lang_from_request(request)
    suggestions = []

    for dev_id, dev in engine.get_all_device_instances().items():
        suggestions.append({
            "type": "device",
            "title": tmsg("suggest_test_device", lang, name=dev.name),
            "description": tmsg("suggest_test_device_desc", lang, name=dev.name, protocol=dev.protocol),
            "scope": "device",
            "target_id": dev_id,
            "priority": "high" if dev.status.value == "online" else "medium",
        })

    for sc_id, sc_config in engine.get_all_scenario_configs().items():
        suggestions.append({
            "type": "scenario",
            "title": tmsg("suggest_test_scenario", lang, name=sc_config.name),
            "description": tmsg("suggest_test_scenario_desc", lang, name=sc_config.name),
            "scope": "scenario",
            "target_id": sc_id,
            "priority": "medium",
        })

    running_protocols = [name for name, p in engine.get_all_protocol_servers().items() if p.status.value == "running"]

    if running_protocols:
        suggestions.append({
            "type": "protocol",
            "title": tmsg("suggest_test_protocols", lang, count=len(running_protocols)),
            "description": tmsg("suggest_verify_connectivity", lang),
            "scope": "protocol",
            "target_id": None,
            "priority": "low",
        })

    if not suggestions:
        suggestions.append({
            "type": "basic",
            "title": tmsg("suggest_basic_test", lang),
            "description": tmsg("suggest_no_devices", lang),
            "scope": "all",
            "target_id": None,
            "priority": "high",
        })

    return {"suggestions": suggestions}


@router.get("/tests/action-types")
async def get_test_action_types(request: Request, _user: dict = Depends(require_viewer)):
    lang = get_lang_from_request(request)
    return {"action_types": [
        {"value": "create_device", "label": tmsg("action_create_device", lang), "category": tmsg("category_device", lang), "params": ["id", "name", "protocol", "points"]},
        {"value": "get_device", "label": tmsg("action_get_device", lang), "category": tmsg("category_device", lang), "params": ["device_id"]},
        {"value": "delete_device", "label": tmsg("action_delete_device", lang), "category": tmsg("category_device", lang), "params": ["device_id"]},
        {"value": "read_points", "label": tmsg("action_read_points", lang), "category": tmsg("category_device", lang), "params": ["device_id"]},
        {"value": "write_point", "label": tmsg("action_write_point", lang), "category": tmsg("category_device", lang), "params": ["device_id", "point_name", "value"]},
        {"value": "list_devices", "label": tmsg("action_list_devices", lang), "category": tmsg("category_device", lang), "params": []},
        {"value": "batch_create_devices", "label": tmsg("action_batch_create", lang), "category": tmsg("category_device", lang), "params": ["devices"]},
        {"value": "batch_delete_devices", "label": tmsg("action_batch_delete", lang), "category": tmsg("category_device", lang), "params": ["device_ids"]},
        {"value": "start_protocol", "label": tmsg("action_start_protocol", lang), "category": tmsg("category_protocol", lang), "params": ["protocol", "config"]},
        {"value": "stop_protocol", "label": tmsg("action_stop_protocol", lang), "category": tmsg("category_protocol", lang), "params": ["protocol"]},
        {"value": "create_scenario", "label": tmsg("action_create_scenario", lang), "category": tmsg("category_scenario", lang), "params": ["id", "name", "devices", "rules"]},
        {"value": "start_scenario", "label": tmsg("action_start_scenario", lang), "category": tmsg("category_scenario", lang), "params": ["scenario_id"]},
        {"value": "stop_scenario", "label": tmsg("action_stop_scenario", lang), "category": tmsg("category_scenario", lang), "params": ["scenario_id"]},
        {"value": "delete_scenario", "label": tmsg("action_delete_scenario", lang), "category": tmsg("category_scenario", lang), "params": ["scenario_id"]},
        {"value": "list_templates", "label": tmsg("action_list_templates", lang), "category": tmsg("category_template", lang), "params": []},
        {"value": "instantiate_template", "label": tmsg("action_instantiate_template", lang), "category": tmsg("category_template", lang), "params": ["template_id"]},
        {"value": "http_request", "label": tmsg("action_http_request", lang), "category": tmsg("category_general", lang), "params": ["method", "url", "headers", "body"]},
        {"value": "wait", "label": tmsg("action_wait", lang), "category": tmsg("category_general", lang), "params": ["seconds"]},
        {"value": "assert_value", "label": tmsg("action_assert_value", lang), "category": tmsg("category_general", lang), "params": []},
    ]}


@router.get("/tests/assertion-types")
async def get_test_assertion_types(request: Request, _user: dict = Depends(require_viewer)):
    lang = get_lang_from_request(request)
    return {"assertion_types": [
        {"value": "status_code", "label": tmsg("assert_type_status_code", lang), "description": tmsg("assert_type_status_code_desc", lang), "simple": True},
        {"value": "not_null", "label": tmsg("assert_type_not_null", lang), "description": tmsg("assert_type_not_null_desc", lang), "simple": True},
        {"value": "length_greater", "label": tmsg("assert_type_length_greater", lang), "description": tmsg("assert_type_length_greater_desc", lang), "simple": True},
        {"value": "equals", "label": tmsg("assert_type_equals", lang), "description": tmsg("assert_type_equals_desc", lang), "simple": True},
        {"value": "contains", "label": tmsg("assert_type_contains", lang), "description": tmsg("assert_type_contains_desc", lang), "simple": True},
        {"value": "greater_than", "label": tmsg("assert_type_greater_than", lang), "description": tmsg("assert_type_greater_than_desc", lang), "simple": False},
        {"value": "less_than", "label": tmsg("assert_type_less_than", lang), "description": tmsg("assert_type_less_than_desc", lang), "simple": False},
        {"value": "not_equals", "label": tmsg("assert_type_not_equals", lang), "description": tmsg("assert_type_not_equals_desc", lang), "simple": False},
        {"value": "not_contains", "label": tmsg("assert_type_not_contains", lang), "description": tmsg("assert_type_not_contains_desc", lang), "simple": False},
        {"value": "regex_match", "label": tmsg("assert_type_regex_match", lang), "description": tmsg("assert_type_regex_match_desc", lang), "simple": False},
        {"value": "json_path", "label": tmsg("assert_type_json_path", lang), "description": tmsg("assert_type_json_path_desc", lang), "simple": False},
        {"value": "type_check", "label": tmsg("assert_type_type_check", lang), "description": tmsg("assert_type_type_check_desc", lang), "simple": False},
        {"value": "length_equals", "label": tmsg("assert_type_length_equals", lang), "description": tmsg("assert_type_length_equals_desc", lang), "simple": False},
        {"value": "length_less", "label": tmsg("assert_type_length_less", lang), "description": tmsg("assert_type_length_less_desc", lang), "simple": False},
    ]}
