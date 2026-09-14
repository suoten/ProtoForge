"""CoAP (Constrained Application Protocol, RFC 7252) protocol server implementation.

Implements a simplified CoAP server that responds to GET/POST/PUT/DELETE requests
over UDP. Designed for IoT constrained device simulation.

Supports:
  - CoAP message format (version 1, message type, token, options)
  - Confirmable (CON) and Non-confirmable (NON) messages
  - GET (read point), POST (write point), PUT (create/update), DELETE (reset)
  - Uri-Path option parsing for resource addressing
  - Content-Format JSON (application/json = 50)
  - Piggybacked response (ACK with response payload)
  - Observe option (RFC 7641) for push-based data subscription
  - Discovery via /.well-known/core (RFC 6690)

No third-party CoAP library required — pure Python asyncio UDP.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120

# CoAP message types
TYPE_CON = 0  # Confirmable
TYPE_NON = 1  # Non-confirmable
TYPE_ACK = 2  # Acknowledgement
TYPE_RST = 3  # Reset

# CoAP method codes
METHOD_GET = 0x01
METHOD_POST = 0x02
METHOD_PUT = 0x03
METHOD_DELETE = 0x04

# Response codes
RESP_CREATED = 0x41  # 2.01 Created
RESP_DELETED = 0x42  # 2.02 Deleted
RESP_VALID = 0x43    # 2.03 Valid
RESP_CHANGED = 0x44  # 2.04 Changed
RESP_CONTENT = 0x45  # 2.05 Content
RESP_BAD_REQUEST = 0x80  # 4.00 Bad Request
RESP_UNAUTHORIZED = 0x81  # 4.01 Unauthorized
RESP_BAD_OPTION = 0x82  # 4.02 Bad Option
RESP_NOT_FOUND = 0x84  # 4.04 Not Found
RESP_METHOD_NOT_ALLOWED = 0x85  # 4.05 Method Not Allowed
RESP_UNSUPPORTED_FORMAT = 0x8F  # 4.15 Unsupported Content Format

# Option numbers
OPT_IF_MATCH = 1
OPT_URI_HOST = 3
OPT_OBSERVE = 6
OPT_URI_PORT = 7
OPT_LOCATION_PATH = 8
OPT_URI_PATH = 11
OPT_CONTENT_FORMAT = 12
OPT_MAX_AGE = 14
OPT_URI_QUERY = 15
OPT_ACCEPT = 17
OPT_LOCATION_QUERY = 20

# Content formats
CT_TEXT_PLAIN = 0
CT_JSON = 50
CT_LINK_FORMAT = 40


def _encode_varint(value: int) -> bytes:
    """Encode a CoAP option value using variable-length encoding."""
    if value < 0:
        raise ValueError("CoAP option value must be non-negative")
    if value < 13:
        return bytes([value])
    elif value < 269:
        return bytes([13, value - 13])
    elif value < 65805:
        return bytes([14, (value - 269) >> 8, (value - 269) & 0xFF])
    else:
        return bytes([15, (value - 65805) >> 16 & 0xFF,
                      (value - 65805) >> 8 & 0xFF,
                      (value - 65805) & 0xFF])


def _decode_option_delta_len(data: bytes, offset: int) -> tuple[int, int, int]:
    """Decode option delta and length, return (delta, length, bytes_consumed)."""
    if offset >= len(data):
        return 0, 0, 0
    b = data[offset]
    delta = (b >> 4) & 0x0F
    length = b & 0x0F
    consumed = 1
    if delta == 13:
        if offset + consumed >= len(data):
            return 0, 0, consumed
        delta = data[offset + consumed] + 13
        consumed += 1
    elif delta == 14:
        if offset + consumed + 1 >= len(data):
            return 0, 0, consumed
        delta = (data[offset + consumed] << 8 | data[offset + consumed + 1]) + 269
        consumed += 2
    elif delta == 15:
        return 0, 0, -1  # error

    if length == 13:
        if offset + consumed >= len(data):
            return delta, 0, consumed
        length = data[offset + consumed] + 13
        consumed += 1
    elif length == 14:
        if offset + consumed + 1 >= len(data):
            return delta, 0, consumed
        length = (data[offset + consumed] << 8 | data[offset + consumed + 1]) + 269
        consumed += 2
    elif length == 15:
        return delta, 0, -1

    return delta, length, consumed


class CoAPDeviceBehavior(StandardDeviceBehavior):
    """CoAP device behavior — maps point names to URI paths."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        # Map URI path -> point name
        self._uri_map: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                uri = addr if addr else f"sensor/{name}"
                self._uri_map[uri] = name

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def get_point_by_uri(self, uri: str) -> str | None:
        return self._uri_map.get(uri)

    def get_all_uris(self) -> list[str]:
        return list(self._uri_map.keys())


class CoAPServer(ProtocolServer):
    """CoAP protocol server (RFC 7252) — UDP-based IoT simulation."""

    protocol_name = "coap"
    protocol_display_name = "CoAP"
    protocol_description = "CoAP (RFC 7252) — 受限应用协议，面向低功耗IoT设备的Web协议"
    protocol_version = "1.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, CoAPDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 5683
        self._transport: asyncio.DatagramTransport | None = None
        self._server_running = False
        self._observe_clients: dict[tuple[str, int], dict[str, Any]] = {}  # (addr, port) -> {token, paths}
        self._observe_task: asyncio.Task | None = None
        self._push_interval: float = 5.0

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5683)
        self._validate_port(self._port)
        self._push_interval = float(config.get("push_interval", 5.0))
        try:
            self._server_running = True
            loop = asyncio.get_event_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: CoAPProtocolHandler(self),
                local_addr=(self._host, self._port),
            )
            self._observe_task = asyncio.create_task(self._observe_loop())
            self._status = ProtocolStatus.RUNNING
            logger.info("CoAP server started on %s:%d (UDP)", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"CoAP service started {self._host}:{self._port} (UDP)",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start CoAP server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._observe_task:
                self._observe_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._observe_task
            if self._transport:
                self._transport.close()
                self._transport = None
            self._observe_clients.clear()
        except Exception as e:
            logger.warning("CoAP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("CoAP server stopped")
            self._log_debug("system", "server_stop", "CoAP service stopped")

    def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming UDP datagram."""
        try:
            self.on_client_connect()
            response = self._process_coap_message(data, addr)
            if response and self._transport:
                self._transport.sendto(response, addr)
            self.on_client_disconnect()
        except Exception as e:
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, str(e))
            logger.debug("CoAP datagram error from %s: %s", addr, e)

    def _process_coap_message(self, data: bytes, addr: tuple[str, int]) -> bytes | None:
        if len(data) < 4:
            return None

        ver = (data[0] >> 6) & 0x03
        if ver != 1:
            return None

        msg_type = (data[0] >> 4) & 0x03
        token_len = data[0] & 0x0F
        code = data[1]
        msg_id = struct.unpack(">H", data[2:4])[0]

        offset = 4
        token = b""
        if token_len > 0 and offset + token_len <= len(data):
            token = data[offset:offset + token_len]
            offset += token_len

        # Parse options
        options = self._parse_options(data, offset)
        uri_path = self._get_uri_path(options)
        observe = self._get_option_value(options, OPT_OBSERVE)

        self._log_debug("recv", "coap_msg",
                        f"CoAP {self._code_name(code)} {uri_path or '/'} (type={msg_type} mid={msg_id})",
                        detail={"code": code, "type": msg_type, "mid": msg_id, "path": uri_path})

        # Handle discovery
        if uri_path == ".well-known/core" and code == METHOD_GET:
            return self._build_discovery_response(msg_type, msg_id, token)

        # Handle observe registration
        if observe is not None and code == METHOD_GET:
            self._register_observer(addr, token, uri_path)
            # Fall through to send initial data

        # Find device and point
        dev_id, point_name = self._find_resource(uri_path)
        if not dev_id:
            return self._build_response(msg_type, msg_id, token, RESP_NOT_FOUND, "Not Found")

        behavior = self._behaviors.get(dev_id)
        if not behavior:
            return self._build_response(msg_type, msg_id, token, RESP_NOT_FOUND, "Device Not Found")

        if code == METHOD_GET:
            val = behavior.get_value(point_name)
            payload = json.dumps({
                "device_id": dev_id,
                "point": point_name,
                "value": val,
                "timestamp": time.time(),
            })
            return self._build_response(msg_type, msg_id, token, RESP_CONTENT, payload)

        elif code == METHOD_POST:
            # Write value
            payload_data = self._extract_payload(data, offset, options)
            try:
                write_val = json.loads(payload_data) if payload_data else 0
                if isinstance(write_val, dict) and "value" in write_val:
                    write_val = write_val["value"]
            except (json.JSONDecodeError, TypeError):
                write_val = payload_data.decode("utf-8", errors="replace") if payload_data else ""

            behavior.on_write(point_name, write_val)
            self._log_debug("send", "coap_write", f"CoAP write {point_name}={write_val}", device_id=dev_id)
            return self._build_response(msg_type, msg_id, token, RESP_CHANGED, "Changed")

        elif code == METHOD_PUT:
            return self._build_response(msg_type, msg_id, token, RESP_CHANGED, "Changed")

        elif code == METHOD_DELETE:
            behavior.clear_written(point_name)
            return self._build_response(msg_type, msg_id, token, RESP_DELETED, "Deleted")

        return self._build_response(msg_type, msg_id, token, RESP_METHOD_NOT_ALLOWED, "Not Allowed")

    def _parse_options(self, data: bytes, offset: int) -> list[tuple[int, bytes]]:
        options = []
        prev_delta = 0
        while offset < len(data):
            if data[offset] == 0xFF:  # Payload marker
                break
            delta, length, consumed = _decode_option_delta_len(data, offset)
            if consumed < 0 or offset + consumed + length > len(data):
                break
            option_num = prev_delta + delta
            option_val = data[offset + consumed:offset + consumed + length]
            options.append((option_num, option_val))
            prev_delta = option_num
            offset += consumed + length
        return options

    def _get_uri_path(self, options: list[tuple[int, bytes]]) -> str:
        parts = []
        for num, val in options:
            if num == OPT_URI_PATH:
                parts.append(val.decode("utf-8", errors="replace"))
        return "/".join(parts) if parts else ""

    def _get_option_value(self, options: list[tuple[int, bytes]], target: int) -> bytes | None:
        for num, val in options:
            if num == target:
                return val
        return None

    def _extract_payload(self, data: bytes, offset: int, options: list) -> bytes:
        # Find payload marker (0xFF)
        for i in range(offset, len(data)):
            if data[i] == 0xFF:
                return data[i + 1:]
        return b""

    def _find_resource(self, uri_path: str) -> tuple[str, str] | tuple[None, None]:
        for dev_id, behavior in self._behaviors.items():
            point_name = behavior.get_point_by_uri(uri_path)
            if point_name:
                return dev_id, point_name
        return None, None

    def _build_response(self, msg_type: int, msg_id: int, token: bytes,
                        code: int, payload: str) -> bytes:
        resp_type = TYPE_ACK if msg_type == TYPE_CON else TYPE_NON
        token_len = len(token) & 0x0F
        header = bytes([(1 << 6) | (resp_type << 4) | token_len, code,
                        (msg_id >> 8) & 0xFF, msg_id & 0xFF])
        # Content-Format option (JSON = 50)
        content_format_opt = bytes([OPT_CONTENT_FORMAT << 4 | 1, CT_JSON])
        result = header + token + content_format_opt
        if payload:
            result += b"\xFF" + payload.encode("utf-8")
        return result

    def _build_discovery_response(self, msg_type: int, msg_id: int, token: bytes) -> bytes:
        links = []
        for _dev_id, behavior in self._behaviors.items():
            for uri in behavior.get_all_uris():
                links.append(f"</{uri}>;ct=50;title=Sensor {uri}")
        links.append("</.well-known/core>;rt=core.wkc")
        payload = ",".join(links)
        resp_type = TYPE_ACK if msg_type == TYPE_CON else TYPE_NON
        token_len = len(token) & 0x0F
        header = bytes([(1 << 6) | (resp_type << 4) | token_len, RESP_CONTENT,
                        (msg_id >> 8) & 0xFF, msg_id & 0xFF])
        content_format_opt = bytes([OPT_CONTENT_FORMAT << 4 | 1, CT_LINK_FORMAT])
        result = header + token + content_format_opt + b"\xFF" + payload.encode("utf-8")
        return result

    def _register_observer(self, addr: tuple[str, int], token: bytes, path: str) -> None:
        key = addr
        if key not in self._observe_clients:
            self._observe_clients[key] = {"token": token, "paths": set()}
        self._observe_clients[key]["paths"].add(path)
        self._log_debug("recv", "observe", f"CoAP Observe registered: {path} from {addr[0]}:{addr[1]}")

    async def _observe_loop(self) -> None:
        try:
            while self._server_running:
                await asyncio.sleep(self._push_interval)
                if not self._observe_clients or not self._transport:
                    continue
                for addr, info in list(self._observe_clients.items()):
                    for path in info.get("paths", set()):
                        dev_id, point_name = self._find_resource(path)
                        if dev_id and point_name:
                            behavior = self._behaviors.get(dev_id)
                            if behavior:
                                val = behavior.get_value(point_name)
                                payload = json.dumps({"device_id": dev_id, "point": point_name,
                                                       "value": val, "timestamp": time.time()})
                                # Build NON notification
                                msg_id = int(time.time()) & 0xFFFF
                                token = info.get("token", b"")
                                token_len = len(token) & 0x0F
                                header = bytes([(1 << 6) | (TYPE_NON << 4) | token_len, RESP_CONTENT,
                                                (msg_id >> 8) & 0xFF, msg_id & 0xFF])
                                content_fmt = bytes([OPT_CONTENT_FORMAT << 4 | 1, CT_JSON])
                                msg = header + token + content_fmt + b"\xFF" + payload.encode("utf-8")
                                try:
                                    self._transport.sendto(msg, addr)
                                except Exception as e:
                                    logger.debug("CoAP observe push error: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("CoAP observe loop error: %s", e)

    @staticmethod
    def _code_name(code: int) -> str:
        if code == METHOD_GET:
            return "GET"
        elif code == METHOD_POST:
            return "POST"
        elif code == METHOD_PUT:
            return "PUT"
        elif code == METHOD_DELETE:
            return "DELETE"
        return f"0x{code:02X}"

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = CoAPDeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"CoAP device created: {device_config.name} ({len(device_config.points)} points)",
                        device_id=device_config.id)
        logger.info("CoAP device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_remove", f"CoAP device removed: {device_id}", device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name in behavior._values:
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(),
                                      quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        self._log_debug("recv", "point_write", f"CoAP write {point_name}={value}", device_id=device_id)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "push_interval": {
                    "type": "number", "default": 5.0,
                    "description": "Observe push interval in seconds"
                },
            },
        }


class CoAPProtocolHandler(asyncio.DatagramProtocol):
    """Asyncio UDP protocol handler for CoAP."""

    def __init__(self, server: CoAPServer):
        self._server = server

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._server.handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("CoAP UDP error: %s", exc)
