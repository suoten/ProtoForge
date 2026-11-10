"""MCP Server 单元测试 — Fake SDK 客户端，无网络、无真实 MCP 传输依赖（v1.13.0）。"""

import json

import pytest

from protoforge import mcp_server
from protoforge.mcp_server import MCP_AVAILABLE, MCPBackend


class FakeClient:
    def __init__(self, base_url="", timeout=30.0, **kwargs):
        self.base_url = base_url
        self.logged_in = 0
        self.fail_auth_once = False
        self.last_protocol = None

    def login(self, username, password):
        self.logged_in += 1

    def health(self):
        return {"version": "1.13.0", "devices": 3}

    def list_protocols(self):
        return [{"name": "modbus_tcp", "running": True}]

    def start_protocol(self, name, config=None):
        return {"ok": True, "protocol": name}

    def stop_protocol(self, name):
        return {"ok": True, "protocol": name}

    def list_templates(self, protocol=None):
        return [{"id": "t1", "protocol": protocol or "modbus_tcp"}]

    def search_templates(self, q="", protocol=None):
        return [{"id": "t1", "q": q}]

    def quick_create(self, template_id, name, device_id=None, protocol_config=None):
        return {"id": device_id or "d-new", "template": template_id, "name": name}

    def start_device(self, device_id):
        return {"ok": True, "id": device_id}

    def stop_device(self, device_id):
        return {"ok": True, "id": device_id}

    def get_device(self, device_id):
        return {"id": device_id, "status": "running"}

    def delete_device(self, device_id):
        return {"ok": True, "id": device_id}

    def list_devices(self, protocol=None):
        self.last_protocol = protocol
        return [{"id": "d1", "protocol": protocol or "modbus_tcp"}]

    def read_points(self, device_id):
        if self.fail_auth_once:
            self.fail_auth_once = False
            raise RuntimeError("HTTP 401 Unauthorized")
        return [{"name": "temp", "value": 25.5}]

    def write_point(self, device_id, point_name, value):
        return {"ok": True, "point": point_name, "value": value}

    def list_scenarios(self):
        return [{"id": "s1"}]

    def start_scenario(self, scenario_id):
        return {"ok": True, "id": scenario_id}

    def stop_scenario(self, scenario_id):
        return {"ok": True, "id": scenario_id}

    def get_logs(self, count=100, protocol=None):
        return [{"message": "read holding registers", "protocol": protocol or "modbus_tcp"}]

    def quick_test(self, scope="all", target_id=None):
        return {"report_id": "r1", "scope": scope}

    def get_test_report(self, report_id):
        return {"id": report_id, "passed": 5}

    def get_device_connection_guide(self, device_id):
        return {"device_id": device_id, "host": "127.0.0.1", "port": 5020}

    def ai_extract_points(self, text, protocol_hint=""):
        return {"ok": True, "device": {"name": "dev", "protocol": protocol_hint or "modbus_tcp",
                                       "points": []}, "notes": []}

    def ai_create_device_from_text(self, text, name="", device_id=None, protocol_hint=""):
        return {"ok": True, "device_id": device_id or "ai-dev", "point_count": 4, "notes": []}


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(mcp_server, "ProtoForgeClient", FakeClient)
    return MCPBackend("http://localhost:8000", username="admin", password="admin")


BACKEND_METHODS = [
    ("server_info", ()),
    ("list_protocols", ()),
    ("start_protocol", ("modbus_tcp",)),
    ("stop_protocol", ("modbus_tcp",)),
    ("list_templates", ()),
    ("search_templates", ("plc",)),
    ("list_devices", ()),
    ("get_device", ("d1",)),
    ("delete_device", ("d1",)),
    ("start_device", ("d1",)),
    ("stop_device", ("d1",)),
    ("read_points", ("d1",)),
    ("write_point", ("d1", "temp", 30)),
    ("list_scenarios", ()),
    ("start_scenario", ("s1",)),
    ("stop_scenario", ("s1",)),
    ("get_logs", ()),
    ("quick_test", ()),
    ("get_test_report", ("r1",)),
    ("connection_guide", ("d1",)),
    ("ai_extract_points", ("说明书文本",)),
    ("ai_create_device_from_text", ("说明书文本",)),
]


@pytest.mark.parametrize("name,args", BACKEND_METHODS)
def test_backend_methods(name, args, backend):
    result = getattr(backend, name)(*args)
    assert result is not None


def test_login_once_across_calls(backend):
    backend.list_devices()
    backend.read_points("d1")
    backend.list_protocols()
    assert backend._client.logged_in == 1  # 多次调用只登录一次


def test_empty_protocol_becomes_none(backend):
    backend.list_devices(protocol="")
    assert backend._client.last_protocol is None


def test_create_device_auto_start(backend):
    data = backend.create_device("tpl-1", "测试PLC", device_id="d9")
    assert data["device"]["id"] == "d9"
    assert data["started"]["ok"] is True


def test_create_device_passes_protocol_config(backend, monkeypatch):
    captured = {}

    def _spy(self, template_id, name, device_id=None, protocol_config=None):
        captured["protocol_config"] = protocol_config
        return {"id": device_id or "d-new", "template": template_id, "name": name}

    monkeypatch.setattr(FakeClient, "quick_create", _spy)
    backend.create_device("tpl-1", "x", device_id="d10", protocol_config={"slave_id": 11})
    assert captured["protocol_config"] == {"slave_id": 11}  # 冲突自愈：AI 可带新从站号重试


def test_create_device_start_failure_still_returns_device(backend, monkeypatch):
    def _boom(self, device_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(FakeClient, "start_device", _boom)
    data = backend.create_device("tpl-1", "x", device_id="d9")
    assert data["device"]["id"] == "d9"
    assert "boom" in data["started"]["error"]


def test_auth_retry_on_401(backend):
    client = backend._ensure()
    client.fail_auth_once = True
    result = backend.read_points("d1")  # 401 -> 自动重登并重试
    assert result[0]["value"] == 25.5
    assert client.logged_in == 2


def test_get_logs_search_filter(backend):
    assert len(backend.get_logs(search="holding")) == 1
    assert backend.get_logs(search="no-such-keyword") == []


def test_list_limit_truncation(backend):
    backend.list_devices()  # 先触发惰性初始化
    backend._client.list_devices = lambda protocol=None: [{"id": i} for i in range(100)]
    assert len(backend.list_devices(limit=5)) == 5


def test_safe_packs_error_as_json(monkeypatch):
    class BoomClient(FakeClient):
        def health(self):
            raise ValueError("boom")

    monkeypatch.setattr(mcp_server, "ProtoForgeClient", BoomClient)
    b = MCPBackend("http://x")
    data = json.loads(mcp_server._safe(b.server_info))
    assert data["ok"] is False
    assert "boom" in data["error"]


def test_run_mcp_exits_without_mcp(monkeypatch):
    monkeypatch.setattr(mcp_server, "MCP_AVAILABLE", False)
    with pytest.raises(SystemExit) as exc:
        mcp_server.run_mcp()
    assert exc.value.code == 1


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp 包未安装")
def test_build_mcp_server_registers_tools(backend):
    mcp = mcp_server.build_mcp_server(backend)
    try:
        tools = {t.name for t in mcp._tool_manager.list_tools()}
    except AttributeError:
        pytest.skip("FastMCP 内部 API 变化，跳过注册断言")
    assert {"server_info", "create_device", "write_point", "quick_test",
            "connection_guide", "get_logs", "ai_extract_points",
            "ai_create_device_from_text"} <= tools
    assert len(tools) >= 22
