"""ProtoForge MCP Server — AI 编程助手直接驱动仿真器（v1.13.0）。

架构：MCP 工具 → ProtoForgeClient（SDK/REST）→ 运行中的 ProtoForge 实例。
不内嵌引擎、不占协议端口、权限完全复用 RBAC；目标是让 Claude/Cursor 等
AI 助手把"搜模板 → 建设备 → 读写点位 → 跑断言"的开发验证闭环一键跑通。

依赖：`pip install 'protoforge-sim[mcp]'`（mcp SDK 钉在 >=1.2,<2 —— 2.x 把
FastMCP 更名为 MCPServer，等客户端生态普遍迁移后再跟进）。
"""

import json
import logging
import os
import sys
from typing import Any

from protoforge.sdk import ProtoForgeClient

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]
    MCP_AVAILABLE = False
    logger.debug("mcp 未安装，MCP Server 不可用：pip install 'protoforge-sim[mcp]'")

MAX_LIST_LIMIT = 200


def _result(value: Any) -> str:
    """MCP 工具统一返回紧凑 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _safe(fn: Any, *args: Any, **kwargs: Any) -> str:
    """业务异常不向上抛，打包成 {"ok": false, "error": ...} 让 AI 自行决策。"""
    try:
        return _result({"ok": True, "data": fn(*args, **kwargs)})
    except Exception as e:  # noqa: BLE001 — 面向 AI 的边界层，错误必须可见而非中断会话
        logger.debug("MCP 工具 %s 执行失败: %s", getattr(fn, "__name__", "?"), e)
        return _result({"ok": False, "error": f"{type(e).__name__}: {e}"})


class MCPBackend:
    """SDK 客户端持有者：惰性连接 + 自动登录 + token 失效自动重登重试。"""

    def __init__(self, base_url: str, username: str = "admin", password: str = "admin",
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: ProtoForgeClient | None = None
        self._auth_done = False

    def _ensure(self) -> ProtoForgeClient:
        if self._client is None:
            self._client = ProtoForgeClient(base_url=self.base_url, timeout=self.timeout)
        if not self._auth_done:
            self._client.login(self.username, self.password)
            self._auth_done = True
        return self._client

    @staticmethod
    def _is_auth_error(e: Exception) -> bool:
        text = str(e).lower()
        return "401" in text or "unauthorized" in text or "expired" in text

    def call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """统一入口：确保登录 → 调用 → 遇认证错误重登一次再试。"""
        client = self._ensure()
        fn = getattr(client, method_name)
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if not self._is_auth_error(e):
                raise
            logger.debug("MCP 认证失效，重登后重试: %s", e)
            self._auth_done = False
            client = self._ensure()
            return getattr(client, method_name)(*args, **kwargs)

    # ---------- 业务方法（全部经由 self.call 获得重登重试） ----------

    def server_info(self) -> dict[str, Any]:
        return {"url": self.base_url, "health": self.call("health")}

    def list_protocols(self) -> list[Any]:
        return self.call("list_protocols")

    def start_protocol(self, name: str) -> dict[str, Any]:
        return self.call("start_protocol", name)

    def stop_protocol(self, name: str) -> dict[str, Any]:
        return self.call("stop_protocol", name)

    def list_templates(self, protocol: str | None = None, limit: int = 30) -> list[Any]:
        items = self.call("list_templates", protocol=protocol or None)
        return items[: max(1, min(limit, MAX_LIST_LIMIT))]

    def search_templates(self, query: str, limit: int = 15) -> list[Any]:
        items = self.call("search_templates", q=query)
        return items[: max(1, min(limit, MAX_LIST_LIMIT))]

    def create_device(self, template_id: str, name: str, device_id: str | None = None,
                      start: bool = True, protocol_config: dict[str, Any] | None = None) -> dict[str, Any]:
        device = self.call("quick_create", template_id, name, device_id=device_id,
                           protocol_config=protocol_config)
        started: Any = None
        if start:
            try:
                started = self.call("start_device", device.get("id"))
            except Exception as e:  # 建成功但起失败：如实回传，AI 可自行重试
                started = {"error": f"{type(e).__name__}: {e}"}
        return {"device": device, "started": started}

    def list_devices(self, protocol: str | None = None, limit: int = 50) -> list[Any]:
        items = self.call("list_devices", protocol=protocol or None)
        return items[: max(1, min(limit, MAX_LIST_LIMIT))]

    def get_device(self, device_id: str) -> dict[str, Any]:
        return self.call("get_device", device_id)

    def delete_device(self, device_id: str) -> dict[str, Any]:
        return self.call("delete_device", device_id)

    def start_device(self, device_id: str) -> dict[str, Any]:
        return self.call("start_device", device_id)

    def stop_device(self, device_id: str) -> dict[str, Any]:
        return self.call("stop_device", device_id)

    def read_points(self, device_id: str, limit: int = 100) -> list[Any]:
        items = self.call("read_points", device_id)
        return items[: max(1, min(limit, MAX_LIST_LIMIT))]

    def write_point(self, device_id: str, point_name: str, value: Any) -> dict[str, Any]:
        return self.call("write_point", device_id, point_name, value)

    def list_scenarios(self) -> list[Any]:
        return self.call("list_scenarios")

    def start_scenario(self, scenario_id: str) -> dict[str, Any]:
        return self.call("start_scenario", scenario_id)

    def stop_scenario(self, scenario_id: str) -> dict[str, Any]:
        return self.call("stop_scenario", scenario_id)

    def get_logs(self, count: int = 50, protocol: str | None = None, search: str = "") -> list[Any]:
        logs = self.call("get_logs", count=max(1, min(count, MAX_LIST_LIMIT)), protocol=protocol or None)
        if search:
            needle = search.lower()
            logs = [entry for entry in logs
                    if needle in json.dumps(entry, ensure_ascii=False, default=str).lower()]
        return logs

    def quick_test(self, scope: str = "all") -> dict[str, Any]:
        return self.call("quick_test", scope=scope)

    def get_test_report(self, report_id: str) -> dict[str, Any]:
        return self.call("get_test_report", report_id)

    def connection_guide(self, device_id: str) -> dict[str, Any]:
        return self.call("get_device_connection_guide", device_id)

    def ai_extract_points(self, text: str, protocol_hint: str = "") -> dict[str, Any]:
        return self.call("ai_extract_points", text, protocol_hint=protocol_hint)

    def ai_create_device_from_text(self, text: str, name: str = "",
                                   device_id: str | None = None,
                                   protocol_hint: str = "") -> dict[str, Any]:
        return self.call("ai_create_device_from_text", text, name=name,
                         device_id=device_id, protocol_hint=protocol_hint)

    def ai_analyze_logs(self, question: str = "", count: int = 200,
                        protocol: str | None = None, device_id: str | None = None,
                        direction: str | None = None) -> dict[str, Any]:
        return self.call("ai_analyze_logs", question=question, count=count,
                         protocol=protocol, device_id=device_id, direction=direction)


def build_mcp_server(backend: MCPBackend) -> "FastMCP":
    """把 backend 的业务方法注册为 MCP 工具（闭包保留函数名/文档串以生成 schema）。"""
    mcp = FastMCP(
        "protoforge",
        instructions=(
            "ProtoForge industrial protocol simulator control tools. "
            "Typical verify loop: search_templates -> create_device (auto-started) -> "
            "read_points / write_point -> quick_test -> connection_guide tells your client "
            "code which host:port to connect. All tools return a JSON string; check the "
            "'ok' field first."
        ),
    )

    @mcp.tool()
    def server_info() -> str:
        """Get connected ProtoForge instance info: URL, version, uptime, device count. Call first to verify connectivity."""
        return _safe(backend.server_info)

    @mcp.tool()
    def list_protocols() -> str:
        """List all protocol services and their running state (modbus_tcp, s7, opcua, mqtt, ...)."""
        return _safe(backend.list_protocols)

    @mcp.tool()
    def start_protocol(name: str) -> str:
        """Start a protocol service (e.g. modbus_tcp / s7 / opcua / mqtt)."""
        return _safe(backend.start_protocol, name)

    @mcp.tool()
    def stop_protocol(name: str) -> str:
        """Stop a running protocol service."""
        return _safe(backend.stop_protocol, name)

    @mcp.tool()
    def list_templates(protocol: str = "", limit: int = 30) -> str:
        """List device templates (133 built-in: PLC/sensor/CNC/camera/meter/IED...). Filter by protocol, e.g. modbus_tcp."""
        return _safe(backend.list_templates, protocol or None, limit)

    @mcp.tool()
    def search_templates(query: str, limit: int = 15) -> str:
        """Search device templates by keyword, e.g. 'siemens', '水表', 'camera'."""
        return _safe(backend.search_templates, query, limit)

    @mcp.tool()
    def create_device(template_id: str, name: str, device_id: str = "", start: bool = True,
                      protocol_config: dict | None = None) -> str:
        """Create a simulated device from a template (auto-started by default). Returns device id/protocol/points. If creation fails with a slave_id conflict, retry with protocol_config={\"slave_id\": <suggested>}."""
        return _safe(backend.create_device, template_id, name, device_id or None, start,
                     protocol_config)

    @mcp.tool()
    def list_devices(protocol: str = "", limit: int = 50) -> str:
        """List simulated devices with id/name/protocol/status/point count."""
        return _safe(backend.list_devices, protocol or None, limit)

    @mcp.tool()
    def get_device(device_id: str) -> str:
        """Get one device's full info: status, points, addresses, config."""
        return _safe(backend.get_device, device_id)

    @mcp.tool()
    def delete_device(device_id: str) -> str:
        """Delete a simulated device."""
        return _safe(backend.delete_device, device_id)

    @mcp.tool()
    def start_device(device_id: str) -> str:
        """Start a simulated device (protocol endpoints become reachable)."""
        return _safe(backend.start_device, device_id)

    @mcp.tool()
    def stop_device(device_id: str) -> str:
        """Stop a simulated device."""
        return _safe(backend.stop_device, device_id)

    @mcp.tool()
    def read_points(device_id: str, limit: int = 100) -> str:
        """Read current values of all (or up to limit) points on a device."""
        return _safe(backend.read_points, device_id, limit)

    @mcp.tool()
    def write_point(device_id: str, point_name: str, value: float | int | str | bool) -> str:
        """Write a value to one point (like writing to a real PLC register)."""
        return _safe(backend.write_point, device_id, point_name, value)

    @mcp.tool()
    def list_scenarios() -> str:
        """List simulation scenarios (multi-device topologies with rules)."""
        return _safe(backend.list_scenarios)

    @mcp.tool()
    def start_scenario(scenario_id: str) -> str:
        """Start a whole scenario (all its devices)."""
        return _safe(backend.start_scenario, scenario_id)

    @mcp.tool()
    def stop_scenario(scenario_id: str) -> str:
        """Stop a running scenario."""
        return _safe(backend.stop_scenario, scenario_id)

    @mcp.tool()
    def get_logs(count: int = 50, protocol: str = "", search: str = "") -> str:
        """Fetch recent protocol message logs (WebSocket debug stream snapshot). Filter by protocol or keyword."""
        return _safe(backend.get_logs, count, protocol or None, search)

    @mcp.tool()
    def quick_test(scope: str = "all") -> str:
        """Run the built-in auto-generated assertion suite (scope: all/device/scenario)."""
        return _safe(backend.quick_test, scope)

    @mcp.tool()
    def get_test_report(report_id: str) -> str:
        """Fetch one test report with per-step assertion results."""
        return _safe(backend.get_test_report, report_id)

    @mcp.tool()
    def connection_guide(device_id: str) -> str:
        """Get how a client should connect to this simulated device: protocol, host:port, addressing examples."""
        return _safe(backend.connection_guide, device_id)

    @mcp.tool()
    def ai_extract_points(text: str, protocol_hint: str = "") -> str:
        """Parse unstructured datasheet/manual text into a structured point table via the configured LLM (local Ollama by default). Returns device name/protocol/slave_id/points[] + notes. Review before creating."""
        return _safe(backend.ai_extract_points, text, protocol_hint)

    @mcp.tool()
    def ai_create_device_from_text(text: str, name: str = "", device_id: str = "",
                                   protocol_hint: str = "") -> str:
        """One-shot: LLM parses datasheet text into a point table, then creates + auto-starts the simulated device. Returns device info incl. point count and notes."""
        return _safe(backend.ai_create_device_from_text, text, name, device_id or None,
                     protocol_hint)

    @mcp.tool()
    def ai_analyze_logs(question: str = "", count: int = 200, protocol: str = "",
                        device_id: str = "", direction: str = "") -> str:
        """AI troubleshoot (v1.13.4): analyze recent protocol debug logs with the configured LLM (local Ollama by default). Returns a diagnosis where every finding cites real log lines as evidence. Filters: protocol / device_id / direction (inbound|outbound|system)."""
        return _safe(backend.ai_analyze_logs, question, count, protocol or None,
                     device_id or None, direction or None)

    @mcp.resource("protoforge://info")
    def protoforge_info() -> str:
        """Current ProtoForge instance info."""
        return _safe(backend.server_info)

    @mcp.prompt()
    def verify_loop(device_hint: str = "") -> str:
        """Guide the AI through the full simulate-verify loop on ProtoForge."""
        hint = device_hint or "any PLC / sensor / camera / meter"
        return (
            "Goal: create a simulated device on ProtoForge and verify it end-to-end.\n"
            f"1. search_templates with a keyword matching: {hint}\n"
            "2. create_device with the best template (it auto-starts)\n"
            "3. read_points to confirm values exist; write_point to force one value\n"
            "4. quick_test to run built-in assertions\n"
            "5. connection_guide to report the exact host:port and addressing your "
            "client code should use.\n"
            "Check the 'ok' field of every JSON result before moving on."
        )

    return mcp


def run_mcp(server_url: str = "", username: str = "", password: str = "",
            transport: str = "stdio", host: str = "127.0.0.1", port: int = 8808,
            timeout: float = 30.0) -> None:
    """CLI 入口：`protoforge mcp`。"""
    if not MCP_AVAILABLE:
        print("! MCP 依赖未安装。安装：pip install 'protoforge-sim[mcp]'")
        sys.exit(1)

    server_url = server_url or os.environ.get("PROTOFORGE_MCP_URL", "http://localhost:8000")
    username = username or os.environ.get("PROTOFORGE_MCP_USERNAME", "admin")
    password = password or os.environ.get("PROTOFORGE_MCP_PASSWORD", "admin")

    backend = MCPBackend(server_url, username=username, password=password, timeout=timeout)
    mcp = build_mcp_server(backend)

    # stdio 传输复用 stdout 走协议帧，横幅必须打到 stderr
    print(f"+ ProtoForge MCP Server 就绪 -> {backend.base_url} (transport={transport})", file=sys.stderr)
    print("  tools: 24 (system/protocols/templates/devices/points/scenarios/logs/tests/guide/ai)", file=sys.stderr)
    if transport == "streamable-http":
        mcp.settings.host = host
        mcp.settings.port = port
        print(f"  listening http://{host}:{port}/mcp", file=sys.stderr)
    mcp.run(transport=transport)  # type: ignore[arg-type]
