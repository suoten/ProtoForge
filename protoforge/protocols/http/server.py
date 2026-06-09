import asyncio
import json
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import StandardDeviceBehavior, ProtocolServer, ProtocolStatus  # FIXED: W11 - 改继承StandardDeviceBehavior，与其他15个协议一致
from protoforge.core.messages import msg, desc

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 30  # FIXED-P0: 定义缺失的读取超时常量，否则_handle_connection中NameError导致服务器完全不可用


class HttpDeviceBehavior(StandardDeviceBehavior):  # FIXED: W11 - 改继承StandardDeviceBehavior，与其他15个协议一致
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
        self._response_templates: dict[str, str] = {}  # FIXED-P1: 每设备的自定义响应模板
        self._host = "0.0.0.0"
        self._port = 8080
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._cors_origin: str = "*"  # FIXED: P4 - W23 CORS origin 从配置获取，默认 * 仅用于开发

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 8080)
        self._validate_port(self._port)
        # FIXED: P4 - W23 CORS origin 从配置获取，未配置时默认 * 仅用于开发环境
        self._cors_origin = config.get("cors_origin", "*")
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
                    request_line = await asyncio.wait_for(reader.readline(), timeout=_READ_TIMEOUT)
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
                http_version = parts[2] if len(parts) >= 3 else "HTTP/1.0"
                # FIXED-P1: 分离path和query string，提取查询参数
                query_params: dict[str, str] = {}
                if "?" in path:
                    path, query_string = path.split("?", 1)
                    for pair in query_string.split("&"):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            query_params[k] = v

                headers = {}
                content_length = 0
                while True:
                    try:
                        line = await asyncio.wait_for(reader.readline(), timeout=_READ_TIMEOUT)
                    except asyncio.TimeoutError:
                        break
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
                if content_length > 10 * 1024 * 1024:  # FIXED-P0: 限制请求体大小为10MB，防止OOM攻击
                    writer.write(self._json_response(413, {"error": "Payload too large"}))
                    await writer.drain()
                    break
                body = b""
                if content_length > 0:
                    try:
                        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=_READ_TIMEOUT)
                    except asyncio.TimeoutError:
                        break

                response = self._route(method, path, body, query_params, http_version)  # FIXED-P1: 传递查询参数和HTTP版本
                writer.write(response)
                await writer.drain()

                # HTTP/1.1默认keep-alive，HTTP/1.0默认close；Connection头可覆盖默认行为
                connection_header = headers.get("connection", "").lower()
                keep_alive = (http_version == "HTTP/1.1" and connection_header != "close") or \
                             (http_version != "HTTP/1.1" and connection_header == "keep-alive")
                if not keep_alive:
                    break
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.CancelledError, asyncio.TimeoutError, BrokenPipeError, ConnectionAbortedError) as e:
            logger.debug("Connection handler error: %s", e)  # FIXED: 添加日志记录，避免异常被静默吞掉
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("HTTP writer close error: %s", e)

    def _route(self, method: str, path: str, body: bytes, query_params: dict[str, str] | None = None, http_version: str = "HTTP/1.1") -> bytes:  # FIXED-P1: 接受查询参数和HTTP版本
        # HTTP/1.1默认keep-alive，HTTP/1.0默认close
        keep_alive = http_version == "HTTP/1.1"
        if method == "OPTIONS":
            return self._cors_preflight_response(keep_alive)
        # FIXED-P1: 使用快照迭代，避免与 create_device/remove_device 并发修改时 RuntimeError
        for device_id, prefix in dict(self._device_prefixes).items():
            if path == prefix or path.startswith(prefix + "/"):
                rel_path = path[len(prefix):] or "/"
                behavior = self._behaviors.get(device_id)
                config = self._device_configs.get(device_id)
                if behavior and config:
                    return self._handle_device(method, rel_path, body, device_id, behavior, config, query_params, keep_alive)  # FIXED-P1

        if path == "/" or path == "/health":
            return self._json_response(200, {"status": "ok", "protocol": "http", "devices": len(self._behaviors)}, keep_alive)

        if path == "/devices":
            devices = []
            # FIXED-P1: 使用快照迭代
            for did, config in dict(self._device_configs).items():
                devices.append({"id": did, "name": config.name, "prefix": self._device_prefixes.get(did, "/api")})
            return self._json_response(200, {"devices": devices}, keep_alive)

        return self._json_response(404, {"error": "Not Found"}, keep_alive)

    def _handle_device(self, method: str, path: str, body: bytes,
                        device_id: str, behavior: HttpDeviceBehavior,
                        config: DeviceConfig, query_params: dict[str, str] | None = None,
                        keep_alive: bool = True) -> bytes:  # FIXED-P1: 接受查询参数和keep_alive
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
                return self._json_response(200, {"device_id": device_id, "points": points}, keep_alive)
            elif method == "POST" and body:
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    return self._json_response(400, {"error": "Invalid JSON body"}, keep_alive)
                for name, value in data.items():
                    behavior.set_value(name, value)
                self._log_debug("recv", "http_write",
                                msg("http", "device_written", detail=device_id),
                                device_id=device_id,
                                detail={"data": data})
                return self._json_response(200, {"ok": True}, keep_alive)

        point_name = path.lstrip("/")
        for p in config.points:
            if p.name == point_name:
                if method == "GET":
                    value = behavior.get_value(p.name)
                    # FIXED-P1: 支持?format=simple查询参数，直接返回值
                    if query_params and query_params.get("format") == "simple":
                        return self._raw_response(200, str(value), "text/plain", keep_alive)
                    tpl = self._response_templates.get(device_id)  # FIXED-P1: 支持自定义响应模板
                    if tpl:
                        try:
                            rendered = tpl.format_map({
                                "name": p.name, "value": value,
                                "unit": p.unit, "data_type": p.data_type.value,
                                "access": p.access, "timestamp": time.time(),
                                "device_id": device_id,
                            })
                            return self._raw_response(200, rendered, "application/json", keep_alive)
                        except (KeyError, ValueError, IndexError) as e:
                            logger.warning("HTTP response_template render error for %s.%s: %s", device_id, p.name, e)
                    return self._json_response(200, {
                        "name": p.name, "value": value,
                        "unit": p.unit, "data_type": p.data_type.value,
                        "access": p.access, "timestamp": time.time(),
                    }, keep_alive)
                elif method in ("PUT", "POST") and body:
                    try:
                        data = json.loads(body)
                    except (json.JSONDecodeError, TypeError):
                        return self._json_response(400, {"error": "Invalid JSON body"}, keep_alive)
                    value = data.get("value", data.get(p.name))
                    if value is not None:
                        behavior.set_value(p.name, value)
                        self._log_debug("recv", "http_write",
                                        msg("http", "point_written", detail=f"{p.name}={value}"),
                                        device_id=device_id)
                    return self._json_response(200, {"ok": True, "name": p.name, "value": behavior.get_value(p.name)}, keep_alive)
                elif method == "DELETE":
                    behavior.set_value(p.name, 0)
                    return self._json_response(200, {"ok": True}, keep_alive)

        return self._json_response(404, {"error": f"Point not found: {point_name}"}, keep_alive)

    def _cors_preflight_response(self, keep_alive: bool = True) -> bytes:
        # FIXED: P4 - W23 使用配置的 CORS origin，而非硬编码 *
        origin = self._cors_origin
        connection = "keep-alive" if keep_alive else "close"
        header = (
            "HTTP/1.1 204 No Content\r\n"
            f"Access-Control-Allow-Origin: {origin}\r\n"
            "Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH\r\n"
            "Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n"
            "Access-Control-Max-Age: 86400\r\n"
            "Content-Length: 0\r\n"
            f"Connection: {connection}\r\n"
            "\r\n"
        )
        return header.encode("utf-8")

    def _json_response(self, status: int, body: dict, keep_alive: bool = True) -> bytes:
        status_text = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large", 500: "Internal Server Error"}.get(status, "OK")
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        # FIXED: P4 - W23 使用配置的 CORS origin，而非硬编码 *
        origin = self._cors_origin
        connection = "keep-alive" if keep_alive else "close"
        header = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: {connection}\r\n"
            f"Access-Control-Allow-Origin: {origin}\r\n"
            f"Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH\r\n"
            f"Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n"
            f"\r\n"
        )
        return header.encode("utf-8") + body_bytes

    def _raw_response(self, status: int, body: str, content_type: str = "application/json", keep_alive: bool = True) -> bytes:  # FIXED-P1: 支持自定义响应模板的原始响应
        status_text = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
        body_bytes = body.encode("utf-8")
        origin = self._cors_origin
        connection = "keep-alive" if keep_alive else "close"
        header = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: {content_type}; charset=utf-8\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: {connection}\r\n"
            f"Access-Control-Allow-Origin: {origin}\r\n"
            f"\r\n"
        )
        return header.encode("utf-8") + body_bytes

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = HttpDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        api_prefix = proto_config.get("api_prefix", f"/api/{device_config.id}")
        response_template = proto_config.get("response_template", "")  # FIXED-P1: 读取自定义响应模板
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_prefixes[device_config.id] = api_prefix  # FIXED-P1: 移入_behaviors_lock内保护
            if response_template:  # FIXED-P1: 存储自定义响应模板
                self._response_templates[device_config.id] = response_template
        await self._update_default_device_async(device_config.id)

        logger.info("HTTP device created: %s (api_prefix=%s)", device_config.id, api_prefix)
        self._log_debug("system", "device_create",
                        msg("http", "device_created", name=device_config.name),
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_prefixes.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
            self._response_templates.pop(device_id, None)  # FIXED-P1: 清理响应模板
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

    def get_all_point_values(self, device_id: str | None = None) -> dict[str, Any]:
        """获取所有设备的测点值，或指定设备的测点值。

        Returns:
            如果 device_id 为 None，返回 {"device_id": {"point_name": value, ...}, ...}
            如果指定了 device_id，返回 {"point_name": value, ...}
        """
        if device_id:
            behavior = self._behaviors.get(device_id)
            if behavior:
                return behavior.get_all_values()
            return {}
        # 返回所有设备的测点值
        result = {}
        for did, behavior in self._behaviors.items():
            result[did] = behavior.get_all_values()
        return result

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address")},
                "port": {"type": "integer", "default": 8080, "description": desc("listen_port")},
                "api_prefix": {"type": "string", "default": "/api", "description": desc("http_api_prefix")},
                "cors_origin": {"type": "string", "default": "*", "description": "CORS Access-Control-Allow-Origin (use * for dev only)"},  # FIXED: P4 - W23
                "response_template": {"type": "string", "default": "", "description": desc("http_response_template", "Custom response template (supports {name},{value},{unit},{timestamp},{device_id})")},  # FIXED-P1
            },
        }
