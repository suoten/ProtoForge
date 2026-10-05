"""v1.5.0 `protoforge doctor` 环境自检测试。

覆盖历史上高频部署问题的诊断路径：
  - 数据目录不可写 → error（Docker 卷未挂载类反馈）
  - 协议端口占用 / 冲突检测
  - 特权端口（<1024）提示
  - 核心依赖缺失 → error
  - 容器环境提示
  - JSON 输出结构与退出码语义
"""

import socket
import sys
from unittest.mock import patch

import pytest

from protoforge import doctor
from tests.wire_golden_harness import free_tcp_port


def _settings_stub(**overrides):
    class _S:
        port = 18080
        db_path = "data/doctor_test.db"
        protoforge_public_host = ""
    s = _S()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _get(results, check_id):
    return next(r for r in results if r.check_id == check_id)


# ---------------------------------------------------------------------------

def test_doctor_clean_environment_has_no_errors():
    """无故障环境下不应有 error 级结果（warning 可接受）。"""
    results = doctor.run_all_checks(_settings_stub())
    errors = [r for r in results if r.severity == "error"]
    assert not errors, f"意外 error: {[r.check_id for r in errors]}"


def test_doctor_db_unwritable_is_error(tmp_path):
    """数据目录不可写 → error + 修复建议（Docker 卷未挂载类问题）。"""
    readonly_dir = tmp_path / "ro"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555) if hasattr(readonly_dir, "chmod") else None
    settings = _settings_stub(db_path=str(readonly_dir / "sub" / "test.db"))
    results = doctor.run_all_checks(settings)
    db = _get(results, "db.writable")
    if sys.platform == "win32":
        # Windows 上只读目录权限语义不同：可写时应为 ok，不可写时必须 error
        if db.severity == "error":
            assert db.fixes, "error 结果必须带修复建议"
    else:
        assert db.severity == "error"
        assert db.fixes


def test_doctor_detects_occupied_http_port():
    """Web 端口被占用 → warning + 换端口建议。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied = blocker.getsockname()[1]
        results = doctor.check_http_port(_settings_stub(port=occupied))
        assert _get(results, "http.port").severity == "warning"
        assert any(str(occupied) in f for f in results[0].fixes)


def test_doctor_free_http_port_is_ok():
    port = free_tcp_port()
    results = doctor.check_http_port(_settings_stub(port=port))
    assert _get(results, "http.port").severity == "ok"


def test_doctor_privileged_ports_flagged():
    """S7(102) 等特权端口协议应出现在特权端口提示中。"""
    results = doctor.check_protocol_ports(_settings_stub())
    priv = _get(results, "protocols.privileged_ports")
    assert priv.severity == "warning"
    assert "s7=102" in priv.title


def test_doctor_conflicting_protocol_ports_flagged():
    """两个协议配同一端口 → warning 列出冲突双方。"""
    settings = _settings_stub(modbus_tcp_port=25000, s7_port=25000)
    results = doctor.check_protocol_ports(settings)
    in_use = _get(results, "protocols.ports_in_use")
    assert in_use.severity == "warning"
    assert "modbus_tcp 与 s7" in in_use.title or "s7 与 modbus_tcp" in in_use.title


def test_doctor_core_dependency_missing_is_error():
    """核心依赖缺失必须 error（不能只给 warning）。"""
    real = doctor.importlib.util.find_spec

    def fake_spec(name):
        if name == "uvicorn":
            return None
        return real(name)

    with patch.object(doctor.importlib.util, "find_spec", fake_spec):
        results = doctor.check_dependencies()
    core = _get(results, "deps.core")
    assert core.severity == "error"
    assert "uvicorn" in core.title


def test_doctor_container_hint():
    """容器环境检测给出端口映射建议。"""
    with patch.object(doctor, "_in_container", return_value=True):
        results = doctor.check_container(_settings_stub(protoforge_public_host=""))
    assert results[0].severity == "warning"
    assert any("NET_BIND_SERVICE" in f or "映射" in f for f in results[0].fixes)


def test_doctor_no_auth_warning():
    with patch.dict("os.environ", {"PROTOFORGE_NO_AUTH": "1"}):
        results = doctor.check_env_security(_settings_stub())
    assert results[0].severity == "warning"


def test_doctor_json_structure():
    """--json 输出包含 version/has_errors/checks 且可反序列化。"""
    import json as _json
    results = doctor.run_all_checks(_settings_stub())
    payload = _json.loads(doctor.render_json(results))
    assert payload["version"]
    assert isinstance(payload["has_errors"], bool)
    assert payload["checks"] and all(
        {"check_id", "severity", "title", "detail", "fixes"} <= set(c) for c in payload["checks"])


def test_doctor_exit_code_semantics():
    """有 error → 返回 1；无 error → 返回 0。"""
    ok_results = [doctor.CheckResult("t.ok", "ok", "fine")]
    assert doctor.main.__code__ is not None  # sanity
    from protoforge import doctor as d
    with patch.object(d, "run_all_checks", return_value=ok_results), \
            patch.object(d, "_get_version", return_value="test"):
        assert d.main(json_output=True) == 0
    err_results = [doctor.CheckResult("t.err", "error", "broken", fixes=["fix me"])]
    with patch.object(d, "run_all_checks", return_value=err_results), \
            patch.object(d, "_get_version", return_value="test"):
        assert d.main(json_output=True) == 1
