"""Custom TCP protocol server — user-defined frame format simulation.

Allows users to define custom TCP frame templates with hex patterns and
variable placeholders. Useful for simulating proprietary protocols.

Frame template format (in protocol_config):
  - "request_pattern": hex string with {var} placeholders, e.g. "AA BB {func} {addr:02X} {data}"
  - "response_pattern": hex string template for response
  - "length_prefix": if true, first 2 bytes = big-endian length of remaining data
  - "delimiter": optional byte sequence that marks end of frame (e.g. "0D0A")

Variables in patterns:
  - {func}: function code (from point address)
  - {addr}: address (from point address)
  - {value}: current point value (formatted per data_type)
  - {seq}: sequence number (auto-increment)

If no pattern is defined, operates in "raw echo" mode: reads data, returns
point values as hex-encoded bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120
MAX_FRAME_SIZE = 65535


class CustomTcpDeviceBehavior(StandardDeviceBehavior):
    """Custom TCP device behavior."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        self._seq: int = 0

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def get_value_bytes(self, point_name: str) -> bytes:
        """Get point value as raw bytes based on data_type."""
        val = self.get_value(point_name)
        pt = self._points.get(point_name)
        if pt is None:
            return struct.pack(">f", float(val))
        dt = pt.data_type.value if hasattr(pt, "data_type") else "float32"
        try:
            if dt == "bool":
                return bytes([0x01 if val else 0x00])
            elif dt == "uint16":
                return struct.pack(">H", int(val) & 0xFFFF)
            elif dt == "int16":
                return struct.pack(">h", int(val))
            elif dt == "uint32":
                return struct.pack(">I", int(val) & 0xFFFFFFFF)
            elif dt == "int32":
                return struct.pack(">i", int(val))
            elif dt == "float32":
                return struct.pack(">f", float(val))
            elif dt == "float64":
                return struct.pack(">d", float(val))
            elif dt == "string":
                return str(val).encode("utf-8")
            elif dt == "hex":
                return bytes.fromhex(str(val))
            else:
                return struct.pack(">f", float(val))
        except (ValueError, TypeError, struct.error):
            return struct.pack(">f", 0.0)


class CustomTcpServer(ProtocolServer):
    """Custom TCP protocol server with user-defined frame format."""

    protocol_name = "custom_tcp"
    protocol_display_name = "自定义 TCP 协议"
    protocol_description = "自定义TCP帧协议模板 - 支持用户定义帧格式，模拟私有TCP协议"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, CustomTcpDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 38000
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._frame_mode: str = "raw"  # raw, length_prefix, delimiter
        self._delimiter: bytes = b"\r\n"
        self._response_template: str = ""

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 38000)
        self._validate_port(self._port)
        self._frame_mode = config.get("frame_mode", "raw")
        self._response_template = config.get("response_template", "")
        delim = config.get("delimiter", "0D0A")
        try:
            self._delimiter = bytes.fromhex(delim)
        except ValueError:
            self._delimiter = b"\r\n"
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("Custom TCP server started on %s:%d (mode=%s)", self._host, self._port, self._frame_mode)
            self._log_debug("system", "server_start",
                            f"Custom TCP service started {self._host}:{self._port} (mode={self._frame_mode})",
                            detail={"host": self._host, "port": self._port, "mode": self._frame_mode})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start custom TCP server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            for writer in list(self._connections.keys()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._connections.clear()
        except Exception as e:
            logger.warning("Custom TCP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Custom TCP server stopped")
            self._log_debug("system", "server_stop", "Custom TCP service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Custom TCP server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"Custom TCP client connected: {peer[0]}:{peer[1]}")
        self._connections[writer] = {"peer": peer}

        try:
            while self._server_running:
                try:
                    if self._frame_mode == "delimiter":
                        data = await asyncio.wait_for(
                            reader.readuntil(self._delimiter), timeout=_READ_TIMEOUT
                        )
                        data = data[:-len(self._delimiter)]
                    elif self._frame_mode == "length_prefix":
                        len_bytes = await asyncio.wait_for(reader.readexactly(2), timeout=_READ_TIMEOUT)
                        frame_len = struct.unpack(">H", len_bytes)[0]
                        if frame_len > MAX_FRAME_SIZE:
                            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                                       f"frame too large: {frame_len}")
                            break
                        data = await asyncio.wait_for(reader.readexactly(frame_len), timeout=10)
                    else:
                        # Raw mode: read available data
                        data = await asyncio.wait_for(reader.read(4096), timeout=_READ_TIMEOUT)
                        if not data:
                            break
                except asyncio.TimeoutError:
                    break
                except asyncio.IncompleteReadError:
                    break
                except asyncio.LimitOverrunError:
                    data = await reader.read(4096)

                self._log_debug("recv", "frame",
                                f"Custom TCP recv: {data.hex(' ')} ({len(data)} bytes)",
                                detail={"hex": data.hex(), "len": len(data)})

                response = await self._process_request(data)
                if response:
                    try:
                        if self._frame_mode == "length_prefix":
                            writer.write(struct.pack(">H", len(response)) + response)
                        elif self._frame_mode == "delimiter":
                            writer.write(response + self._delimiter)
                        else:
                            writer.write(response)
                        await writer.drain()
                    except Exception as e:
                        logger.debug("Custom TCP send error: %s", e)
                        break

        except Exception:
            logger.exception("Custom TCP connection handler error from %s", peer)
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, "connection handler error")
        finally:
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"Custom TCP client disconnected: {peer[0]}:{peer[1]}")

    async def _process_request(self, data: bytes) -> bytes:
        """Process request data and return response bytes.

        In raw mode: return all point values concatenated.
        In template mode: format response using the template.
        """
        if not self._behaviors:
            return b""

        # Use the first (or default) device
        device_id = self._default_device_id or next(iter(self._behaviors.keys()))
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return b""

        if self._response_template:
            return self._format_response(behavior, data)

        # Default: return all point values as hex bytes
        result = bytearray()
        for point_name in behavior._points:
            result.extend(behavior.get_value_bytes(point_name))
        return bytes(result)

    def _format_response(self, behavior: CustomTcpDeviceBehavior, request_data: bytes) -> bytes:
        """Format response using template."""
        template = self._response_template
        result = bytearray()

        # Parse hex template with variables
        parts = template.split()
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                var = part[1:-1].lower()
                if var == "seq":
                    result.extend(struct.pack(">H", behavior.next_seq()))
                elif var == "all_points":
                    for point_name in behavior._points:
                        result.extend(behavior.get_value_bytes(point_name))
                elif var in behavior._points:
                    result.extend(behavior.get_value_bytes(var))
                elif var == "echo":
                    result.extend(request_data)
                else:
                    result.extend(b"\x00\x00")
            else:
                try:
                    result.append(int(part, 16))
                except ValueError:
                    result.extend(part.encode("ascii"))

        return bytes(result)

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = CustomTcpDeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"Custom TCP device created: {device_config.name} ({len(device_config.points)} points)",
                        device_id=device_config.id)
        logger.info("Custom TCP device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name in behavior._points:
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(),
                                      quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "frame_mode": {
                    "type": "string", "default": "raw",
                    "description": "Frame mode: raw, length_prefix, or delimiter",
                    "enum": ["raw", "length_prefix", "delimiter"]
                },
                "delimiter": {
                    "type": "string", "default": "0D0A",
                    "description": "Hex delimiter bytes (for delimiter mode)"
                },
                "response_template": {
                    "type": "string", "default": "",
                    "description": "Response template: hex bytes and {variables} (e.g. 'AA BB {seq} {all_points}')"
                },
                "port": {
                    "type": "number", "default": 38000,
                    "description": "TCP port"
                },
            },
        }
