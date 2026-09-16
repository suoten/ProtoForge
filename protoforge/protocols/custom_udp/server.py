"""Custom UDP protocol server — user-defined frame format simulation over UDP.

Similar to CustomTcpServer but uses UDP datagrams. Each datagram is treated
as a complete frame.
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


class CustomUdpDeviceBehavior(StandardDeviceBehavior):
    """Custom UDP device behavior."""

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


class CustomUdpServer(ProtocolServer):
    """Custom UDP protocol server with user-defined frame format."""

    protocol_name = "custom_udp"
    protocol_display_name = "自定义 UDP 协议"
    protocol_description = "自定义UDP帧协议模板 - 支持用户定义帧格式，模拟私有UDP协议"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, CustomUdpDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 38001
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._response_template: str = ""

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 38001)
        self._validate_port(self._port)
        self._response_template = config.get("response_template", "")
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("Custom UDP server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"Custom UDP service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start custom UDP server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
        except Exception as e:
            logger.warning("Custom UDP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Custom UDP server stopped")
            self._log_debug("system", "server_stop", "Custom UDP service stopped")

    async def _serve(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(self), local_addr=(self._host, self._port)
            )
            try:
                await asyncio.Future()  # run forever
            finally:
                transport.close()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Custom UDP server error: %s", e)
            self._status = ProtocolStatus.ERROR

    def on_datagram(self, data: bytes, addr: tuple) -> bytes | None:
        """Process incoming UDP datagram, return response bytes or None."""
        self._log_debug("recv", "datagram",
                        f"Custom UDP recv from {addr[0]}:{addr[1]}: {data.hex(' ')} ({len(data)} bytes)",
                        detail={"hex": data.hex(), "len": len(data), "from": f"{addr[0]}:{addr[1]}"})

        if not self._behaviors:
            return None

        device_id = self._default_device_id or next(iter(self._behaviors.keys()))
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return None

        if self._response_template:
            return self._format_response(behavior, data)

        # Default: return all point values
        result = bytearray()
        for point_name in behavior._points:
            result.extend(behavior.get_value_bytes(point_name))
        return bytes(result)

    def _format_response(self, behavior: CustomUdpDeviceBehavior, request_data: bytes) -> bytes:
        template = self._response_template
        result = bytearray()
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
        behavior = CustomUdpDeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        logger.info("Custom UDP device created: %s (%d points)", device_config.id, len(device_config.points))
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
                "response_template": {
                    "type": "string", "default": "",
                    "description": "Response template: hex bytes and {variables} (e.g. 'AA BB {seq} {all_points}')"
                },
                "port": {
                    "type": "number", "default": 38001,
                    "description": "UDP port"
                },
            },
        }


class _UdpProtocol(asyncio.DatagramProtocol):
    """Internal UDP protocol handler."""

    def __init__(self, server: CustomUdpServer):
        self._server = server
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        response = self._server.on_datagram(data, addr)
        if response and self._transport:
            self._transport.sendto(response, addr)
            self._server._log_debug("send", "datagram",
                                    f"Custom UDP sent to {addr[0]}:{addr[1]}: {response.hex(' ')} ({len(response)} bytes)")

    def error_received(self, exc: Exception) -> None:
        logger.warning("Custom UDP error: %s", exc)
        self._server.record_protocol_error(ProtocolErrorCategory.NETWORK, str(exc))
