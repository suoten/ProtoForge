"""ProtoForge 统一集成管理器

重构要点:
1. 合并 edgelite.py 的 REST 直连功能，IntegrationManager 成为唯一联调入口
2. 消除双路径冲突（原 edgelite.py + IntegrationManager 并行推送）
3. 增加智能管线自修复（verify_pipeline 可自动修复问题）
4. 增加双向状态同步（定期轮询 + WebSocket 实时）
5. 增加智能配置发现（同机部署自动检测）
"""

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx

from protoforge.core.defaults import HTTP_TIMEOUT_DEFAULT, HTTP_TIMEOUT_SHORT
from protoforge.core.event_bus import (
    EventBus,
    DeviceCreatedEvent,
    DeviceStartedEvent,
    DeviceStoppedEvent,
    DeviceRemovedEvent,
)
from protoforge.core.integration.channel import HttpChannel, WebSocketChannel, ChannelFactory
from protoforge.core.integration.protocol import (
    ACCESS_MODE_MAP,
    PROTOCOL_MAP_BASE,
    DataTypeMapper,
    ProtocolMapper,
)
from protoforge.core.integration.state import ConnectionStateMachine, ConnectionState
from protoforge.core.integration.retry import RetryPolicy, IntegrationError, NetworkError
from protoforge.core.integration.auth import IntegrationAuth
from protoforge.core.integration.metrics import IntegrationMetrics
from protoforge.core.integration.validator import MappingValidator
from protoforge.core.messages import desc

logger = logging.getLogger(__name__)

# 仅保留 EdgeLite 支持的协议映射
PROTOCOL_MAP: dict[str, str] = {
    k: v for k, v in PROTOCOL_MAP_BASE.items() if v is not None
}

EDGELITE_DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


class AlarmReactionRule:
    def __init__(
        self,
        rule_id: str = "",
        source_device_id: str = "",
        alarm_severity: str = "",
        action: str = "stop_device",
        target_device_id: str = "",
        action_params: dict[str, Any] | None = None,
        enabled: bool = True,
    ):
        self.rule_id = rule_id
        self.source_device_id = source_device_id
        self.alarm_severity = alarm_severity
        self.action = action
        self.target_device_id = target_device_id
        self.action_params = action_params or {}
        self.enabled = enabled

    def matches(self, source_device_id: str, severity: str) -> bool:
        if not self.enabled:
            return False
        if self.source_device_id and self.source_device_id != source_device_id:
            return False
        if self.alarm_severity and self.alarm_severity != severity:
            return False
        return True


class DeviceStatusCache:
    """带过期时间的设备状态缓存"""

    def __init__(self, ttl_seconds: float = 60.0):
        self._cache: dict[str, tuple[str, float]] = {}
        self._ttl = ttl_seconds

    def get(self, device_id: str) -> str | None:
        if device_id not in self._cache:
            return None
        status, timestamp = self._cache[device_id]
        if time.time() - timestamp > self._ttl:
            del self._cache[device_id]
            return None
        return status

    def set(self, device_id: str, status: str) -> None:
        self._cache[device_id] = (status, time.time())

    def remove(self, device_id: str) -> None:
        self._cache.pop(device_id, None)

    def clear(self) -> None:
        self._cache.clear()


class IntegrationManager:
    """ProtoForge 统一集成管理器 — 与 EdgeLite 联调的唯一入口。

    职责:
    - 设备推送/删除/更新 (REST API)
    - 管线验证与自修复
    - 连接测试
    - 数据读取
    - WebSocket 实时数据回传
    - 告警联动
    - 双向状态同步
    """

    def __init__(
        self,
        event_bus: EventBus,
        enabled: bool = False,
        edgelite_url: str = "",
        username: str = "admin",
        password: str = "",
    ):
        self._event_bus = event_bus
        self._enabled = enabled
        self._edgelite_url = edgelite_url
        self._username = username
        self._password = password

        # HTTP 通道（REST API 直连，用于设备 CRUD 和管线验证）
        self._http_client: httpx.AsyncClient | None = None
        self._auth: IntegrationAuth | None = None

        # WebSocket 通道（实时数据回传）
        self._ws_channel: WebSocketChannel | None = None

        # 状态管理
        self._state = ConnectionStateMachine(on_change=self._on_state_change)
        self._retry = RetryPolicy()
        self._metrics = IntegrationMetrics()

        # 映射与校验
        self._protocol_mapper = ProtocolMapper()
        self._data_type_mapper = DataTypeMapper()
        self._validator = MappingValidator(self._protocol_mapper, self._data_type_mapper)

        # 缓存与规则
        self._device_status_cache = DeviceStatusCache()
        self._alarm_reaction_rules: list[AlarmReactionRule] = []
        self._backhaul_data: dict[str, list[dict[str, Any]]] = {}

        # Token 缓存
        self._token_cache: dict[str, dict[str, Any]] = {}
        self._token_cache_lock = asyncio.Lock()
        self._TOKEN_REFRESH_MARGIN = 30

        # 运行状态
        self._running = False
        self._retry_queue: asyncio.Queue = asyncio.Queue()
        self._retry_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None
        self._ws_reconnect_task: asyncio.Task | None = None
        self._sync_interval = 60.0  # 状态同步间隔（秒）
        self._ws_reconnect_interval = 10.0  # WebSocket 重连间隔（秒）

        # HTTP Webhook 数据推送（被动协议需要 ProtoForge 主动推送模拟数据到 EdgeLite）
        self._http_push_tasks: dict[str, asyncio.Task] = {}  # device_id -> task
        self._http_push_interval = 5.0  # 推送间隔（秒）

    # ─── 配置与生命周期 ───────────────────────────────────────

    def configure(self, edgelite_url: str, username: str = "admin", password: str = "") -> None:
        self._edgelite_url = edgelite_url
        self._username = username
        self._password = password
        self._enabled = bool(edgelite_url)

    async def start(self) -> None:
        if not self._enabled or not self._edgelite_url:
            logger.info("IntegrationManager disabled, no EdgeLite URL configured")
            return

        self._running = True
        self._auth = IntegrationAuth(
            base_url=self._edgelite_url,
            username=self._username,
            password=self._password,
        )

        # 初始化 HTTP 客户端
        self._http_client = httpx.AsyncClient(
            base_url=self._edgelite_url.rstrip("/"),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            timeout=HTTP_TIMEOUT_DEFAULT,
        )

        # 订阅事件
        self._event_bus.on("DeviceCreatedEvent", self._on_device_created)
        self._event_bus.on("DeviceStartedEvent", self._on_device_started)
        self._event_bus.on("DeviceStoppedEvent", self._on_device_stopped)
        self._event_bus.on("DeviceRemovedEvent", self._on_device_removed)
        self._event_bus.on("ProtocolStatusEvent", self._on_protocol_status)

        # 连接测试
        try:
            await self._connect_http()
        except Exception as e:
            logger.warning("IntegrationManager initial HTTP connection failed: %s", e)

        # WebSocket 连接（非致命）
        try:
            await self._connect_websocket()
        except Exception as e:
            logger.warning("IntegrationManager WebSocket connection failed (non-fatal): %s", e)

        # 启动后台任务
        self._retry_task = asyncio.create_task(self._retry_queue_consumer())
        self._sync_task = asyncio.create_task(self._periodic_state_sync())
        self._ws_reconnect_task = asyncio.create_task(self._ws_reconnect_loop())

        logger.info("IntegrationManager started, target: %s", self._edgelite_url)

    async def stop(self) -> None:
        self._running = False

        # 取消后台任务
        for task_attr in ("_retry_task", "_sync_task", "_ws_reconnect_task"):
            task = getattr(self, task_attr, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("Error cancelling background task: %s", e)

        # 清理事件订阅
        self._event_bus.off("DeviceCreatedEvent", self._on_device_created)
        self._event_bus.off("DeviceStartedEvent", self._on_device_started)
        self._event_bus.off("DeviceStoppedEvent", self._on_device_stopped)
        self._event_bus.off("DeviceRemovedEvent", self._on_device_removed)
        self._event_bus.off("ProtocolStatusEvent", self._on_protocol_status)

        # 关闭连接
        # 停止所有 HTTP 推送任务
        for device_id in list(self._http_push_tasks.keys()):
            self._stop_http_push(device_id)

        if self._ws_channel:
            try:
                await self._ws_channel.close()
            except Exception as e:
                logger.debug("Failed to close WebSocket channel: %s", e)
            self._ws_channel = None

        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception as e:
                logger.debug("Failed to close HTTP client: %s", e)
            self._http_client = None

        if self._auth:
            try:
                await self._auth.close()
            except Exception as e:
                logger.debug("Failed to close auth session: %s", e)
            self._auth = None

        logger.info("IntegrationManager stopped")

    # ─── HTTP 连接管理 ───────────────────────────────────────

    async def _connect_http(self) -> None:
        """建立 HTTP 连接（认证 + 状态检查）。"""
        if not await self._state.transition(ConnectionState.CONNECTING):
            return
        try:
            if self._auth:
                await self._auth.ensure_token()
            await self._state.transition(ConnectionState.CONNECTED)
            self._metrics.set_connected()
            await self._flush_retry_queue()
        except Exception as e:
            await self._state.transition(ConnectionState.DISCONNECTED)
            logger.warning("HTTP connection failed: %s", e)

    async def _ensure_connected(self) -> bool:
        if self._http_client and self._state.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            return True
        try:
            await self._connect_http()
            return self._state.state == ConnectionState.CONNECTED
        except Exception:
            return False

    async def _get_auth_headers(self) -> tuple[dict[str, str], Exception | None]:
        """获取认证头，返回 (headers, error)。"""
        if not self._auth:
            return {}, IntegrationError("Auth not initialized")
        try:
            await self._auth.ensure_token()
            return {"Authorization": f"Bearer {self._auth.token}"}, None
        except Exception as e:
            return {}, e

    async def _request_with_auth(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """带认证的 HTTP 请求，401 时自动重新登录重试。"""
        if not self._http_client:
            raise ConnectionError("HTTP client not initialized")

        headers, auth_err = await self._get_auth_headers()
        if auth_err:
            raise auth_err

        req_headers = {**headers, **kwargs.pop("headers", {})}
        resp = await getattr(self._http_client, method)(path, headers=req_headers, **kwargs)

        if resp.status_code == 401 and self._auth:
            # Token 过期，重新登录
            try:
                await self._auth.refresh_token()
                req_headers["Authorization"] = f"Bearer {self._auth.token}"
                resp = await getattr(self._http_client, method)(path, headers=req_headers, **kwargs)
            except Exception as e:
                logger.debug("Token refresh retry failed: %s", e)

        return resp

    # ─── WebSocket 连接 ───────────────────────────────────────

    async def _connect_websocket(self) -> None:
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(self._edgelite_url)
            ws_proto = "wss" if parsed.scheme == "https" else "ws"
            ws_host = parsed.hostname or "localhost"
            ws_port = f":{parsed.port}" if parsed.port else ""
            ws_url = f"{ws_proto}://{ws_host}{ws_port}/ws/v1/integration"

            # FIX: EdgeLite 要求首帧发送 {"type": "auth", "token": "xxx"}，
            # 而非将 token 放入 URL 参数（URL 中的 token 会泄露到日志）。
            # 认证流程：auth消息 → handshake消息
            ws_heartbeat_interval = 30.0
            ws_channel = WebSocketChannel(url=ws_url, heartbeat_interval=ws_heartbeat_interval)
            ws_channel.on_message("point_data", self._on_ws_point_data)
            ws_channel.on_message("device_status_changed", self._on_ws_device_status)
            ws_channel.on_message("alarm_fired", self._on_ws_alarm)
            ws_channel.on_message("alarm_recovered", self._on_ws_alarm)
            ws_channel.on_message("handshake_ack", self._on_ws_handshake_ack)
            await ws_channel.connect()

            # 第一步：发送认证消息
            if self._auth:
                await self._auth.ensure_token()
                auth_msg = {"type": "auth", "token": self._auth.token}
                await ws_channel.send(auth_msg)

            # 第二步：发送握手消息
            handshake_msg = {
                "type": "handshake",
                "version": "1.0",
                "protocols": [],
                "capabilities": ["push_device", "device_control", "delete_device", "backhaul", "alarm_forward"],
                "heartbeat_interval": ws_heartbeat_interval,
            }
            await ws_channel.send(handshake_msg)

            self._ws_channel = ws_channel
            # 认证和握手完成，启动心跳
            ws_channel.mark_ready()
            logger.info("WebSocket integration channel connected to %s", ws_url)
        except ImportError:
            logger.warning("websockets library not installed, WebSocket integration channel unavailable")
        except Exception as e:
            logger.warning("WebSocket integration channel connection failed: %s", e)

    async def _on_ws_handshake_ack(self, message: dict[str, Any]) -> None:
        session_id = message.get("session_id", "")
        protocols = message.get("protocols", [])
        if protocols:
            self._protocol_mapper.update_edgelite_protocols(protocols)
        logger.info("WebSocket handshake acknowledged, session=%s protocols=%s", session_id, protocols)

    async def _on_ws_point_data(self, message: dict[str, Any]) -> None:
        await self.handle_backhaul_message(message)

    async def _on_ws_device_status(self, message: dict[str, Any]) -> None:
        await self.handle_backhaul_message(message)

    async def _on_ws_alarm(self, message: dict[str, Any]) -> None:
        await self.handle_backhaul_message(message)

    # ─── 设备推送（核心功能，合并自 edgelite.py）───────────────

    async def push_device(self, device: Any, protoforge_host: str = "") -> dict[str, Any]:
        """推送设备到 EdgeLite — 唯一的推送入口。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import (
            convert_device_to_edgelite,
            get_edgelite_config_from_device,
            _normalize_device_id,
            _get_protocol_status,
            _is_edgelite_local,
            get_protoforge_host,
            EDGELITE_PIP_PACKAGES,
        )

        el_config = get_edgelite_config_from_device(device)
        if not el_config.get("url"):
            return {
                "ok": False, "skipped": True,
                "reason": "edgelite_url not configured",
                "error_type": "not_configured",
                "suggestion": desc("edgelite.suggestion.configure_url"),
            }

        # 构建推送 payload
        payload = convert_device_to_edgelite(device, protoforge_host, self._protocol_mapper, self._data_type_mapper, el_config=el_config)
        if payload is None:
            return {
                "ok": False, "skipped": True,
                "reason": "Protocol not supported by EdgeLite",
                "error_type": "unsupported",
                "suggestion": desc("edgelite.suggestion.unsupported_protocol"),
            }

        # 兼容性校验
        points_data = getattr(device, "points", []) or []
        points_list = []
        for p in points_data:
            if hasattr(p, "model_dump"):
                points_list.append(p.model_dump())
            elif hasattr(p, "__dict__"):
                points_list.append(p.__dict__)
            else:
                points_list.append(p)

        report = self._validator.validate(
            device_id=payload.get("device_id", ""),
            protocol=payload.get("protocol", ""),
            points=points_list,
            driver_config=payload.get("config", {}),
        )
        if not report.compatible:
            return {"ok": False, "skipped": True, "reason": "Compatibility check failed", "report": report}

        # 检查协议服务器是否运行
        protocol = getattr(device, "protocol", "") or ""
        protocol_status = _get_protocol_status(protocol)
        if protocol_status != "running":
            return {
                "ok": False,
                "error": f"Protocol {protocol} is not running (status: {protocol_status})",
                "error_type": "protocol_not_running",
                "suggestion": desc("edgelite.suggestion.protocol_not_running"),
                "driver_config": payload.get("config", {}),
            }

        # 检测私有 IP 问题：EdgeLite 远程部署时，ProtoForge 的局域网 IP 无法被 EdgeLite 访问
        driver_config = payload.get("config", {})
        driver_host = driver_config.get("host") or driver_config.get("ip") or ""
        is_private_ip = driver_host and (
            driver_host.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                                   "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                                   "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                                   "172.30.", "172.31.", "192.168.")) or
            driver_host in ("127.0.0.1", "localhost")
        )
        is_edgelite_remote = el_config.get("url") and not _is_edgelite_local(el_config)
        if is_private_ip and is_edgelite_remote:
            actual_host = get_protoforge_host()
            logger.warning(
                "Device %s push: driver host %s is a private IP, EdgeLite (%s) may not be able to reach it. "
                "Current protoforge_public_host setting: %s. Please configure a public/reachable IP in System Settings.",
                payload["device_id"], driver_host, el_config.get("url"), actual_host
            )
            # 将检测结果写入日志，但不阻止推送（让 EdgeLite 决定是否失败）
            payload["_private_ip_warning"] = True
            payload["_suggested_host"] = actual_host

        # 通过 REST API 推送
        start_time = time.time()
        try:
            if not await self._ensure_connected():
                return {"ok": False, "error": desc("edgelite.error.cannot_connect"), "error_type": "connection"}

            resp = await self._request_with_auth("post", "/api/v1/devices", json=payload)

            if resp.status_code in (200, 201):
                latency_ms = (time.time() - start_time) * 1000
                self._metrics.record_push_success(latency_ms)
                logger.info("Device %s registered to EdgeLite", payload["device_id"])

                # 被动协议（HTTP/Webhook）需要 ProtoForge 主动推送模拟数据到 EdgeLite
                protocol = payload.get("protocol", "")
                if protocol in ("http", "webhook"):
                    self._start_http_push(payload["device_id"], device)

                return {"ok": True, "action": "created", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}

            if resp.status_code == 409:
                return await self._handle_push_conflict(resp, payload, el_config, start_time)

            if resp.status_code == 422:
                return {
                    "ok": False,
                    "error": f"EdgeLite rejected push: {resp.text[:300]}",
                    "error_type": "validation_error",
                    "suggestion": desc("edgelite.suggestion.check_config"),
                }

            if resp.status_code >= 500:
                return {
                    "ok": False,
                    "error": f"EdgeLite server error: HTTP {resp.status_code}",
                    "error_type": "edgelite_error",
                }

            return {"ok": False, "error": f"Create failed: HTTP {resp.status_code}", "error_type": "create_failed"}

        except httpx.ConnectError:
            self._metrics.record_push_failure()
            return {"ok": False, "error": desc("edgelite.error.cannot_connect"), "error_type": "connection"}
        except httpx.TimeoutException:
            self._metrics.record_push_failure()
            return {"ok": False, "error": desc("edgelite.error.connect_timeout"), "error_type": "timeout"}
        except Exception as e:
            self._metrics.record_push_failure()
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    async def _handle_push_conflict(
        self, create_resp: httpx.Response, payload: dict[str, Any],
        el_config: dict[str, str], start_time: float
    ) -> dict[str, Any]:
        """处理 409 冲突：区分驱动启动失败 vs 设备已存在。"""
        from protoforge.core.edgelite import EDGELITE_PIP_PACKAGES
        conflict_detail = ""
        try:
            conflict_data = create_resp.json()
            if isinstance(conflict_data, dict):
                conflict_detail = str(conflict_data.get("detail", ""))
        except Exception as e:
            logger.debug("Failed to parse conflict detail: %s", e)

        driver_config = payload.get("config", {})
        is_driver_failure = any(
            kw in conflict_detail.lower()
            for kw in ("driver", "start failed", "connection")
        )

        # 私有 IP 超时检测：如果错误包含 timeout 且驱动 IP 为私有地址，给出更明确提示
        is_private_ip_timeout = (
            is_driver_failure and
            any(kw in conflict_detail.lower() for kw in ("timeout", "receive timeout", "connect", "unreachable", "refused")) and
            driver_config.get("host") and (
                driver_config["host"].startswith(("10.", "172.", "192.168.")) or
                driver_config["host"] in ("127.0.0.1", "localhost")
            )
        )
        if is_private_ip_timeout:
            from protoforge.core.edgelite import get_protoforge_host
            actual_host = get_protoforge_host()
            suggestion = (
                f"EdgeLite 驱动连接超时。驱动配置的 IP 地址 ({driver_config.get('host')}) 是私有地址，"
                f"EdgeLite 无法从外网访问。请在【系统设置 > 公网地址】中配置 ProtoForge 的公网可达地址，"
                f"例如通过反向代理或内网穿透映射。当前配置: {actual_host}"
            )

        # 提取缺失的 pip 包提示
        pip_hint = ""
        missing_packages = []
        for pattern in [
            r"(?:未安装[，,]?\s*请执行|not installed[.,]?\s*(?:Run|run)[.:]?\s*)pip install\s+(\S+)",
            r"pip install\s+(\S+)",
        ]:
            for m in re.finditer(pattern, conflict_detail):
                pkg = m.group(1).strip().rstrip('.')
                if pkg and len(pkg) > 2 and not pkg.startswith("http"):
                    correct_pkg = EDGELITE_PIP_PACKAGES.get(pkg.lower(), [pkg])[0]
                    if correct_pkg not in missing_packages:
                        missing_packages.append(correct_pkg)
        if missing_packages:
            pip_hint = "pip install " + " ".join(missing_packages)

        suggestion = ""
        if is_driver_failure:
            from protoforge.core.edgelite import _format_driver_config_for_display
            logger.warning("EdgeLite device %s driver start failed: %s", payload["device_id"], conflict_detail)
            conn_info = _format_driver_config_for_display(driver_config)
            # 私有 IP 超时已经在上面设置了正确的 suggestion，这里不再覆盖
            if not is_private_ip_timeout:
                suggestion = desc("edgelite.suggestion.check_driver_config")
                if pip_hint:
                    suggestion = f"{suggestion}\n\n安装缺失依赖: {pip_hint}"

            # 不可恢复的错误（依赖包缺失）→ 清理 EdgeLite 上的失败设备记录，避免下次推送继续 409
            is_unrecoverable = any(
                kw in conflict_detail.lower()
                for kw in ("未安装", "not installed", "no module", "importerror", "dll", "fwlib")
            )
            if is_unrecoverable:
                try:
                    device_id = payload["device_id"]
                    await self._request_with_auth("delete", f"/api/v1/devices/{quote(str(device_id), safe='')}")
                    logger.info("Cleaned up failed device %s on EdgeLite (unrecoverable driver error)", device_id)
                except Exception as e:
                    logger.debug("Failed to clean up failed device on EdgeLite: %s", e)

            self._metrics.record_push_failure()
            return {
                "ok": False,
                "error": f"EdgeLite driver start failed: {conflict_detail}",
                "error_type": "driver_failed",
                "suggestion": suggestion,
                "driver_config": driver_config,
                "connection_info": conn_info,
                "pip_hint": pip_hint or None,
                "private_ip_warning": is_private_ip_timeout,
                "suggested_host": get_protoforge_host() if is_private_ip_timeout else None,
            }

        # 设备已存在，尝试 GET 确认 + PUT 更新
        device_id = payload["device_id"]
        try:
            dev_resp = await self._request_with_auth(
                "get", f"/api/v1/devices/{quote(str(device_id), safe='')}"
            )
            if dev_resp.status_code == 404:
                # 设备已被服务器删除，重新 POST
                create_resp2 = await self._request_with_auth("post", "/api/v1/devices", json=payload)
                if create_resp2.status_code in (200, 201):
                    latency_ms = (time.time() - start_time) * 1000
                    self._metrics.record_push_success(latency_ms)
                    return {"ok": True, "action": "created", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}
                try:
                    err_data = create_resp2.json()
                    err_detail = err_data.get("detail", str(create_resp2.text[:200]))
                except Exception:
                    err_detail = str(create_resp2.text[:200])
                self._metrics.record_push_failure()
                return {"ok": False, "error": f"Re-create failed: HTTP {create_resp2.status_code} - {err_detail}", "error_type": "create_failed"}
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug("Network error checking device existence: %s", e)

        # PUT 更新
        update_payload = {k: v for k, v in payload.items() if k != "device_id"}
        try:
            update_resp = await self._request_with_auth(
                "put", f"/api/v1/devices/{quote(str(device_id), safe='')}", json=update_payload
            )
            if update_resp.status_code == 200:
                latency_ms = (time.time() - start_time) * 1000
                self._metrics.record_push_success(latency_ms)
                logger.info("Device %s updated on EdgeLite", payload["device_id"])
                return {"ok": True, "action": "updated", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}
            self._metrics.record_push_failure()
            return {"ok": False, "error": f"Update failed: HTTP {update_resp.status_code}", "error_type": "update_failed"}
        except httpx.ConnectError:
            self._metrics.record_push_failure()
            return {"ok": False, "error": desc("edgelite.error.push_connection"), "error_type": "connection"}
        except httpx.TimeoutException:
            self._metrics.record_push_failure()
            return {"ok": False, "error": desc("edgelite.error.push_timeout"), "error_type": "timeout"}

    # ─── 设备删除 ────────────────────────────────────────────

    async def delete_device(self, device: Any) -> dict[str, Any]:
        """从 EdgeLite 删除设备。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import _normalize_device_id, get_edgelite_config_from_device

        el_config = get_edgelite_config_from_device(device)
        if not el_config.get("url"):
            return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

        device_id = _normalize_device_id(getattr(device, "id", ""))

        try:
            resp = await self._request_with_auth(
                "delete", f"/api/v1/devices/{quote(str(device_id), safe='')}"
            )
            if resp.status_code in (200, 204, 404):
                return {"ok": True, "action": "deleted", "device_id": device_id}
            return {"ok": False, "error": f"Delete failed: HTTP {resp.status_code}", "error_type": "delete_failed"}
        except httpx.ConnectError:
            return {"ok": False, "error": desc("edgelite.error.cannot_connect"), "error_type": "connection"}
        except httpx.TimeoutException:
            return {"ok": False, "error": desc("edgelite.error.connect_timeout"), "error_type": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    # ─── 连接测试 ────────────────────────────────────────────

    async def test_connection(self, url: str = "", username: str = "", password: str = "") -> dict[str, Any]:
        """测试 EdgeLite 网关连通性。"""
        test_url = url or self._edgelite_url
        if not test_url:
            return {"ok": False, "error": desc("edgelite.error.url_empty")}
        if not test_url.startswith("http://") and not test_url.startswith("https://"):
            return {"ok": False, "error": desc("edgelite.error.url_invalid")}

        test_user = username or self._username
        test_pass = password or self._password

        client = self._http_client or httpx.AsyncClient(timeout=HTTP_TIMEOUT_DEFAULT)
        try:
            resp = await client.get(f"{test_url.rstrip('/')}/api/v1/system/status")
        except httpx.ConnectError:
            return {"ok": False, "error": desc("edgelite.error.cannot_connect")}
        except httpx.TimeoutException:
            return {"ok": False, "error": desc("edgelite.error.connect_timeout")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

        if resp.status_code == 200:
            try:
                raw = resp.json()
            except Exception:
                return {"ok": False, "error": "EdgeLite returned non-JSON response"}
            data = raw.get("data", raw)
            return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", data.get("devices", 0))}

        if resp.status_code not in (401, 403):
            return {"ok": False, "error": f"HTTP {resp.status_code}"}

        if not test_pass:
            return {"ok": False, "error": desc("edgelite.error.auth_required")}

        try:
            login_resp = await client.post(
                f"{test_url.rstrip('/')}/api/v1/auth/login",
                json={"username": test_user, "password": test_pass},
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            return {"ok": False, "error": str(e)}

        if login_resp.status_code == 200:
            from protoforge.core.edgelite import _extract_token
            token = _extract_token(login_resp)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                status_resp = await client.get(f"{test_url.rstrip('/')}/api/v1/system/status", headers=headers)
                if status_resp.status_code == 200:
                    raw = status_resp.json()
                    data = raw.get("data", raw)
                    return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", data.get("devices", 0))}
            except Exception as e:
                logger.debug("Failed to get system status after login: %s", e)
            return {"ok": False, "error": f"EdgeLite status returned HTTP {status_resp.status_code}"}

        if login_resp.status_code == 401:
            return {"ok": False, "error": desc("edgelite.error.auth_failed")}
        return {"ok": False, "error": desc("edgelite.error.login_http_failed").format(status=login_resp.status_code)}

    # ─── 数据读取 ────────────────────────────────────────────

    async def read_device_points(self, device: Any) -> dict[str, Any]:
        """从 EdgeLite 读取设备数据点。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import _normalize_device_id, get_edgelite_config_from_device

        el_config = get_edgelite_config_from_device(device)
        if not el_config.get("url"):
            return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

        device_id = _normalize_device_id(getattr(device, "id", ""))

        try:
            resp = await self._request_with_auth(
                "get", f"/api/v1/devices/{quote(str(device_id), safe='')}/points"
            )
            if resp.status_code == 200:
                raw = resp.json()
                data = raw.get("data", raw)
                return {"ok": True, "device_id": device_id, "points": data}
            if resp.status_code == 404:
                return {"ok": False, "error": desc("edgelite.error.query_device_connection"), "error_type": "not_found"}
            return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}
        except httpx.ConnectError:
            return {"ok": False, "error": desc("edgelite.error.read_points_connection"), "error_type": "connection"}
        except httpx.TimeoutException:
            return {"ok": False, "error": desc("edgelite.error.read_points_timeout"), "error_type": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    # ─── 设备状态查询 ─────────────────────────────────────────

    async def get_device_status(self, device: Any) -> dict[str, Any]:
        """查询 EdgeLite 设备状态。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import _normalize_device_id, get_edgelite_config_from_device

        el_config = get_edgelite_config_from_device(device)
        if not el_config.get("url"):
            return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

        device_id = _normalize_device_id(getattr(device, "id", ""))

        try:
            resp = await self._request_with_auth(
                "get", f"/api/v1/devices/{quote(str(device_id), safe='')}"
            )
            if resp.status_code == 200:
                raw = resp.json()
                data = raw.get("data", raw)
                return {"ok": True, "device_id": device_id, "status": data.get("status", "unknown"), "data": data}
            if resp.status_code == 404:
                return {"ok": False, "error": desc("edgelite.error.query_device_connection"), "error_type": "not_found"}
            return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}
        except httpx.ConnectError:
            return {"ok": False, "error": desc("edgelite.error.query_device_connection"), "error_type": "connection"}
        except httpx.TimeoutException:
            return {"ok": False, "error": desc("edgelite.error.query_device_timeout"), "error_type": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    # ─── 智能管线验证（带自修复）───────────────────────────────

    async def verify_pipeline(self, device: Any, auto_fix: bool = True) -> dict[str, Any]:
        """端到端管线验证，支持自动修复。

        步骤: 认证 → 注册检查 → 连接检查 → 数据采集检查
        auto_fix=True 时，自动修复可修复的问题（如设备未注册则自动推送）。
        """
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import (
            _normalize_device_id,
            get_edgelite_config_from_device,
            _is_edgelite_local,
            _build_connect_error,
            _get_protocol_status,
        )

        el_config = get_edgelite_config_from_device(device)
        if not el_config.get("url"):
            return {
                "ok": False, "skipped": True,
                "reason": "edgelite_url not configured",
                "error_type": "not_configured",
            }

        device_id = _normalize_device_id(getattr(device, "id", ""))
        result: dict[str, Any] = {"device_id": device_id, "steps": {}, "auto_fixes": []}

        # Step 1: 认证
        try:
            headers, auth_err = await self._get_auth_headers()
            if auth_err:
                result["steps"]["auth"] = {"ok": False, "error": str(auth_err)}
                result["ok"] = False
                return result
            result["steps"]["auth"] = {"ok": True}
        except Exception as e:
            result["steps"]["auth"] = {"ok": False, "error": str(e)}
            result["ok"] = False
            return result

        # Step 2: 注册检查
        try:
            dev_resp = await self._request_with_auth(
                "get", f"/api/v1/devices/{quote(str(device_id), safe='')}"
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            result["steps"]["register"] = {"ok": False, "error": str(e)}
            result["ok"] = False
            return result

        if dev_resp.status_code == 404:
            # 设备未注册
            if auto_fix:
                # 自修复：自动推送设备
                fix_result = await self.push_device(device)
                if fix_result.get("ok"):
                    result["steps"]["register"] = {"ok": True, "auto_fixed": True, "fix_detail": "Device auto-pushed to EdgeLite"}
                    result["auto_fixes"].append({"step": "register", "action": "auto_push", "result": "success"})
                    # 重新查询
                    try:
                        dev_resp = await self._request_with_auth(
                            "get", f"/api/v1/devices/{quote(str(device_id), safe='')}"
                        )
                    except Exception as e:
                        logger.debug("Failed to re-query device after auto-push: %s", e)
                else:
                    result["steps"]["register"] = {"ok": False, "auto_fix_failed": True, "error": fix_result.get("error", "Auto-push failed")}
                    result["auto_fixes"].append({"step": "register", "action": "auto_push", "result": "failed", "error": fix_result.get("error", "")})
                    result["ok"] = False
                    return result
            else:
                result["steps"]["register"] = {"ok": False, "error": "Device not registered on EdgeLite"}
                result["ok"] = False
                return result

        if dev_resp.status_code != 200:
            result["steps"]["register"] = {"ok": False, "error": f"HTTP {dev_resp.status_code}"}
            result["ok"] = False
            return result

        try:
            dev_data_raw = dev_resp.json()
        except Exception:
            result["steps"]["register"] = {"ok": False, "error": "Invalid JSON response"}
            result["ok"] = False
            return result

        dev_data = dev_data_raw.get("data", dev_data_raw)
        el_status = dev_data.get("status", "unknown")
        result["steps"]["register"] = {"ok": True, "status": el_status}

        # Step 3: 连接检查
        if el_status == "offline":
            protocol = getattr(device, "protocol", "") or ""
            protoforge_running = _get_protocol_status(protocol) == "running"
            same_server = _is_edgelite_local(el_config)

            if auto_fix and not protoforge_running:
                # 自修复：尝试启动协议服务器
                try:
                    from protoforge.main import get_engine
                    engine = get_engine()
                    if engine:
                        # FIX: start_protocol 需要 config 参数，从引擎配置中获取协议端口
                        protocol_config = engine.config.dict() if hasattr(engine, 'config') and hasattr(engine.config, 'dict') else {}
                        await engine.start_protocol(protocol, protocol_config)
                        protoforge_running = True
                        result["auto_fixes"].append({"step": "connect", "action": "start_protocol", "result": "success"})
                except Exception as e:
                    result["auto_fixes"].append({"step": "connect", "action": "start_protocol", "result": "failed", "error": str(e)})

            driver_config = dev_data.get("config", dev_data.get("driver_config", {}))
            if isinstance(driver_config, str):
                try:
                    import json
                    driver_config = json.loads(driver_config)
                except Exception:
                    driver_config = {}

            connect_error = _build_connect_error(
                driver_config if isinstance(driver_config, dict) else {},
                protocol, protoforge_running, same_server
            )
            result["steps"]["connect"] = connect_error
            result["ok"] = False
            return result

        result["steps"]["connect"] = {"ok": True, "status": el_status}

        # Step 4: 数据采集检查
        try:
            points_resp = await self._request_with_auth(
                "get", f"/api/v1/devices/{quote(str(device_id), safe='')}/points"
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            result["steps"]["collect"] = {"ok": False, "error": str(e)}
            result["ok"] = False
            return result

        if points_resp.status_code == 200:
            try:
                raw_points = points_resp.json()
            except Exception:
                result["steps"]["collect"] = {"ok": False, "error": "Invalid JSON"}
                result["ok"] = False
                return result

            points_data = raw_points.get("data", raw_points)
            if isinstance(points_data, list):
                has_data = len(points_data) > 0
                points_dict = {}
                for item in points_data:
                    if isinstance(item, dict):
                        key = item.get("name") or item.get("point_name") or item.get("id", "")
                        points_dict[key] = item.get("value")
                if points_dict:
                    points_data = points_dict
            elif isinstance(points_data, dict):
                has_data = any(v is not None for v in points_data.values())
            else:
                has_data = False

            result["steps"]["collect"] = {"ok": True, "data": points_data, "has_real_data": has_data}
        else:
            result["steps"]["collect"] = {"ok": False, "error": f"HTTP {points_resp.status_code}"}

        all_ok = all(s.get("ok", False) for s in result["steps"].values())
        collect_step = result["steps"].get("collect", {})
        if all_ok and not collect_step.get("has_real_data"):
            all_ok = False
        result["ok"] = all_ok
        return result

    # ─── 批量推送 ────────────────────────────────────────────

    async def batch_push(self, devices: list[Any], protoforge_host: str = "", concurrency: int = 10) -> dict[str, Any]:
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        semaphore = asyncio.Semaphore(concurrency)
        results = {"total": len(devices), "success": 0, "failure": 0, "details": []}

        async def _push_one(dev: Any) -> dict[str, Any]:
            async with semaphore:
                return await self.push_device(dev, protoforge_host)

        tasks = [_push_one(d) for d in devices]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in task_results:
            if isinstance(r, Exception):
                results["failure"] += 1
                results["details"].append({"ok": False, "error": str(r)})
            elif r.get("ok"):
                results["success"] += 1
                results["details"].append(r)
            else:
                results["failure"] += 1
                results["details"].append(r)

        results["ok"] = results["failure"] == 0
        return results

    # ─── 告警联动 ────────────────────────────────────────────

    def add_alarm_reaction_rule(self, rule: AlarmReactionRule) -> None:
        self._alarm_reaction_rules.append(rule)

    def remove_alarm_reaction_rule(self, rule_id: str) -> None:
        self._alarm_reaction_rules = [r for r in self._alarm_reaction_rules if r.rule_id != rule_id]

    def get_alarm_reaction_rules(self) -> list[AlarmReactionRule]:
        return list(self._alarm_reaction_rules)

    # ─── 数据回传处理 ────────────────────────────────────────

    async def handle_backhaul_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "device_status_changed":
            device_id = payload.get("device_id", "")
            new_status = payload.get("new_status", "")
            self._device_status_cache.set(device_id, new_status)
            self._metrics.record_sync_event()
            logger.info("Device %s status changed to %s (from EdgeLite)", device_id, new_status)

        elif msg_type == "device_fault":
            device_id = payload.get("device_id", "")
            logger.warning("Device %s fault reported from EdgeLite: %s", device_id, payload)

        elif msg_type == "point_data":
            device_id = payload.get("device_id", "")
            self._backhaul_data.setdefault(device_id, []).append({
                "point_name": payload.get("point_name", ""),
                "value": payload.get("value", 0.0),
                "quality": payload.get("quality", "good"),
                "timestamp": message.get("timestamp", time.time()),
            })
            if len(self._backhaul_data[device_id]) > 1000:
                self._backhaul_data[device_id] = self._backhaul_data[device_id][-1000:]
            self._metrics.record_data_backhaul()

        elif msg_type in ("alarm_fired", "alarm_recovered"):
            await self._handle_alarm_from_edgelite(payload, msg_type)
            self._metrics.record_alarm_forward()

    async def _handle_alarm_from_edgelite(self, payload: dict[str, Any], msg_type: str) -> None:
        source_device_id = payload.get("device_id", "")
        severity = payload.get("severity", "")
        if msg_type == "alarm_fired":
            for rule in self._alarm_reaction_rules:
                if rule.matches(source_device_id, severity):
                    await self._execute_alarm_reaction(rule, payload)

    async def _execute_alarm_reaction(self, rule: AlarmReactionRule, alarm_payload: dict[str, Any]) -> None:
        target_id = rule.target_device_id or rule.source_device_id
        logger.info("Executing alarm reaction: rule=%s action=%s target=%s", rule.rule_id, rule.action, target_id)

        if rule.action == "stop_device":
            try:
                from protoforge.main import get_engine
                engine = get_engine()
                if engine:
                    await engine.stop_device(target_id)
            except Exception as e:
                logger.error("Alarm reaction stop_device failed: %s", e)

        elif rule.action == "start_device":
            try:
                from protoforge.main import get_engine
                engine = get_engine()
                if engine:
                    await engine.start_device(target_id)
            except Exception as e:
                logger.error("Alarm reaction start_device failed: %s", e)

        elif rule.action == "log_only":
            logger.warning("Alarm logged: rule=%s severity=%s source=%s", rule.rule_id, rule.alarm_severity, rule.source_device_id)

    def get_backhaul_data(self, device_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if device_id:
            data = self._backhaul_data.get(device_id, [])
            return [{**entry, "device_id": device_id} for entry in data[-limit:]]
        all_data = []
        for dev_id, entries in self._backhaul_data.items():
            for entry in entries[-limit:]:
                all_data.append({**entry, "device_id": dev_id})
        all_data.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return all_data[:limit]

    # ─── HTTP Webhook 数据推送 ────────────────────────────────

    def _start_http_push(self, device_id: str, instance: Any) -> None:
        """为被动协议（HTTP/Webhook）设备启动模拟数据推送任务。"""
        if device_id in self._http_push_tasks:
            return  # 已有推送任务
        task = asyncio.create_task(
            self._http_push_loop(device_id, instance),
            name=f"http-push-{device_id}",
        )
        self._http_push_tasks[device_id] = task
        logger.info("Started HTTP push loop for device %s", device_id)

    def _stop_http_push(self, device_id: str) -> None:
        """停止设备的 HTTP 推送任务。"""
        task = self._http_push_tasks.pop(device_id, None)
        if task and not task.done():
            task.cancel()
            logger.info("Stopped HTTP push loop for device %s", device_id)

    async def _http_push_loop(self, device_id: str, instance: Any) -> None:
        """定期将 ProtoForge 模拟数据推送到 EdgeLite 的 webhook 端点。"""
        import datetime
        try:
            while self._running:
                try:
                    # 从设备实例获取当前模拟数据
                    points_data = {}

                    # 尝试从 HttpSimulatorServer 获取数据
                    if hasattr(instance, "get_all_point_values"):
                        all_values = instance.get_all_point_values()
                        # get_all_point_values 可能返回 {"device_id": {"point_name": value}}
                        # 或直接 {"point_name": value}（单个设备）
                        if device_id in all_values:
                            # 嵌套格式
                            points_data = all_values[device_id]
                        elif any(isinstance(v, dict) for v in all_values.values()):
                            # 嵌套格式，但device_id作为键
                            points_data = all_values.get(device_id, {})
                        else:
                            # 扁平格式
                            points_data = all_values
                    elif hasattr(instance, "read_points"):
                        # read_points 返回 list[PointValue]
                        pts = instance.read_points(device_id)
                        for pv in pts:
                            if pv.name and pv.value is not None:
                                points_data[pv.name] = pv.value
                    elif hasattr(instance, "points"):
                        for pt in instance.points:
                            pt_name = getattr(pt, "name", "")
                            pt_value = getattr(pt, "current_value", None)
                            if pt_value is None:
                                pt_value = getattr(pt, "value", None)
                            if pt_name and pt_value is not None:
                                points_data[pt_name] = pt_value

                    if not points_data:
                        await asyncio.sleep(self._http_push_interval)
                        continue

                    # FIXED: 将数据转换为 EdgeLite 期望的格式
                    # EdgeLite 期望: {"data": {"point_name": {"value": xxx, "quality": "good", "timestamp": "..."}}}
                    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    push_payload = {
                        "data": {
                            pt_name: {
                                "value": pt_value,
                                "quality": "good",
                                "timestamp": now
                            }
                            for pt_name, pt_value in points_data.items()
                        }
                    }

                    # 推送到 EdgeLite 的 webhook 端点
                    push_url = f"{self._edgelite_url.rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}/push"
                    headers = {}
                    if self._auth:
                        await self._auth.ensure_token()
                        if self._auth.token:
                            headers["Authorization"] = f"Bearer {self._auth.token}"

                    resp = await self._http_client.post(
                        push_url,
                        json=push_payload,
                        headers=headers,
                        timeout=HTTP_TIMEOUT_SHORT,
                    )
                    if resp.status_code not in (200, 201, 204):
                        # 记录错误详情以便诊断 400 问题
                        logger.warning(
                            "HTTP push to EdgeLite for %s returned %d: %s",
                            device_id, resp.status_code, resp.text[:500]
                        )
                    else:
                        logger.debug("HTTP push to EdgeLite for %s succeeded", device_id)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("HTTP push loop error for %s: %s", device_id, e)

                await asyncio.sleep(self._http_push_interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._http_push_tasks.pop(device_id, None)

    # ─── 事件处理（自动同步）──────────────────────────────────

    async def _on_device_created(self, event: DeviceCreatedEvent) -> None:
        """设备创建事件 — 自动推送到 EdgeLite。"""
        if not self._enabled:
            return
        proto_config = event.protocol_config or {}
        el_url = proto_config.get("edgelite_url", "")
        el_enabled = proto_config.get("edgelite_enabled", False)
        if not el_url and not el_enabled:
            return

        logger.info("IntegrationManager: auto-pushing DeviceCreatedEvent for %s", event.device_id)
        try:
            from protoforge.main import get_engine
            engine = get_engine()
            if engine:
                instance = engine.get_device_instance(event.device_id)
                if instance:
                    protoforge_host = proto_config.get("protoforge_host", "")
                    result = await self.push_device(instance, protoforge_host)
                    if result.get("ok"):
                        logger.info("Auto-pushed device %s to EdgeLite", event.device_id)
                    else:
                        logger.debug("Auto-push for %s: %s", event.device_id, result.get("reason", result.get("error", "")))
        except Exception as e:
            logger.warning("IntegrationManager auto-push failed for %s: %s", event.device_id, e)

    async def _on_device_started(self, event: DeviceStartedEvent) -> None:
        """设备启动事件 — 通知 EdgeLite 开始采集。"""
        msg = {"type": "device_control", "payload": {"device_id": event.device_id, "action": "start_collect"}}
        if self._ws_channel and self._ws_channel.is_connected:
            try:
                await self._ws_channel.send(msg)
                self._metrics.record_sync_event()
            except Exception:
                await self._enqueue_retry(msg)
        else:
            await self._enqueue_retry(msg)

    async def _on_device_stopped(self, event: DeviceStoppedEvent) -> None:
        """设备停止事件 — 通知 EdgeLite 停止采集。"""
        msg = {"type": "device_control", "payload": {"device_id": event.device_id, "action": "stop_collect"}}
        if self._ws_channel and self._ws_channel.is_connected:
            try:
                await self._ws_channel.send(msg)
                self._metrics.record_sync_event()
            except Exception:
                await self._enqueue_retry(msg)
        else:
            await self._enqueue_retry(msg)

    async def _on_device_removed(self, event: DeviceRemovedEvent) -> None:
        """设备删除事件 — 从 EdgeLite 删除。"""
        self._backhaul_data.pop(event.device_id, None)
        self._stop_http_push(event.device_id)  # 停止 HTTP 推送任务
        from protoforge.core.edgelite import _normalize_device_id
        # FIX: 统一规范化 device_id，REST 和 WS 路径使用相同的 ID
        device_id = _normalize_device_id(event.device_id)

        # 通过 REST API 删除（比 WebSocket 更可靠）
        try:
            resp = await self._request_with_auth("delete", f"/api/v1/devices/{quote(str(device_id), safe='')}")
            # FIX: 检查响应状态码，只有真正成功才记录指标
            if resp.status_code in (200, 204, 404):
                self._metrics.record_sync_event()
            else:
                logger.warning("EdgeLite delete device %s returned HTTP %d", device_id, resp.status_code)
        except Exception:
            # 回退到 WebSocket（使用规范化后的 device_id）
            msg = {"type": "delete_device", "payload": {"device_id": device_id}}
            await self._enqueue_retry(msg)

    async def _on_protocol_status(self, event: Any) -> None:
        """协议状态变更事件 — 端口变更时自动更新 EdgeLite 中的设备配置。

        解决关键问题：ProtoForge 协议端口因冲突自动切换后，EdgeLite 中的
        设备仍用旧端口配置，导致连接失败。此处理器在协议重启后自动用
        新端口重新推送所有受影响的设备。
        """
        protocol_name = getattr(event, "protocol_name", "")
        new_status = getattr(event, "new_status", "")
        old_status = getattr(event, "old_status", "")

        if new_status != "running":
            return  # 只在协议启动时处理

        logger.info("Protocol %s status changed to running, checking affected devices on EdgeLite", protocol_name)

        # 查找所有使用此协议的设备
        try:
            from protoforge.main import get_engine
            engine = get_engine()
        except RuntimeError:
            return

        affected_devices = []
        # FIX: 使用 get_all_device_instances() 获取字典副本，避免迭代时字典被修改
        for dev_id, instance in engine.get_all_device_instances().items():
            if instance.protocol == protocol_name:
                affected_devices.append(instance)

        if not affected_devices:
            return

        # 获取当前实际端口
        actual_port = engine.get_protocol_running_port(protocol_name)

        # 重新推送受影响的设备（使用新端口配置）
        for instance in affected_devices:
            try:
                protoforge_host = getattr(instance.config, "protocol_config", {}) or {}
                host = protoforge_host.get("protoforge_host", "")
                result = await self.push_device(instance, protoforge_host=host)
                if result.get("ok"):
                    logger.info(
                        "Auto-updated device %s on EdgeLite after protocol %s restart (port=%s)",
                        instance.id, protocol_name, actual_port,
                    )
                else:
                    logger.warning(
                        "Failed to auto-update device %s on EdgeLite after protocol %s restart: %s",
                        instance.id, protocol_name, result.get("error", "unknown"),
                    )
            except Exception as e:
                logger.warning("Error updating device %s after protocol restart: %s", instance.id, e)

        self._metrics.record_sync_event()

    # ─── 重试队列 ────────────────────────────────────────────

    async def _enqueue_retry(self, message: dict[str, Any]) -> None:
        retry_count = message.get("_retry_count", 0) + 1
        if retry_count > 50:
            logger.warning("Dropping message after %d retries: type=%s", retry_count, message.get("type"))
            return
        message["_retry_count"] = retry_count
        try:
            self._retry_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Retry queue full, dropping message: type=%s", message.get("type"))

    async def _retry_queue_consumer(self) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(self._retry_queue.get(), timeout=5.0)
                try:
                    if self._ws_channel and self._ws_channel.is_connected:
                        result = await self._ws_channel.send(message)
                        if result and not result.get("ok"):
                            await self._enqueue_retry(message)
                    else:
                        await self._enqueue_retry(message)
                except Exception:
                    await self._enqueue_retry(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Retry queue consumer error: %s", e)

    async def _flush_retry_queue(self) -> None:
        if self._retry_queue.empty():
            return
        items = []
        while not self._retry_queue.empty():
            try:
                items.append(self._retry_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if items:
            logger.info("Flushing %d queued messages after reconnection", len(items))
            for msg in items:
                try:
                    if self._ws_channel and self._ws_channel.is_connected:
                        result = await self._ws_channel.send(msg)
                        if result and not result.get("ok"):
                            await self._enqueue_retry(msg)
                except Exception:
                    await self._enqueue_retry(msg)

    # ─── 定期状态同步 ────────────────────────────────────────

    async def _periodic_state_sync(self) -> None:
        """定期同步 EdgeLite 设备状态到本地缓存。"""
        while self._running:
            try:
                await asyncio.sleep(self._sync_interval)
                if not self._running or not self._http_client:
                    break
                # 查询 EdgeLite 所有设备状态
                try:
                    resp = await self._request_with_auth("get", "/api/v1/devices", params={"limit": 100})
                    if resp.status_code == 200:
                        raw = resp.json()
                        devices = raw.get("data", raw.get("devices", []))
                        if isinstance(devices, list):
                            for dev in devices:
                                if isinstance(dev, dict):
                                    dev_id = dev.get("device_id", "")
                                    status = dev.get("status", "unknown")
                                    if dev_id:
                                        self._device_status_cache.set(dev_id, status)
                            logger.debug("Synced %d device statuses from EdgeLite", len(devices))
                except Exception as e:
                    logger.debug("Periodic state sync failed: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Periodic state sync error: %s", e)

    async def _ws_reconnect_loop(self) -> None:
        """WebSocket 断线自动重连循环。

        检测 WebSocket 连接断开后，定期尝试重连。
        重连成功后自动刷新重试队列中的消息。
        """
        while self._running:
            try:
                await asyncio.sleep(self._ws_reconnect_interval)
                if not self._running:
                    break

                # 检查 WebSocket 是否需要重连
                if self._ws_channel and self._ws_channel.is_connected:
                    continue  # 连接正常，无需重连

                # 尝试重连
                logger.info("WebSocket disconnected, attempting reconnect...")
                try:
                    # 先关闭旧连接
                    if self._ws_channel:
                        try:
                            await self._ws_channel.close()
                        except Exception as e:
                            logger.debug("Failed to close old WebSocket channel: %s", e)
                        self._ws_channel = None

                    await self._connect_websocket()
                    logger.info("WebSocket reconnected successfully")
                    # 重连成功后刷新重试队列
                    await self._flush_retry_queue()
                except Exception as e:
                    logger.debug("WebSocket reconnect failed: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("WebSocket reconnect loop error: %s", e)

    # ─── 状态回调 ────────────────────────────────────────────

    def _on_state_change(self, old_state: ConnectionState, new_state: ConnectionState) -> None:
        if new_state == ConnectionState.CONNECTED:
            self._metrics.set_connected()
        elif new_state == ConnectionState.DISCONNECTED:
            self._metrics.set_disconnected()

    # ─── 公共访问器 ──────────────────────────────────────────

    def is_connected(self) -> bool:
        return self._state.state == ConnectionState.CONNECTED

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "edgelite_url": self._edgelite_url,
            "connection_state": self._state.state.value,
            "metrics": self._metrics.to_dict(),
        }

    def get_metrics(self) -> dict[str, Any]:
        return self._metrics.to_dict()

    def get_protocol_map(self) -> dict[str, str]:
        return self._protocol_mapper.get_map()

    def map_protocol(self, protoforge_protocol: str):
        """映射 ProtoForge 协议到 EdgeLite 协议，返回 ProtocolMappingResult。"""
        return self._protocol_mapper.map(protoforge_protocol)

    def get_supported_source_protocols(self) -> list[str]:
        return self._protocol_mapper.get_supported_source_protocols()

    def get_device_status_cache(self) -> dict[str, str]:
        return {k: v for k, (v, _) in self._device_status_cache._cache.items()}

    async def send_device_control(self, device_id: str, action: str) -> dict[str, Any]:
        """通过 WebSocket 向 EdgeLite 发送设备控制命令。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        msg = {"type": "device_control", "payload": {"device_id": device_id, "action": action}}
        if self._ws_channel and self._ws_channel.is_connected:
            try:
                await self._ws_channel.send(msg)
                self._metrics.record_sync_event()
                return {"ok": True, "device_id": device_id, "action": action}
            except Exception as e:
                await self._enqueue_retry(msg)
                return {"ok": False, "error": str(e), "error_type": "ws_send_failed"}

        # 回退到 REST API
        try:
            from protoforge.core.edgelite import _normalize_device_id
            norm_id = _normalize_device_id(device_id)
            resp = await self._request_with_auth(
                "post", f"/api/v1/devices/{quote(str(norm_id), safe='')}/control",
                json={"action": action},
            )
            if resp.status_code in (200, 204):
                return {"ok": True, "device_id": device_id, "action": action}
            return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}
        except Exception as e:
            await self._enqueue_retry(msg)
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    async def send_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """通过 WebSocket 向 EdgeLite 发送通用消息。"""
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        if self._ws_channel and self._ws_channel.is_connected:
            try:
                await self._ws_channel.send(message)
                self._metrics.record_sync_event()
                return {"ok": True}
            except Exception as e:
                await self._enqueue_retry(message)
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": "No WebSocket connection available", "error_type": "no_connection"}
