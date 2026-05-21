import asyncio
import json
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.core.messages import msg, desc

logger = logging.getLogger(__name__)


class HttpDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        super().__init__(points)

    def get_all_values(self) -> dict[str, Any]:
        return {name: self.get_value(name) for name in self._values}


class HttpSimulatorServer(ProtocolServer):
    protocol_name = "http"
    protocol_display_name = "HTTP REST"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, HttpDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_prefixes: dict[str, str] = {}
        self._host = "0.0.0.0"
        self._port = 8080
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 8080)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("HTTP REST server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            msg("http", "service_started", host=self._host, port=self._port),
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start HTTP server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("HTTP task cancelled")
        except Exception as e:
            logger.warning("HTTP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("HTTP REST server stopped")
            self._log_debug("system", "server_stop", msg("http", "service_stopped"))

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("HTTP server task cancelled")
        except Exception as e:
            logger.error("HTTP server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        try:
            while self._server_running:
                try:
                    request_line = await asyncio.wait_for(reader.readline(), timeout=30.0)
                except asyncio.TimeoutError:
                    break
                if not request_line:
                    break
                request_str = request_line.decode("utf-8", errors="replace").strip()
                if not request_str:
                    continue
                parts = request_str.split(" ")
                if len(parts) < 2:
                    break
                method = parts[0].upper()
                path = parts[1]

                headers = {}
                content_length = 0
                while True:
                    line = await reader.readline()
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, val = line_str.split(":", 1)
                        headers[key.strip().lower()] = val.strip()
                try:
                    content_length = int(headers.get("content-length", "0"))
                except (ValueError, TypeError):
                    content_length = 0
                body = b""
                if content_length > 0:
                    body = await reader.readexactly(content_length)

                response = self._route(method, path, body)
                writer.write(response)
                await writer.drain()

                if headers.get("connection", "").lower() == "close":
                    break
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("HTTP writer close error: %s", e)

    def _route(self, method: str, path: str, body: bytes) -> bytes:
        if method == "OPTIONS":
            return self._cors_preflight_response()
        for device_id, prefix in self._device_prefixes.items():
            if path.startswith(prefix):
                rel_path = path[len(prefix):] or "/"
                behavior = self._behaviors.get(device_id)
                config = self._device_configs.get(device_id)
                if behavior and config:
                    return self._handle_device(method, rel_path, body, device_id, behavior, config)

        if path == "/" or path == "/health":
            return self._json_response(200, {"status": "ok", "protocol": "http", "devices": len(self._behaviors)})

        if path == "/devices":
            devices = []
            for did, config in self._device_configs.items():
                devices.append({"id": did, "name": config.name, "prefix": self._device_prefixes.get(did, "/api")})
            return self._json_response(200, {"devices": devices})

        return self._json_response(404, {"error": "Not Found"})

    def _handle_device(self, method: str, path: str, body: bytes,
                        device_id: str, behavior: HttpDeviceBehavior,
                        config: DeviceConfig) -> bytes:
        if path == "/" or path == "/points":
            if method == "GET":
                values = behavior.get_all_values()
                points = []
                for p in config.points:
                    points.append({
                        "name": p.name, "value": values.get(p.name, 0),
                        "unit": p.unit, "data_type": p.data_type.value,
                        "access": p.access, "timestamp": time.time(),
                    })
                return self._json_response(200, {"device_id": device_id, "points": points})
            elif method == "POST" and body:
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    return self._json_response(400, {"error": "Invalid JSON body"})
                for name, value in data.items():
                    behavior.set_value(name, value)
                self._log_debug("recv", "http_write",
                                msg("http", "device_written", detail=device_id),
                                device_id=device_id,
                                detail={"data": data})
                return self._json_response(200, {"ok": True})

        point_name = path.lstrip("/")
        for p in config.points:
            if p.name == point_name:
                if method == "GET":
                    return self._json_response(200, {
                        "name": p.name, "value": behavior.get_value(p.name),
                        "unit": p.unit, "data_type": p.data_type.value,
                        "access": p.access, "timestamp": time.time(),
                    })
                elif method in ("PUT", "POST") and body:
                    try:
                        data = json.loads(body)
                    except (json.JSONDecodeError, TypeError):
                        return self._json_response(400, {"error": "Invalid JSON body"})
                    value = data.get("value", data.get(p.name))
                    if value is not None:
                        behavior.set_value(p.name, value)
                        self._log_debug("recv", "http_write",
                                        msg("http", "point_written", detail=f"{p.name}={value}"),
                                        device_id=device_id)
                    return self._json_response(200, {"ok": True, "name": p.name, "value": behavior.get_value(p.name)})
                elif method == "DELETE":
                    behavior.set_value(p.name, 0)
                    return self._json_response(200, {"ok": True})

        return self._json_response(404, {"error": f"Point not found: {point_name}"})

    def _cors_preflight_response(self) -> bytes:
        header = (
            "HTTP/1.1 204 No Content\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH\r\n"
            "Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n"
            "Access-Control-Max-Age: 86400\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        return header.encode("utf-8")

    def _json_response(self, status: int, body: dict) -> bytes:
        status_text = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}.get(status, "OK")
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        header = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: keep-alive\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH\r\n"
            f"Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n"
            f"\r\n"
        )
        return header.encode("utf-8") + body_bytes

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = HttpDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        await self._update_default_device_async(device_config.id)

        proto_config = device_config.protocol_config or {}
        api_prefix = proto_config.get("api_prefix", f"/api/{device_config.id}")
        self._device_prefixes[device_config.id] = api_prefix

        logger.info("HTTP device created: %s (api_prefix=%s)", device_config.id, api_prefix)
        self._log_debug("system", "device_create",
                        msg("http", "device_created", name=device_config.name),
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_prefixes.pop(device_id, None)
        await self._clear_default_device_async(device_id)
        logger.info("HTTP device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        msg("http", "device_removed", id=device_id),
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []
        now = time.time()
        result = []
        for point in config.points:
            value = behavior.get_value(point.name)
            result.append(PointValue(name=point.name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address")},
                "port": {"type": "integer", "default": 8080, "description": desc("listen_port")},
                "api_prefix": {"type": "string", "default": "/api", "description": desc("http_api_prefix")},
            },
        }
