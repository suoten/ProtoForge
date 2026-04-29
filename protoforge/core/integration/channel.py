import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ChannelBase(ABC):
    def __init__(self):
        self._message_handlers: dict[str, list[Callable]] = {}

    def on_message(self, msg_type: str, handler: Callable) -> None:
        self._message_handlers.setdefault(msg_type, []).append(handler)

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @property
    def channel_type(self) -> str:
        return "base"

    async def _dispatch_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type", "")
        for handler in self._message_handlers.get(msg_type, []):
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Message handler error for %s: %s", msg_type, e)


class HttpChannel(ChannelBase):
    def __init__(self, base_url: str, auth: Any = None):
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._connected = False
        self._client: Any = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def channel_type(self) -> str:
        return "http"

    async def connect(self) -> None:
        import httpx
        self._client = httpx.AsyncClient(timeout=10.0, base_url=self._base_url)
        if self._auth:
            await self._auth.ensure_token()
        self._connected = True
        logger.info("HTTP channel connected to %s", self._base_url)

    async def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not self._client or not self._connected:
            raise ConnectionError("HTTP channel not connected")

        headers = {}
        if self._auth and self._auth.token:
            headers["Authorization"] = f"Bearer {self._auth.token}"

        msg_type = message.get("type", "")
        payload = message.get("payload", message)

        try:
            if msg_type in ("push_device", "batch_push"):
                resp = await self._client.post("/api/v1/devices", json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    return {"ok": True, "data": resp.json()}
                if resp.status_code == 409:
                    device_id = payload.get("device_id", "")
                    update_payload = {k: v for k, v in payload.items() if k != "device_id"}
                    resp = await self._client.put(f"/api/v1/devices/{device_id}", json=update_payload, headers=headers)
                    if resp.status_code == 200:
                        return {"ok": True, "updated": True, "data": resp.json()}
                if resp.status_code == 401 and self._auth:
                    await self._auth.refresh_token()
                    headers["Authorization"] = f"Bearer {self._auth.token}"
                    resp = await self._client.post("/api/v1/devices", json=payload, headers=headers)
                    if resp.status_code in (200, 201):
                        return {"ok": True, "data": resp.json()}
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            elif msg_type == "delete_device":
                device_id = payload.get("device_id", "")
                resp = await self._client.delete(f"/api/v1/devices/{device_id}", headers=headers)
                return {"ok": resp.status_code in (200, 204)}

            elif msg_type == "device_control":
                device_id = payload.get("device_id", "")
                action = payload.get("action", "")
                if action == "start_collect":
                    resp = await self._client.post(f"/api/v1/devices/{device_id}/start", headers=headers)
                elif action == "stop_collect":
                    resp = await self._client.post(f"/api/v1/devices/{device_id}/stop", headers=headers)
                else:
                    return {"ok": False, "error": f"Unknown action: {action}"}
                return {"ok": resp.status_code == 200}

            else:
                resp = await self._client.post("/api/v1/integration/message", json=message, headers=headers)
                return {"ok": resp.status_code == 200, "data": resp.json() if resp.status_code == 200 else None}

        except Exception as e:
            self._connected = False
            raise

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False


class ChannelFactory:
    _registry: dict[str, type[ChannelBase]] = {}

    @classmethod
    def register(cls, channel_type: str, channel_class: type[ChannelBase]) -> None:
        cls._registry[channel_type] = channel_class

    @classmethod
    def create(cls, channel_type: str, **kwargs: Any) -> ChannelBase:
        if channel_type not in cls._registry:
            raise ValueError(f"Unknown channel type: {channel_type}, available: {list(cls._registry.keys())}")
        return cls._registry[channel_type](**kwargs)

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())


ChannelFactory.register("http", HttpChannel)


class WebSocketChannel(ChannelBase):
    def __init__(
        self,
        url: str,
        auth: Any = None,
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: int = 3,
    ):
        super().__init__()
        self._url = url
        self._auth = auth
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._connected = False
        self._ws: Any = None
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._missed_heartbeats = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def channel_type(self) -> str:
        return "websocket"

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.warning("websockets library not installed, WebSocket channel unavailable")
            raise

        if self._auth:
            await self._auth.ensure_token()
            token = self._auth.token
            separator = "&" if "?" in self._url else "?"
            connect_url = f"{self._url}{separator}token={token}"
        else:
            connect_url = self._url

        self._ws = await websockets.connect(connect_url, ping_interval=None, close_timeout=5.0)
        self._connected = True
        self._missed_heartbeats = 0

        self._receive_task = asyncio.create_task(self._receive_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("WebSocket channel connected to %s", self._url)

    async def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not self._ws or not self._connected:
            raise ConnectionError("WebSocket channel not connected")

        data = json.dumps(message)
        await self._ws.send(data)
        return None

    async def close(self) -> None:
        self._connected = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("WebSocket close error: %s", e)
            self._ws = None
        logger.info("WebSocket channel closed")

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw) if isinstance(raw, str) else raw
                    msg_type = message.get("type", "")
                    if msg_type == "heartbeat_ack":
                        self._missed_heartbeats = 0
                    await self._dispatch_message(message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received on WebSocket")
                except Exception as e:
                    logger.error("WebSocket receive error: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("WebSocket connection lost: %s", e)
            self._connected = False

    async def _heartbeat_loop(self) -> None:
        try:
            while self._connected:
                await asyncio.sleep(self._heartbeat_interval)
                if not self._connected:
                    break
                try:
                    await self.send({
                        "type": "heartbeat",
                        "timestamp": time.time(),
                    })
                except Exception as e:
                    logger.warning("Heartbeat send failed: %s", e)
                    self._missed_heartbeats += 1
                    if self._missed_heartbeats >= self._heartbeat_timeout:
                        await self._handle_timeout()
                    continue
                if self._missed_heartbeats > 0:
                    self._missed_heartbeats = 0
        except asyncio.CancelledError:
            pass

    async def _handle_timeout(self) -> None:
        logger.warning(
            "WebSocket heartbeat timeout after %d missed heartbeats, disconnecting",
            self._heartbeat_timeout,
        )
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("WebSocket close error on timeout: %s", e)
            self._ws = None


ChannelFactory.register("websocket", WebSocketChannel)


class ChannelManager:
    def __init__(self, primary: ChannelBase, fallback: ChannelBase | None = None):
        self._primary = primary
        self._fallback = fallback
        self._active: ChannelBase = primary

    @property
    def active_channel(self) -> ChannelBase:
        return self._active

    async def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if self._primary.is_connected:
            try:
                return await self._primary.send(message)
            except Exception as e:
                logger.warning("Primary channel send failed: %s, trying fallback", e)
                if self._fallback:
                    if not self._fallback.is_connected:
                        try:
                            await self._fallback.connect()
                        except Exception as e:
                            logger.debug("Fallback connect error: %s", e)
                    if self._fallback.is_connected:
                        self._active = self._fallback
                        return await self._fallback.send(message)
                raise
        if self._fallback and self._fallback.is_connected:
            self._active = self._fallback
            return await self._fallback.send(message)
        raise ConnectionError("No channel available")

    async def close(self) -> None:
        await self._primary.close()
        if self._fallback:
            await self._fallback.close()
