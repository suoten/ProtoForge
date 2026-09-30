"""Connection diagnostics API routes.

Helps users self-diagnose the most common "cannot connect" issues:
  - is the protocol service running, and is its bind address a local NIC?
  - is the simulated service port actually reachable (TCP connect)?
  - can the host reach an external target (EMQX / SIP platform / custom server)?

All checks return structured results with message keys so the frontend can
render them localized (zh/en).
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Depends

from protoforge.api.v1._helpers import _get_engine
from protoforge.api.v1.auth import require_viewer
from protoforge.core.netutils import is_local_bind_host, list_local_ips
from protoforge.protocols.base import ProtocolStatus

router = APIRouter()
logger = logging.getLogger(__name__)


def _engine_or_none():
    return _get_engine()


@router.get("/diagnostics/nics")
async def list_nics(_user: dict[str, Any] = Depends(require_viewer)):
    """列出本机全部 IPv4 地址（供"绑定地址应填什么"引导）。"""
    return {"addresses": list_local_ips()}


@router.post("/diagnostics/protocol/{protocol_name}")
async def diagnose_protocol(protocol_name: str, _user: dict[str, Any] = Depends(require_viewer)):
    """对指定协议服务做一键体检，返回逐项检查结果。

    每项: { key, ok, detail, suggestion? } —— key/selection 为前端 i18n 键。
    """
    engine = _get_engine()
    server = engine.get_protocol_server(protocol_name) if engine else None
    checks: list[dict[str, Any]] = []

    def add(key: str, ok: bool, detail: str = "", suggestion: str | None = None, params: dict | None = None):
        checks.append({"key": key, "ok": ok, "detail": detail, "suggestion": suggestion, "params": params or {}})

    # 1. 协议已注册
    add("registered", server is not None,
        detail=f"protocol={protocol_name}",
        suggestion=None if server is not None else "diag_s_registered")

    if server is None:
        return {"protocol": protocol_name, "ok": False, "checks": checks}

    # 2. 服务运行状态
    running = server.status == ProtocolStatus.RUNNING
    add("running", running,
        detail=f"status={server.status.value}",
        suggestion=None if running else "diag_s_running")

    if not running:
        return {"protocol": protocol_name, "ok": False, "checks": checks}

    # 3. 监听地址是否本机可绑定
    host = getattr(server, "_host", "") or ""
    serial_mode = bool(host) and is_serial_like(host)
    if serial_mode:
        add("bind_address", True, detail=f"serial={host}")
    else:
        bindable = is_local_bind_host(host)
        add("bind_address", bindable, detail=f"host={host}",
            suggestion=None if bindable else "diag_s_bind")

    # 4. 端口实际可达（TCP 连接测试）
    port = server.get_running_port()
    connect_host = host if host and not is_serial_like(host) and host not in ("0.0.0.0", "::") else "127.0.0.1"
    if isinstance(port, int) and port > 0 and not serial_mode:
        ok, latency_ms, err = await _tcp_probe(connect_host, int(port))
        add("port_listening", ok,
            detail=f"{connect_host}:{port}" + (f" ({latency_ms}ms)" if ok else f" error={err}"),
            suggestion=None if ok else "diag_s_port",
            params={"host": connect_host, "port": str(port)})
    else:
        add("port_listening", True, detail="skipped (serial mode or no TCP port)")

    # 5. 设备注册数量
    try:
        device_count = len(server._device_configs)
    except Exception:
        device_count = 0
    add("devices_registered", device_count > 0, detail=f"count={device_count}",
        suggestion=None if device_count > 0 else "diag_s_devices")

    overall = all(c["ok"] for c in checks)
    return {"protocol": protocol_name, "ok": overall, "checks": checks}


@router.post("/diagnostics/outbound")
async def diagnose_outbound(target: dict[str, Any] = Body(...),
                            _user: dict[str, Any] = Depends(require_viewer)):
    """测试本机到外部目标的 TCP 可达性（如 EMQX / SIP 平台 / 自定义服务器）。

    body: { host: str, port: int }
    """
    host = str(target.get("host", "")).strip()
    port = int(target.get("port", 0))
    if not host or not 1 <= port <= 65535:
        return {"ok": False, "error": "invalid host/port"}
    ok, latency_ms, err = await _tcp_probe(host, port, timeout=4.0)
    result: dict[str, Any] = {"ok": ok, "host": host, "port": port}
    if ok:
        result["latency_ms"] = latency_ms
    else:
        result["error"] = err or "unreachable"
        result["suggestion"] = "diag_s_outbound"
    return result


def is_serial_like(host: str) -> bool:
    return host.startswith("/dev/tty") or host.startswith("/dev/serial") or host.upper().startswith("COM")


async def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> tuple[bool, float | None, str | None]:
    """TCP 连接探测，返回 (是否可达, 延迟ms, 错误信息)。"""
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        latency = round((time.monotonic() - start) * 1000, 1)
        writer.close()
        return True, latency, None
    except Exception as e:
        return False, None, str(e)
