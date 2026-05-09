import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

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

    transport = ASGITransport(app=app)
    _internal_client = AsyncClient(transport=transport, base_url="http://testserver")

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
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    tc = TestCase.from_dict(case_def)
    await runner.save_test_case(tc)
    return tc.to_dict()


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
    tc = TestCase.from_dict(merged)
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
async def run_test(test_cases: list[dict[str, Any]], _user: dict = Depends(require_user)):
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    cases = []

    for tc_def in test_cases:
        tc = TestCase.from_dict(tc_def)
        cases.append(tc)

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

            steps = [
                TestStep(
                    name=f"读取 {dev.name} 测点",
                    action="read_points",
                    params={"device_id": dev_id},
                    assertions=[Assertion(type=AssertionType.LENGTH_GREATER, expected=0, message=f"{dev.name} 应有测点数据")],
                ),
            ]

            writable_points = [p for p in dev.config.points if getattr(p, 'access', 'rw') != "r"]

            if writable_points:
                wp = writable_points[0]
                steps.append(TestStep(
                    name=f"写入 {dev.name}/{wp.name}",
                    action="write_point",
                    params={"device_id": dev_id, "point_name": wp.name, "value": 42.5},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message=f"写入 {wp.name} 应成功")],
                ))

            cases.append(TestCase(
                id=f"qt-{dev_id}", name=f"设备测试: {dev.name}",
                tags=["quick-test", "device"], steps=steps,
            ))

    if scope == "all" or scope == "scenario":
        for sc_id, sc_config in engine.get_all_scenario_configs().items():
            if target_id and sc_id != target_id:
                continue
            sc_steps = [
                TestStep(name=f"验证场景 {sc_config.name} 状态", action="http_request",
                         params={"method": "GET", "url": f"/api/v1/scenarios/{sc_id}"},
                         assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="场景应可访问")]),
            ]

            cases.append(TestCase(
                id=f"qt-scene-{sc_id}", name=f"场景测试: {sc_config.name}",
                tags=["quick-test", "scenario"],
                steps=sc_steps,
            ))

    if scope == "all" or scope == "protocol":
        for proto_name, proto_server in engine.get_all_protocol_servers().items():
            cases.append(TestCase(
                id=f"qt-proto-{proto_name}", name=f"协议测试: {proto_name}",
                tags=["quick-test", "protocol"],
                steps=[
                    TestStep(name=f"验证协议 {proto_name} 运行状态", action="http_request",
                             params={"method": "GET", "url": "/api/v1/protocols"},
                             assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="协议列表应可访问")]),
                ],
            ))

    if not cases:
        cases.append(TestCase(
                id="qt-empty", name="基础连通性测试", tags=["quick-test"],
                steps=[
                    TestStep(name="API健康检查", action="http_request",
                             params={"method": "GET", "url": "/health"},
                             assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="API应可访问")]),
                ],
            ))

    api_client = await _get_internal_client()
    report = await _get_test_runner().run_test_suite("一键测试", cases, api_client=api_client)
    return report.to_dict()


@router.get("/tests/suggestions")
async def get_test_suggestions(_user: dict = Depends(require_viewer)):
    engine = _get_engine()
    suggestions = []

    for dev_id, dev in engine.get_all_device_instances().items():
        suggestions.append({
            "type": "device",
            "title": f"测试设备 {dev.name}",
            "description": f"验证 {dev.name} ({dev.protocol}) 的测点读写功能",
            "scope": "device",
            "target_id": dev_id,
            "priority": "high" if dev.status.value == "online" else "medium",
        })

    for sc_id, sc_config in engine.get_all_scenario_configs().items():
        suggestions.append({
            "type": "scenario",
            "title": f"测试场景 {sc_config.name}",
            "description": f"验证场景 {sc_config.name} 的启停和规则触发",
            "scope": "scenario",
            "target_id": sc_id,
            "priority": "medium",
        })

    running_protocols = [name for name, p in engine.get_all_protocol_servers().items() if p.status.value == "running"]

    if running_protocols:
        suggestions.append({
            "type": "protocol",
            "title": f"测试 {len(running_protocols)} 个运行中协议",
            "description": "验证所有运行中协议的连通性",
            "scope": "protocol",
            "target_id": None,
            "priority": "low",
        })

    if not suggestions:
        suggestions.append({
            "type": "basic",
            "title": "基础连通性测试",
            "description": "系统暂无设备，先测试API连通性",
            "scope": "all",
            "target_id": None,
            "priority": "high",
        })

    return {"suggestions": suggestions}


@router.get("/tests/action-types")
async def get_test_action_types(_user: dict = Depends(require_viewer)):
    return {"action_types": [
        {"value": "create_device", "label": "创建设备", "category": "设备", "params": ["id", "name", "protocol", "points"]},
        {"value": "get_device", "label": "获取设备", "category": "设备", "params": ["device_id"]},
        {"value": "delete_device", "label": "删除设备", "category": "设备", "params": ["device_id"]},
        {"value": "read_points", "label": "读取测点", "category": "设备", "params": ["device_id"]},
        {"value": "write_point", "label": "写入测点", "category": "设备", "params": ["device_id", "point_name", "value"]},
        {"value": "list_devices", "label": "设备列表", "category": "设备", "params": []},
        {"value": "batch_create_devices", "label": "批量创建", "category": "设备", "params": ["devices"]},
        {"value": "batch_delete_devices", "label": "批量删除", "category": "设备", "params": ["device_ids"]},
        {"value": "start_protocol", "label": "启动协议", "category": "协议", "params": ["protocol", "config"]},
        {"value": "stop_protocol", "label": "停止协议", "category": "协议", "params": ["protocol"]},
        {"value": "create_scenario", "label": "创建场景", "category": "场景", "params": ["id", "name", "devices", "rules"]},
        {"value": "start_scenario", "label": "启动场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "stop_scenario", "label": "停止场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "delete_scenario", "label": "删除场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "list_templates", "label": "模板列表", "category": "模板", "params": []},
        {"value": "instantiate_template", "label": "实例化模板", "category": "模板", "params": ["template_id"]},
        {"value": "http_request", "label": "HTTP请求", "category": "通用", "params": ["method", "url", "headers", "body"]},
        {"value": "wait", "label": "等待", "category": "通用", "params": ["seconds"]},
        {"value": "assert_value", "label": "断言值", "category": "通用", "params": []},
    ]}


@router.get("/tests/assertion-types")
async def get_test_assertion_types(_user: dict = Depends(require_viewer)):
    return {"assertion_types": [
        {"value": "status_code", "label": "请求应成功", "description": "验证HTTP状态码", "simple": True},
        {"value": "not_null", "label": "值不应为空", "description": "验证返回值非空", "simple": True},
        {"value": "length_greater", "label": "列表不应为空", "description": "验证列表长度>0", "simple": True},
        {"value": "equals", "label": "值应等于", "description": "验证值等于期望值", "simple": True},
        {"value": "contains", "label": "应包含", "description": "验证包含指定内容", "simple": True},
        {"value": "greater_than", "label": "值应大于", "description": "验证数值大于阈值", "simple": False},
        {"value": "less_than", "label": "值应小于", "description": "验证数值小于阈值", "simple": False},
        {"value": "not_equals", "label": "值不应等于", "description": "验证值不等于指定值", "simple": False},
        {"value": "not_contains", "label": "不应包含", "description": "验证不包含指定内容", "simple": False},
        {"value": "regex_match", "label": "正则匹配", "description": "验证匹配正则表达式", "simple": False},
        {"value": "json_path", "label": "JSON路径取值", "description": "从JSON中提取值验证", "simple": False},
        {"value": "type_check", "label": "类型检查", "description": "验证值的类型", "simple": False},
        {"value": "length_equals", "label": "长度等于", "description": "验证列表长度等于指定值", "simple": False},
        {"value": "length_less", "label": "长度小于", "description": "验证列表长度小于指定值", "simple": False},
    ]}
