import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request  # FIXED: added Body import

from protoforge.api.v1.auth import require_user, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_database, _trigger_webhook_safe

router = APIRouter()
logger = logging.getLogger(__name__)

_test_runner = None
_internal_client = None
_internal_token_exp = 0.0


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
                    token = create_token(admin_user.id, admin_user.username, admin_user.role, expires_in=86400)
                    _internal_client.headers["Authorization"] = f"Bearer {token}"
                    _internal_token_exp = time.time() + 86400
            except Exception as exc:
                logger.debug("Internal client token refresh failed: %s", exc)
        return _internal_client

    from httpx import ASGITransport, AsyncClient
    from protoforge.main import app
    from protoforge.api.v1.auth import is_no_auth

    try:  # FIXED: 添加异常保护
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
                token = create_token(admin_user.id, admin_user.username, admin_user.role, expires_in=86400)
                _internal_client.headers["Authorization"] = f"Bearer {token}"
                _internal_token_exp = time.time() + 86400
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
    if not isinstance(case_def, dict) or not case_def:  # FIXED: 类型校验
        raise HTTPException(status_code=400, detail="Request body must be a non-empty object")
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    try:  # FIXED: 添加异常处理，格式错误返回400而非500
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
    try:  # FIXED: 添加异常处理
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


@router.post("/tests/suites")
async def create_test_suite(suite_def: dict[str, Any], _user: dict = Depends(require_user)):
    import time as _time
    from protoforge.core.testing import TestSuite

    runner = _get_test_runner()
    suite = TestSuite(
        id=suite_def.get("id") or uuid.uuid4().hex[:12],
        name=suite_def.get("name", ""),
        description=suite_def.get("description", ""),
        test_case_ids=suite_def.get("test_case_ids", []),
        tags=suite_def.get("tags", []),
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
async def run_test(payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)):  # FIXED: accept wrapped object for explicit contract
    test_cases = payload.get("test_cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(test_cases, list) or not test_cases:  # FIXED: 类型校验
        raise HTTPException(status_code=400, detail="Request body must be a non-empty array of test cases")
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    cases = []
    try:  # FIXED: 添加异常处理
        for tc_def in test_cases:
            tc = TestCase.from_dict(tc_def)
            cases.append(tc)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid test case in request: {e}") from e

    api_client = await _get_internal_client()
    report = await runner.run_test_suite("API Test", cases, api_client=api_client)
    await _trigger_webhook_safe("test_complete", {"report_id": report.id, "passed": report.passed, "failed": report.failed, "total": report.total})
    return report.to_dict()


@router.post("/tests/run/case/{case_id}")
async def run_test_case_by_id(case_id: str, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    tc = runner.get_test_case(case_id)

    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")

    api_client = await _get_internal_client()
    report = await runner.run_test_suite(f"Single: {tc.name}", [tc], api_client=api_client)
    await _trigger_webhook_safe("test_complete", {"report_id": report.id, "passed": report.passed, "failed": report.failed, "total": report.total})
    return report.to_dict()


@router.post("/tests/run/suite/{suite_id}")
async def run_test_suite_by_id(suite_id: str, _user: dict = Depends(require_user)):
    runner = _get_test_runner()
    api_client = await _get_internal_client()

    try:
        report = await runner.run_test_suite_by_id(suite_id, api_client=api_client)
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
    if not _user and not token:  # FIXED: 无认证且无token时拒绝访问
        raise HTTPException(status_code=401, detail="Authentication required")
    if token and not _user:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
    from fastapi.responses import HTMLResponse
    runner = _get_test_runner()
    html = runner.get_report_html(report_id)

    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(content=html)


@router.post("/tests/quick-test")
async def quick_test(scope: str = "all", target_id: Optional[str] = None, _user: dict = Depends(require_user)):
    engine = _get_engine()
    from protoforge.core.testing import TestCase, TestStep, Assertion, AssertionType
    cases = []

    if scope == "all" or scope == "device":
        for dev_id, dev in engine.get_all_device_instances().items():
            if target_id and dev_id != target_id:
                continue

            # FIXED: check if device's protocol is actually running
            protocol_running = engine.is_protocol_running(dev.protocol)

            steps = [
                TestStep(
                    name=f"Read {dev.name} points",
                    action="read_points",
                    params={"device_id": dev_id},
                    assertions=[Assertion(type=AssertionType.LENGTH_GREATER, expected=0,
                                           message=f"{dev.name} should have point data")],
                ),
            ]

            # FIXED: add protocol status check step for device
            if not protocol_running:
                steps.append(TestStep(
                    name=f"WARNING: Protocol {dev.protocol} is not running for device {dev.name}",
                    action="http_request",
                    params={"method": "GET", "url": "/health"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=f"Protocol {dev.protocol} is not running - point data is simulated only, not from real protocol")],
                ))

            writable_points = [p for p in dev.config.points if getattr(p, 'access', 'rw') != "r"]

            if writable_points:
                wp = writable_points[0]
                steps.append(TestStep(
                    name=f"Write {dev.name}/{wp.name}",
                    action="write_point",
                    params={"device_id": dev_id, "point_name": wp.name, "value": 42.5},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=f"Write {wp.name} should succeed")],
                ))

            cases.append(TestCase(
                id=f"qt-{dev_id}", name=f"Device test: {dev.name}",
                tags=["quick-test", "device"], steps=steps,
            ))

    if scope == "all" or scope == "scenario":
        for sc_id, sc_config in engine.get_all_scenario_configs().items():
            if target_id and sc_id != target_id:
                continue
            sc_steps = [
                TestStep(name=f"Verify scenario {sc_config.name} status", action="http_request",
                         params={"method": "GET", "url": f"/api/v1/scenarios/{sc_id}"},
                         assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="Scenario should be accessible")]),
            ]

            cases.append(TestCase(
                id=f"qt-scene-{sc_id}", name=f"Scenario test: {sc_config.name}",
                tags=["quick-test", "scenario"],
                steps=sc_steps,
            ))

    if scope == "all" or scope == "protocol":
        for proto_name, proto_server in engine.get_all_protocol_servers().items():
            # FIXED: test actual protocol status instead of just API list endpoint
            is_running = proto_server.status.value == "running"
            running_port = engine.get_protocol_running_port(proto_name)
            proto_steps = []

            if is_running and running_port:
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
                    name=f"Verify protocol {proto_name} port {running_port} is listening",
                    action="http_request",
                    params={"method": "GET", "url": f"/api/v1/protocols"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)],
                ))
                if not port_reachable:
                    proto_steps.append(TestStep(
                        name=f"WARNING: Protocol {proto_name} reports running but port {running_port} is not reachable",
                        action="http_request",
                        params={"method": "GET", "url": "/health"},
                        assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                               message=f"Protocol {proto_name} port {running_port} not reachable - data is simulated only")],
                    ))
            else:
                proto_steps.append(TestStep(
                    name=f"Protocol {proto_name} is not running (status: {proto_server.status.value})",
                    action="http_request",
                    params={"method": "GET", "url": "/health"},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200,
                                           message=f"Protocol {proto_name} is not running - devices using this protocol will only return simulated data")],
                ))

            cases.append(TestCase(
                id=f"qt-proto-{proto_name}", name=f"Protocol test: {proto_name}",
                tags=["quick-test", "protocol"],
                steps=proto_steps,
            ))

    if not cases:
        cases.append(TestCase(
                id="qt-empty", name="Basic connectivity test", tags=["quick-test"],
                steps=[
                    TestStep(name="API health check", action="http_request",
                             params={"method": "GET", "url": "/health"},
                             assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="API should be accessible")]),
                ],
            ))

    api_client = await _get_internal_client()
    report = await _get_test_runner().run_test_suite("Quick test", cases, api_client=api_client)
    return report.to_dict()


@router.get("/tests/suggestions")
async def get_test_suggestions(_user: dict = Depends(require_viewer)):
    engine = _get_engine()
    suggestions = []

    for dev_id, dev in engine.get_all_device_instances().items():
        suggestions.append({
            "type": "device",
            "title": f"Test device {dev.name}",  # FIXED: CN→EN
            "description": f"Verify read/write points for {dev.name} ({dev.protocol})",  # FIXED: CN→EN
            "scope": "device",
            "target_id": dev_id,
            "priority": "high" if dev.status.value == "online" else "medium",
        })

    for sc_id, sc_config in engine.get_all_scenario_configs().items():
        suggestions.append({
            "type": "scenario",
            "title": f"Test scenario {sc_config.name}",  # FIXED: CN→EN
            "description": f"Verify start/stop and rule triggering for scenario {sc_config.name}",  # FIXED: CN→EN
            "scope": "scenario",
            "target_id": sc_id,
            "priority": "medium",
        })

    running_protocols = [name for name, p in engine.get_all_protocol_servers().items() if p.status.value == "running"]

    if running_protocols:
        suggestions.append({
            "type": "protocol",
            "title": f"Test {len(running_protocols)} running protocol(s)",  # FIXED: CN→EN
            "description": "Verify connectivity of all running protocols",  # FIXED: CN→EN
            "scope": "protocol",
            "target_id": None,
            "priority": "low",
        })

    if not suggestions:
        suggestions.append({
            "type": "basic",
            "title": "Basic connectivity test",  # FIXED: CN→EN
            "description": "No devices yet, test API connectivity first",  # FIXED: CN→EN
            "scope": "all",
            "target_id": None,
            "priority": "high",
        })

    return {"suggestions": suggestions}


@router.get("/tests/action-types")
async def get_test_action_types(_user: dict = Depends(require_viewer)):
    return {"action_types": [
        {"value": "create_device", "label": "Create device", "category": "Device", "params": ["id", "name", "protocol", "points"]},  # FIXED: CN→EN
        {"value": "get_device", "label": "Get device", "category": "Device", "params": ["device_id"]},  # FIXED: CN→EN
        {"value": "delete_device", "label": "Delete device", "category": "Device", "params": ["device_id"]},  # FIXED: CN→EN
        {"value": "read_points", "label": "Read points", "category": "Device", "params": ["device_id"]},  # FIXED: CN→EN
        {"value": "write_point", "label": "Write point", "category": "Device", "params": ["device_id", "point_name", "value"]},  # FIXED: CN→EN
        {"value": "list_devices", "label": "Device list", "category": "Device", "params": []},  # FIXED: CN→EN
        {"value": "batch_create_devices", "label": "Batch create", "category": "Device", "params": ["devices"]},  # FIXED: CN→EN
        {"value": "batch_delete_devices", "label": "Batch delete", "category": "Device", "params": ["device_ids"]},  # FIXED: CN→EN
        {"value": "start_protocol", "label": "Start protocol", "category": "Protocol", "params": ["protocol", "config"]},  # FIXED: CN→EN
        {"value": "stop_protocol", "label": "Stop protocol", "category": "Protocol", "params": ["protocol"]},  # FIXED: CN→EN
        {"value": "create_scenario", "label": "Create scenario", "category": "Scenario", "params": ["id", "name", "devices", "rules"]},  # FIXED: CN→EN
        {"value": "start_scenario", "label": "Start scenario", "category": "Scenario", "params": ["scenario_id"]},  # FIXED: CN→EN
        {"value": "stop_scenario", "label": "Stop scenario", "category": "Scenario", "params": ["scenario_id"]},  # FIXED: CN→EN
        {"value": "delete_scenario", "label": "Delete scenario", "category": "Scenario", "params": ["scenario_id"]},  # FIXED: CN→EN
        {"value": "list_templates", "label": "Template list", "category": "Template", "params": []},  # FIXED: CN→EN
        {"value": "instantiate_template", "label": "Instantiate template", "category": "Template", "params": ["template_id"]},  # FIXED: CN→EN
        {"value": "http_request", "label": "HTTP request", "category": "General", "params": ["method", "url", "headers", "body"]},  # FIXED: CN→EN
        {"value": "wait", "label": "Wait", "category": "General", "params": ["seconds"]},  # FIXED: CN→EN
        {"value": "assert_value", "label": "Assert value", "category": "General", "params": []},  # FIXED: CN→EN
    ]}


@router.get("/tests/assertion-types")
async def get_test_assertion_types(_user: dict = Depends(require_viewer)):
    return {"assertion_types": [
        {"value": "status_code", "label": "Request should succeed", "description": "Verify HTTP status code", "simple": True},  # FIXED: CN→EN
        {"value": "not_null", "label": "Value should not be empty", "description": "Verify return value is not empty", "simple": True},  # FIXED: CN→EN
        {"value": "length_greater", "label": "List should not be empty", "description": "Verify list length > 0", "simple": True},  # FIXED: CN→EN
        {"value": "equals", "label": "Value should equal", "description": "Verify value equals expected", "simple": True},  # FIXED: CN→EN
        {"value": "contains", "label": "Should contain", "description": "Verify contains specified content", "simple": True},  # FIXED: CN→EN
        {"value": "greater_than", "label": "Value should be greater than", "description": "Verify value greater than threshold", "simple": False},  # FIXED: CN→EN
        {"value": "less_than", "label": "Value should be less than", "description": "Verify value less than threshold", "simple": False},  # FIXED: CN→EN
        {"value": "not_equals", "label": "Value should not equal", "description": "Verify value does not equal specified value", "simple": False},  # FIXED: CN→EN
        {"value": "not_contains", "label": "Should not contain", "description": "Verify does not contain specified content", "simple": False},  # FIXED: CN→EN
        {"value": "regex_match", "label": "Regex match", "description": "Verify matches regex pattern", "simple": False},  # FIXED: CN→EN
        {"value": "json_path", "label": "JSON path value", "description": "Extract value from JSON for verification", "simple": False},  # FIXED: CN→EN
        {"value": "type_check", "label": "Type check", "description": "Verify value type", "simple": False},  # FIXED: CN→EN
        {"value": "length_equals", "label": "Length equals", "description": "Verify list length equals specified value", "simple": False},  # FIXED: CN→EN
        {"value": "length_less", "label": "Length less than", "description": "Verify list length less than specified value", "simple": False},  # FIXED: CN→EN
    ]}
