import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

__all__ = ["TestStatus", "TestStep", "TestCase", "TestSuite", "TestReport",
           "AssertionType", "Assertion", "VariableStore", "AssertionEngine", "TestRunner"]

logger = logging.getLogger(__name__)

from typing import Any, Optional


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class AssertionType(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    REGEX_MATCH = "regex_match"
    JSON_PATH = "json_path"
    NOT_NULL = "not_null"
    TYPE_CHECK = "type_check"
    STATUS_CODE = "status_code"
    LENGTH_EQUALS = "length_equals"
    LENGTH_GREATER = "length_greater"
    LENGTH_LESS = "length_less"


@dataclass
class Assertion:
    type: AssertionType = AssertionType.EQUALS
    target: str = ""
    expected: Any = None
    json_path: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "target": self.target,
            "expected": self.expected,
            "json_path": self.json_path,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Assertion":
        return cls(
            type=AssertionType(data.get("type", "equals")),
            target=data.get("target", ""),
            expected=data.get("expected"),
            json_path=data.get("json_path", ""),
            message=data.get("message", ""),
        )


@dataclass
class TestStep:
    name: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    assertions: list[Assertion] = field(default_factory=list)
    extract: dict[str, str] = field(default_factory=dict)
    pre_hook: str = ""
    post_hook: str = ""
    delay: float = 0.0
    skip: bool = False
    actual: Any = None
    status: TestStatus = TestStatus.PENDING
    duration: float = 0.0
    error: str = ""
    extracted_vars: dict[str, Any] = field(default_factory=dict)
    assertion_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "params": self.params,
            "expected": self.expected,
            "assertions": [a.to_dict() for a in self.assertions],
            "extract": self.extract,
            "pre_hook": self.pre_hook,
            "post_hook": self.post_hook,
            "delay": self.delay,
            "skip": self.skip,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestStep":
        assertions = [Assertion.from_dict(a) for a in data.get("assertions", [])]
        return cls(
            name=data.get("name", ""),
            action=data.get("action", ""),
            params=data.get("params", {}),
            expected=data.get("expected", {}),
            assertions=assertions,
            extract=data.get("extract", {}),
            pre_hook=data.get("pre_hook", ""),
            post_hook=data.get("post_hook", ""),
            delay=data.get("delay", 0.0),
            skip=data.get("skip", False),
        )


@dataclass
class TestCase:
    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    setup_steps: list[TestStep] = field(default_factory=list)
    teardown_steps: list[TestStep] = field(default_factory=list)
    status: TestStatus = TestStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "steps": [s.to_dict() for s in self.steps],
            "setup_steps": [s.to_dict() for s in self.setup_steps],
            "teardown_steps": [s.to_dict() for s in self.teardown_steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestCase":
        steps = [TestStep.from_dict(s) for s in data.get("steps", [])]
        setup_steps = [TestStep.from_dict(s) for s in data.get("setup_steps", [])]
        teardown_steps = [TestStep.from_dict(s) for s in data.get("teardown_steps", [])]
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            steps=steps,
            setup_steps=setup_steps,
            teardown_steps=teardown_steps,
        )


@dataclass
class TestSuite:
    id: str
    name: str
    description: str = ""
    test_case_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "test_case_ids": self.test_case_ids,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TestReport:
    id: str
    name: str
    test_cases: list[TestCase] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time if self.end_time and self.start_time else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": round(self.duration, 3),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "success_rate": round(self.success_rate, 1),
            "environment": self.environment,
            "test_cases": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "description": tc.description,
                    "tags": tc.tags,
                    "status": tc.status.value,
                    "duration": round(tc.end_time - tc.start_time, 3) if tc.end_time else 0,
                    "error": tc.error,
                    "steps": [
                        {
                            "name": s.name,
                            "action": s.action,
                            "status": s.status.value,
                            "duration": round(s.duration, 3),
                            "error": s.error,
                            "extracted_vars": s.extracted_vars,
                            "assertion_results": s.assertion_results,
                        }
                        for s in tc.steps
                    ],
                }
                for tc in self.test_cases
            ],
        }

    def to_html(self) -> str:
        passed_pct = round(self.success_rate, 1)
        failed_pct = round((self.failed / self.total * 100) if self.total else 0, 1)
        error_pct = round((self.errors / self.total * 100) if self.total else 0, 1)

        status_colors = {
            "passed": "#18a058", "failed": "#d03050", "error": "#f0a020",
            "skipped": "#909399", "running": "#2080f0", "pending": "#c0c0c0",
        }

        case_rows = ""
        for tc in self.test_cases:
            tc_status_color = status_colors.get(tc.status.value, "#c0c0c0")
            tc_duration = round(tc.end_time - tc.start_time, 3) if tc.end_time else 0
            step_rows = ""
            for s in tc.steps:
                s_color = status_colors.get(s.status.value, "#c0c0c0")
                step_rows += f"""
                <tr>
                    <td>{s.name}</td>
                    <td><span style="color:{s_color};font-weight:600">{s.status.value.upper()}</span></td>
                    <td>{round(s.duration, 3)}s</td>
                    <td>{s.error or '-'}</td>
                </tr>"""
                for ar in s.assertion_results:
                    ar_color = "#18a058" if ar.get("passed") else "#d03050"
                    step_rows += f"""
                <tr class="assertion-row">
                    <td colspan="4">
                        <span style="color:{ar_color}">{'✓' if ar.get('passed') else '✗'}</span>
                        {ar.get('message', '')}
                    </td>
                </tr>"""

            case_rows += f"""
            <div class="case-card">
                <div class="case-header" style="border-left:4px solid {tc_status_color}">
                    <span class="case-name">{tc.name}</span>
                    <span class="case-status" style="color:{tc_status_color}">{tc.status.value.upper()}</span>
                    <span class="case-duration">{tc_duration}s</span>
                </div>
                {f'<div class="case-error">{tc.error}</div>' if tc.error else ''}
                <table class="steps-table">
                    <thead><tr><th>步骤</th><th>状态</th><th>耗时</th><th>错误</th></tr></thead>
                    <tbody>{step_rows}</tbody>
                </table>
            </div>"""

        env_rows = ""
        for k, v in self.environment.items():
            env_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>ProtoForge 测试报告 - {self.name}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f5f5; color:#333; padding:20px; }}
.container {{ max-width:1200px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:20px; color:#1a1a1a; }}
.summary {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:24px; }}
.summary-card {{ background:#fff; border-radius:8px; padding:16px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,0.1); }}
.summary-card .number {{ font-size:28px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#666; margin-top:4px; }}
.progress-bar {{ height:8px; background:#e0e0e0; border-radius:4px; margin:16px 0 24px; overflow:hidden; display:flex; }}
.progress-bar .passed {{ background:#18a058; }}
.progress-bar .failed {{ background:#d03050; }}
.progress-bar .errors {{ background:#f0a020; }}
.case-card {{ background:#fff; border-radius:8px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.1); overflow:hidden; }}
.case-header {{ padding:12px 16px; display:flex; align-items:center; gap:12px; }}
.case-name {{ font-weight:600; flex:1; }}
.case-status {{ font-weight:600; font-size:13px; }}
.case-duration {{ color:#666; font-size:13px; }}
.case-error {{ padding:8px 16px; background:#fff2f0; color:#d03050; font-size:13px; }}
.steps-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.steps-table th {{ background:#fafafa; padding:8px 12px; text-align:left; border-top:1px solid #eee; }}
.steps-table td {{ padding:6px 12px; border-top:1px solid #f0f0f0; }}
.assertion-row td {{ padding:4px 12px 4px 32px; color:#666; font-size:12px; background:#fafafa; }}
.env-table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:12px; }}
.env-table th, .env-table td {{ padding:8px 12px; border:1px solid #eee; text-align:left; }}
.env-table th {{ background:#fafafa; }}
.timestamp {{ color:#999; font-size:13px; margin-bottom:16px; }}
</style>
</head>
<body>
<div class="container">
<h1>🧪 ProtoForge 测试报告</h1>
<p class="timestamp">报告ID: {self.id} | 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
<div class="summary">
    <div class="summary-card"><div class="number">{self.total}</div><div class="label">总用例</div></div>
    <div class="summary-card"><div class="number" style="color:#18a058">{self.passed}</div><div class="label">通过</div></div>
    <div class="summary-card"><div class="number" style="color:#d03050">{self.failed}</div><div class="label">失败</div></div>
    <div class="summary-card"><div class="number" style="color:#f0a020">{self.errors}</div><div class="label">错误</div></div>
    <div class="summary-card"><div class="number" style="color:#909399">{self.skipped}</div><div class="label">跳过</div></div>
    <div class="summary-card"><div class="number" style="color:#2080f0">{passed_pct}%</div><div class="label">通过率</div></div>
</div>
<div class="progress-bar">
    <div class="passed" style="width:{passed_pct}%"></div>
    <div class="failed" style="width:{failed_pct}%"></div>
    <div class="errors" style="width:{error_pct}%"></div>
</div>
{case_rows}
{f'<h2 style="margin-top:24px;font-size:18px">环境信息</h2><table class="env-table"><thead><tr><th>键</th><th>值</th></tr></thead><tbody>{env_rows}</tbody></table>' if env_rows else ''}
</div>
</body>
</html>"""


class VariableStore:
    def __init__(self):
        self._vars: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._vars[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._vars.get(key, default)

    def resolve(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1]
            return self._vars.get(var_name, value)
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        return value

    def clear(self) -> None:
        self._vars.clear()

    def to_dict(self) -> dict[str, Any]:
        return dict(self._vars)


class AssertionEngine:
    def evaluate(self, actual: Any, assertion: Assertion) -> dict[str, Any]:
        result = {"passed": False, "message": "", "assertion": assertion.to_dict()}
        try:
            target_value = self._resolve_target(actual, assertion.target)

            if assertion.type == AssertionType.EQUALS:
                passed = target_value == assertion.expected
                result["passed"] = passed
                result["message"] = f"期望 {assertion.expected}, 实际 {target_value}" if not passed else f"等于 {assertion.expected}"

            elif assertion.type == AssertionType.NOT_EQUALS:
                passed = target_value != assertion.expected
                result["passed"] = passed
                result["message"] = f"不应等于 {assertion.expected}" if not passed else f"不等于 {assertion.expected}"

            elif assertion.type == AssertionType.CONTAINS:
                passed = assertion.expected in str(target_value) if target_value is not None else False
                result["passed"] = passed
                result["message"] = f"包含 '{assertion.expected}'" if passed else f"不包含 '{assertion.expected}', 实际: {target_value}"

            elif assertion.type == AssertionType.NOT_CONTAINS:
                passed = assertion.expected not in str(target_value) if target_value is not None else True
                result["passed"] = passed
                result["message"] = f"不包含 '{assertion.expected}'" if passed else f"包含 '{assertion.expected}'"

            elif assertion.type == AssertionType.GREATER_THAN:
                passed = float(target_value) > float(assertion.expected) if target_value is not None else False
                result["passed"] = passed
                result["message"] = f"{target_value} > {assertion.expected}" if passed else f"{target_value} 不大于 {assertion.expected}"

            elif assertion.type == AssertionType.LESS_THAN:
                passed = float(target_value) < float(assertion.expected) if target_value is not None else False
                result["passed"] = passed
                result["message"] = f"{target_value} < {assertion.expected}" if passed else f"{target_value} 不小于 {assertion.expected}"

            elif assertion.type == AssertionType.REGEX_MATCH:
                passed = bool(re.search(str(assertion.expected), str(target_value))) if target_value is not None else False
                result["passed"] = passed
                result["message"] = f"匹配正则 '{assertion.expected}'" if passed else f"不匹配正则 '{assertion.expected}'"

            elif assertion.type == AssertionType.JSON_PATH:
                json_value = self._extract_json_path(actual, assertion.json_path)
                passed = json_value == assertion.expected
                result["passed"] = passed
                result["message"] = f"JSON路径 '{assertion.json_path}' = {json_value}" if passed else f"JSON路径 '{assertion.json_path}' 期望 {assertion.expected}, 实际 {json_value}"

            elif assertion.type == AssertionType.NOT_NULL:
                passed = target_value is not None and target_value != ""
                result["passed"] = passed
                result["message"] = "值不为空" if passed else "值为空"

            elif assertion.type == AssertionType.TYPE_CHECK:
                type_map = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
                expected_type = type_map.get(str(assertion.expected), str)
                passed = isinstance(target_value, expected_type)
                result["passed"] = passed
                result["message"] = f"类型为 {assertion.expected}" if passed else f"类型不为 {assertion.expected}, 实际 {type(target_value).__name__}"

            elif assertion.type == AssertionType.STATUS_CODE:
                status = self._extract_json_path(actual, "status_code") if isinstance(actual, dict) else None
                passed = str(status) == str(assertion.expected)
                result["passed"] = passed
                result["message"] = f"状态码 {status}" if passed else f"状态码期望 {assertion.expected}, 实际 {status}"

            elif assertion.type == AssertionType.LENGTH_EQUALS:
                length = len(target_value) if target_value is not None and hasattr(target_value, "__len__") else 0
                passed = length == int(assertion.expected)
                result["passed"] = passed
                result["message"] = f"长度 {length} == {assertion.expected}" if passed else f"长度 {length} != {assertion.expected}"

            elif assertion.type == AssertionType.LENGTH_GREATER:
                length = len(target_value) if target_value is not None and hasattr(target_value, "__len__") else 0
                passed = length > int(assertion.expected)
                result["passed"] = passed
                result["message"] = f"长度 {length} > {assertion.expected}" if passed else f"长度 {length} 不大于 {assertion.expected}"

            elif assertion.type == AssertionType.LENGTH_LESS:
                length = len(target_value) if target_value is not None and hasattr(target_value, "__len__") else 0
                passed = length < int(assertion.expected)
                result["passed"] = passed
                result["message"] = f"长度 {length} < {assertion.expected}" if passed else f"长度 {length} 不小于 {assertion.expected}"

            else:
                result["message"] = f"未知断言类型: {assertion.type}"

        except Exception as e:
            result["passed"] = False
            result["message"] = f"断言执行异常: {str(e)}"

        if assertion.message:
            result["message"] = f"{assertion.message}: {result['message']}"
        return result

    def _resolve_target(self, actual: Any, target: str) -> Any:
        if not target:
            return actual
        if isinstance(actual, dict):
            return self._extract_json_path(actual, target)
        return actual

    def _extract_json_path(self, data: Any, path: str) -> Any:
        if not path or not isinstance(data, dict):
            return data
        parts = path.replace("[", ".").replace("]", "").split(".")
        current = data
        for part in parts:
            if not part:
                continue
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current


class TestRunner:
    def __init__(self):
        self._reports: list[TestReport] = []
        self._test_cases: dict[str, TestCase] = {}
        self._test_suites: dict[str, TestSuite] = {}
        self._assertion_engine = AssertionEngine()
        self._db = None

    def set_database(self, db) -> None:
        self._db = db

    async def restore_from_db(self) -> None:
        if not self._db:
            return
        try:
            cases = await self._db.load_all_test_cases()
            for c in cases:
                tc = TestCase.from_dict(c)
                self._test_cases[tc.id] = tc
            logger.info("Restored %d test cases from database", len(cases))
        except Exception as e:
            logger.warning("Failed to restore test cases: %s", e)
        try:
            suites = await self._db.load_all_test_suites()
            for s in suites:
                suite = TestSuite(
                    id=s["id"], name=s["name"], description=s.get("description", ""),
                    test_case_ids=s.get("test_case_ids", []), tags=s.get("tags", []),
                    created_at=s.get("created_at", 0), updated_at=s.get("updated_at", 0),
                )
                self._test_suites[suite.id] = suite
            logger.info("Restored %d test suites from database", len(suites))
        except Exception as e:
            logger.warning("Failed to restore test suites: %s", e)
        try:
            reports = await self._db.load_test_reports(count=100)
            for r in reports:
                report = TestReport(
                    id=r["id"], name=r["name"],
                    start_time=r.get("start_time", 0), end_time=r.get("end_time", 0),
                    total=r.get("total", 0), passed=r.get("passed", 0),
                    failed=r.get("failed", 0), errors=r.get("errors", 0),
                    skipped=r.get("skipped", 0), environment=r.get("environment", {}),
                )
                self._reports.append(report)
            logger.info("Restored %d test reports from database", len(reports))
        except Exception as e:
            logger.warning("Failed to restore test reports: %s", e)

    async def save_test_case(self, test_case: TestCase) -> TestCase:
        self._test_cases[test_case.id] = test_case
        if self._db:
            try:
                await self._db.save_test_case(test_case.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test case: %s", e)
        return test_case

    def get_test_case(self, case_id: str) -> Optional[TestCase]:
        return self._test_cases.get(case_id)

    def list_test_cases(self, tag: Optional[str] = None) -> list[TestCase]:
        cases = list(self._test_cases.values())
        if tag:
            cases = [c for c in cases if tag in c.tags]
        return cases

    async def delete_test_case(self, case_id: str) -> bool:
        if case_id in self._test_cases:
            del self._test_cases[case_id]
            if self._db:
                try:
                    await self._db.delete_test_case(case_id)
                except Exception as e:
                    logger.warning("Failed to delete test case from DB: %s", e)
            return True
        return False

    async def save_test_suite(self, suite: TestSuite) -> TestSuite:
        self._test_suites[suite.id] = suite
        if self._db:
            try:
                await self._db.save_test_suite(suite.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test suite: %s", e)
        return suite

    def get_test_suite(self, suite_id: str) -> Optional[TestSuite]:
        return self._test_suites.get(suite_id)

    def list_test_suites(self) -> list[TestSuite]:
        return list(self._test_suites.values())

    async def delete_test_suite(self, suite_id: str) -> bool:
        if suite_id in self._test_suites:
            del self._test_suites[suite_id]
            if self._db:
                try:
                    await self._db.delete_test_suite(suite_id)
                except Exception as e:
                    logger.warning("Failed to delete test suite from DB: %s", e)
            return True
        return False

    def create_test_case(self, name: str, description: str = "",
                         steps: list[dict[str, Any]] | None = None,
                         tags: list[str] | None = None) -> TestCase:
        tc = TestCase(
            id=uuid.uuid4().hex[:12],
            name=name,
            description=description,
            tags=tags or [],
        )
        if steps:
            for step_def in steps:
                step = TestStep.from_dict(step_def)
                tc.steps.append(step)
        self._test_cases[tc.id] = tc
        return tc

    async def run_test(self, test_case: TestCase, api_client=None) -> TestCase:
        test_case.status = TestStatus.RUNNING
        test_case.start_time = time.time()
        var_store = VariableStore()

        if test_case.setup_steps:
            for step in test_case.setup_steps:
                await self._execute_step(step, api_client, var_store)

        for step in test_case.steps:
            if step.skip:
                step.status = TestStatus.SKIPPED
                continue

            step.status = TestStatus.RUNNING
            step_start = time.time()
            try:
                if step.pre_hook:
                    await self._run_hook(step.pre_hook, var_store, api_client)

                if step.delay > 0:
                    import asyncio
                    await asyncio.sleep(step.delay)

                resolved_params = var_store.resolve(step.params)
                result = await self._execute_step_with_params(step, resolved_params, api_client)
                step.actual = result
                step.duration = time.time() - step_start

                if step.extract:
                    self._extract_variables(result, step.extract, var_store, step)

                if step.assertions:
                    all_passed = True
                    for assertion in step.assertions:
                        ar = self._assertion_engine.evaluate(result, assertion)
                        step.assertion_results.append(ar)
                        if not ar["passed"]:
                            all_passed = False
                    step.status = TestStatus.PASSED if all_passed else TestStatus.FAILED
                    if not all_passed:
                        step.error = "; ".join(
                            ar["message"] for ar in step.assertion_results if not ar["passed"]
                        )
                elif step.expected:
                    if self._check_expected(result, step.expected):
                        step.status = TestStatus.PASSED
                    else:
                        step.status = TestStatus.FAILED
                        step.error = f"Expected {step.expected}, got {result}"
                else:
                    step.status = TestStatus.PASSED

                if step.post_hook:
                    await self._run_hook(step.post_hook, var_store, api_client)

            except Exception as e:
                step.status = TestStatus.ERROR
                step.error = str(e)
                step.duration = time.time() - step_start

        if test_case.teardown_steps:
            for step in test_case.teardown_steps:
                try:
                    await self._execute_step(step, api_client, var_store)
                except Exception as e:
                    logger.warning("Teardown step failed: %s", e)

        test_case.end_time = time.time()

        step_statuses = [s.status for s in test_case.steps]
        if any(s == TestStatus.ERROR for s in step_statuses):
            test_case.status = TestStatus.ERROR
        elif any(s == TestStatus.FAILED for s in step_statuses):
            test_case.status = TestStatus.FAILED
        elif all(s == TestStatus.SKIPPED for s in step_statuses) and step_statuses:
            test_case.status = TestStatus.SKIPPED
        else:
            test_case.status = TestStatus.PASSED

        return test_case

    async def run_test_suite_by_id(self, suite_id: str, api_client=None) -> TestReport:
        suite = self._test_suites.get(suite_id)
        if not suite:
            raise ValueError(f"Test suite not found: {suite_id}")
        cases = []
        for cid in suite.test_case_ids:
            tc = self._test_cases.get(cid)
            if tc:
                cases.append(tc)
        return await self.run_test_suite(suite.name, cases, api_client)

    async def run_test_suite(self, name: str, test_cases: list[TestCase],
                             api_client=None) -> TestReport:
        report = TestReport(
            id=uuid.uuid4().hex[:12],
            name=name,
            start_time=time.time(),
            environment={"platform": "ProtoForge", "version": "1.0"},
        )

        for tc in test_cases:
            await self.run_test(tc, api_client)
            report.test_cases.append(tc)

        report.end_time = time.time()
        report.total = len(test_cases)
        report.passed = sum(1 for tc in test_cases if tc.status == TestStatus.PASSED)
        report.failed = sum(1 for tc in test_cases if tc.status == TestStatus.FAILED)
        report.errors = sum(1 for tc in test_cases if tc.status == TestStatus.ERROR)
        report.skipped = sum(1 for tc in test_cases if tc.status == TestStatus.SKIPPED)

        self._reports.append(report)
        if self._db:
            try:
                await self._db.save_test_report(report.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test report: %s", e)
        return report

    def get_reports(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._reports]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        for r in self._reports:
            if r.id == report_id:
                return r.to_dict()
        return None

    def get_report_html(self, report_id: str) -> str | None:
        for r in self._reports:
            if r.id == report_id:
                return r.to_html()
        return None

    def get_report_trend(self, count: int = 20) -> list[dict[str, Any]]:
        recent = self._reports[-count:]
        return [
            {
                "report_id": r.id,
                "name": r.name,
                "timestamp": r.start_time,
                "total": r.total,
                "passed": r.passed,
                "failed": r.failed,
                "errors": r.errors,
                "success_rate": round(r.success_rate, 1),
            }
            for r in recent
        ]

    async def _execute_step(self, step: TestStep, api_client=None,
                            var_store: Optional[VariableStore] = None) -> Any:
        resolved_params = var_store.resolve(step.params) if var_store else step.params
        return await self._execute_step_with_params(step, resolved_params, api_client)

    async def _execute_step_with_params(self, step: TestStep, params: dict[str, Any],
                                        api_client=None) -> Any:
        if not api_client:
            return None

        action = step.action

        if action == "create_device":
            resp = await api_client.post("/api/v1/devices", json=params)
            return self._resp_to_dict(resp)
        elif action == "get_device":
            device_id = params.get("device_id", "")
            resp = await api_client.get(f"/api/v1/devices/{device_id}")
            return self._resp_to_dict(resp)
        elif action == "delete_device":
            device_id = params.get("device_id", "")
            resp = await api_client.delete(f"/api/v1/devices/{device_id}")
            return self._resp_to_dict(resp)
        elif action == "read_points":
            device_id = params.get("device_id", "")
            resp = await api_client.get(f"/api/v1/devices/{device_id}/points")
            return self._resp_to_dict(resp)
        elif action == "write_point":
            device_id = params.get("device_id", "")
            point_name = params.get("point_name", "")
            value = params.get("value")
            resp = await api_client.put(
                f"/api/v1/devices/{device_id}/points/{point_name}",
                params={"value": value},
            )
            return self._resp_to_dict(resp)
        elif action == "start_protocol":
            protocol = params.get("protocol", "")
            config = params.get("config", {})
            resp = await api_client.post(f"/api/v1/protocols/{protocol}/start", json=config)
            return self._resp_to_dict(resp)
        elif action == "stop_protocol":
            protocol = params.get("protocol", "")
            resp = await api_client.post(f"/api/v1/protocols/{protocol}/stop")
            return self._resp_to_dict(resp)
        elif action == "list_devices":
            resp = await api_client.get("/api/v1/devices")
            return self._resp_to_dict(resp)
        elif action == "create_scenario":
            resp = await api_client.post("/api/v1/scenarios", json=params)
            return self._resp_to_dict(resp)
        elif action == "start_scenario":
            scenario_id = params.get("scenario_id", "")
            resp = await api_client.post(f"/api/v1/scenarios/{scenario_id}/start")
            return self._resp_to_dict(resp)
        elif action == "stop_scenario":
            scenario_id = params.get("scenario_id", "")
            resp = await api_client.post(f"/api/v1/scenarios/{scenario_id}/stop")
            return self._resp_to_dict(resp)
        elif action == "delete_scenario":
            scenario_id = params.get("scenario_id", "")
            resp = await api_client.delete(f"/api/v1/scenarios/{scenario_id}")
            return self._resp_to_dict(resp)
        elif action == "list_templates":
            resp = await api_client.get("/api/v1/templates")
            return self._resp_to_dict(resp)
        elif action == "instantiate_template":
            template_id = params.get("template_id", "")
            resp = await api_client.post(f"/api/v1/templates/{template_id}/instantiate", params=params)
            return self._resp_to_dict(resp)
        elif action == "batch_create_devices":
            resp = await api_client.post("/api/v1/devices/batch", json=params.get("devices", []))
            return self._resp_to_dict(resp)
        elif action == "batch_delete_devices":
            resp = await api_client.request("DELETE", "/api/v1/devices/batch", json=params.get("device_ids", params.get("ids", [])))
            return self._resp_to_dict(resp)
        elif action == "http_request":
            method = params.get("method", "GET").upper()
            url = params.get("url", "")
            if not url.startswith("http"):
                url = f"{api_client.base_url}{url}" if hasattr(api_client, 'base_url') else url
            headers = params.get("headers", {})
            body = params.get("body")
            kwargs = {"headers": headers}
            if body and method in ("POST", "PUT", "PATCH"):
                kwargs["json"] = body
            resp = await api_client.request(method, url, **kwargs)
            return self._resp_to_dict(resp)
        elif action == "wait":
            import asyncio
            seconds = params.get("seconds", 1.0)
            await asyncio.sleep(seconds)
            return {"waited": seconds}
        elif action == "assert_value":
            return params

        return None

    def _resp_to_dict(self, resp: Any) -> Any:
        if hasattr(resp, 'json'):
            try:
                result = resp.json()
                if hasattr(resp, 'status_code'):
                    if isinstance(result, dict):
                        result["status_code"] = resp.status_code
                    else:
                        result = {"data": result, "status_code": resp.status_code}
                return result
            except Exception:
                return {"status_code": getattr(resp, 'status_code', 0), "text": str(resp)}
        return resp

    def _extract_variables(self, result: Any, extract: dict[str, str],
                           var_store: VariableStore, step: TestStep) -> None:
        if not isinstance(result, dict):
            return
        for var_name, path in extract.items():
            value = self._assertion_engine._extract_json_path(result, path)
            var_store.set(var_name, value)
            step.extracted_vars[var_name] = value

    async def _run_hook(self, hook: str, var_store: VariableStore,
                        api_client=None) -> None:
        if not hook:
            return
        try:
            safe_builtins = {"print": print, "len": len, "str": str, "int": int, "float": float}
            local_vars = {"vars": var_store, "api": api_client}
            exec(hook, {"__builtins__": safe_builtins}, local_vars)
            if "vars" in local_vars and isinstance(local_vars["vars"], VariableStore):
                var_store._vars.update(local_vars["vars"]._vars)
        except Exception as e:
            logger.warning("Test hook execution failed: %s", e)

    def _check_expected(self, actual: Any, expected: dict[str, Any]) -> bool:
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual:
                return False
            if actual[key] != value:
                return False
        return True
