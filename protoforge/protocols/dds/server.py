"""DDS (Data Distribution Service) protocol server implementation.

Implements a simplified DDS-like publish/subscribe protocol server.
Simulates the core concepts of OMG DDS:
  - Topics (named data channels)
  - Data Writers (publish data to topics)
  - Data Readers (subscribe to topics and receive data)
  - QoS policies (BEST_EFFORT vs RELIABLE)
  - Simple RTPS-like wire protocol over UDP/TCP

Wire protocol (simplified RTPS):
  - Magic: 'RTPS' (4 bytes)
  - Protocol version (2 bytes: major.minor)
  - Vendor ID (2 bytes)
  - GUID prefix (12 bytes)
  - Message body (variable)

This is a lightweight implementation for simulation purposes — not a full
DDS/RTPS stack. It enables testing of DDS-based applications without
requiring actual DDS middleware (OpenDDS, FastDDS, etc.).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
import uuid
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120

RTPS_MAGIC = b"RTPS"
RTPS_VERSION = b"\x02\x02"  # 2.2
RTPS_VENDOR = b"\x01\x03"   # ProtoForge vendor ID

# RTPS message types
MSG_DATA = 0x15       # DATA sub-message
MSG_DATA_FRAG = 0x16  # DATA FRAG
MSG_ACKNACK = 0x06    # ACKNACK sub-message
MSG_HEARTBEAT = 0x07  # HEARTBEAT sub-message
MSG_GAP = 0x08        # GAP sub-message
MSG_INFO_TS = 0x09    # INFO TS sub-message
MSG_INFO_SRC = 0x0C   # INFO SRC sub-message
MSG_INFO_DST = 0x0E   # INFO DST sub-message
MSG_PARTICIPANT = 0x10  # DATA(Participant)
MSG_WRITER = 0x12       # DATA(Writer)
MSG_READER = 0x14       # DATA(Reader)
MSG_PAD = 0x01
MSG_E = 0x02  # END sub-message

# Topic QoS
QOS_BEST_EFFORT = 0x01
QOS_RELIABLE = 0x02


class DDSDeviceBehavior(StandardDeviceBehavior):
    """DDS device behavior — maps point names to topics."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        # Map point name -> topic name
        self._topic_map: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                topic = addr if addr else f"protoforge/{name}"
                self._topic_map[name] = topic

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def get_topic(self, point_name: str) -> str:
        return self._topic_map.get(point_name, f"protoforge/{point_name}")

    def get_point_by_topic(self, topic: str) -> str | None:
        for name, t in self._topic_map.items():
            if t == topic:
                return name
        return None

    def get_all_topics(self) -> list[str]:
        return list(self._topic_map.values())


class DDSServer(ProtocolServer):
    """DDS-like publish/subscribe protocol server for IoT simulation."""

    protocol_name = "dds"
    protocol_display_name = "DDS"
    protocol_description = "DDS (Data Distribution Service) — OMG标准数据分发服务，面向实时系统的发布/订阅中间件"
    protocol_version = "2.2"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, DDSDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 7400
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._subscribers: dict[str, asyncio.StreamWriter] = {}  # topic -> list of subscribers
        self._guid_prefix: bytes = uuid.uuid4().bytes[:12]
        self._push_task: asyncio.Task | None = None
        self._push_interval: float = 1.0
        self._use_tcp: bool = True

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 7400)
        self._validate_port(self._port)
        self._push_interval = float(config.get("push_interval", 1.0))
        self._use_tcp = bool(config.get("use_tcp", True))
        try:
            self._server_running = True
            if self._use_tcp:
                self._server_task = asyncio.create_task(self._serve_tcp())
            else:
                loop = asyncio.get_event_loop()
                self._transport, _ = await loop.create_datagram_endpoint(
                    lambda: DDSProtocolHandler(self),
                    local_addr=(self._host, self._port),
                )
            self._push_task = asyncio.create_task(self._push_loop())
            self._status = ProtocolStatus.RUNNING
            transport_name = "TCP" if self._use_tcp else "UDP"
            logger.info("DDS server started on %s:%d (%s)", self._host, self._port, transport_name)
            self._log_debug("system", "server_start",
                            f"DDS service started {self._host}:{self._port} ({transport_name})",
                            detail={"host": self._host, "port": self._port, "transport": transport_name})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start DDS server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._push_task:
                self._push_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._push_task
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            if hasattr(self, "_transport") and self._transport:
                self._transport.close()
                self._transport = None
            for writer in self._subscribers.values():
                with contextlib.suppress(Exception):
                    writer.close()
            self._subscribers.clear()
        except Exception as e:
            logger.warning("DDS server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("DDS server stopped")
            self._log_debug("system", "server_stop", "DDS service stopped")

    async def _serve_tcp(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_tcp_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("DDS TCP server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_tcp_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"DDS client connected: {peer[0]}:{peer[1]}")

        try:
            while self._server_running:
                try:
                    header = await asyncio.wait_for(reader.readexactly(4), timeout=_READ_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if header != RTPS_MAGIC:
                    logger.debug("DDS: invalid magic from %s: %s", peer, header)
                    break

                # Read RTPS header remainder
                try:
                    await reader.readexactly(16)  # version(2)+vendor(2)+guid(12)
                except asyncio.IncompleteReadError:
                    break

                # Read sub-messages until connection closes
                while True:
                    try:
                        sub_header = await reader.readexactly(4)
                    except asyncio.IncompleteReadError:
                        break
                    sub_type = sub_header[0]
                    sub_header[1]
                    sub_len = struct.unpack(">H", sub_header[2:4])[0]
                    if sub_len > 0:
                        try:
                            sub_data = await reader.readexactly(sub_len)
                        except asyncio.IncompleteReadError:
                            break
                        await self._process_submessage(writer, sub_type, sub_data)

        except Exception as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("DDS connection error from %s: %s", peer, e)
        finally:
            # Clean up subscriber registration
            topics_to_remove = [t for t, w in self._subscribers.items() if w is writer]
            for t in topics_to_remove:
                self._subscribers.pop(t, None)
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"DDS client disconnected: {peer[0]}:{peer[1]}")

    async def _process_submessage(self, writer: asyncio.StreamWriter, sub_type: int, data: bytes) -> None:
        if sub_type == MSG_DATA:
            # Data message — could be a write or a subscription request
            await self._handle_data_msg(writer, data)
        elif sub_type == MSG_ACKNACK:
            self._log_debug("recv", "acknack", "DDS ACKNACK received")
        elif sub_type == MSG_HEARTBEAT:
            self._log_debug("recv", "heartbeat", "DDS HEARTBEAT received")
        elif sub_type == MSG_INFO_TS:
            self._log_debug("recv", "info_ts", "DDS INFO_TS received")
        else:
            self._log_debug("recv", "submsg", f"DDS sub-message type=0x{sub_type:02X} ({len(data)} bytes)")

    async def _handle_data_msg(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
            topic = payload.get("topic", "")
            action = payload.get("action", "")
            value = payload.get("value")

            if action == "subscribe" and topic:
                self._subscribers[topic] = writer
                self._log_debug("recv", "subscribe", f"DDS subscribe: {topic}")
            elif action == "publish" and topic:
                # Write to device
                for dev_id, behavior in self._behaviors.items():
                    point_name = behavior.get_point_by_topic(topic)
                    if point_name:
                        behavior.on_write(point_name, value)
                        self._log_debug("recv", "publish", f"DDS publish: {topic}={value}", device_id=dev_id)
                        break
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("DDS data parse error: %s", e)

    def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle UDP datagram for UDP mode."""
        self.on_client_connect()
        if not data.startswith(RTPS_MAGIC):
            self.on_client_disconnect()
            return
        # Simplified UDP processing
        try:
            payload_start = 20  # 4 magic + 16 header
            if len(data) > payload_start:
                payload_data = data[payload_start:]
                try:
                    payload = json.loads(payload_data.decode("utf-8"))
                    topic = payload.get("topic", "")
                    value = payload.get("value")
                    for dev_id, behavior in self._behaviors.items():
                        point_name = behavior.get_point_by_topic(topic)
                        if point_name:
                            behavior.on_write(point_name, value)
                            self._log_debug("recv", "publish", f"DDS UDP publish: {topic}={value}", device_id=dev_id)
                            break
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        except Exception as e:
            logger.debug("DDS UDP error: %s", e)
        self.on_client_disconnect()

    def _build_rtps_data_msg(self, topic: str, value: Any, dev_id: str) -> bytes:
        payload = json.dumps({
            "topic": topic,
            "value": value,
            "device_id": dev_id,
            "timestamp": time.time(),
        }).encode("utf-8")

        # RTPS header
        header = RTPS_MAGIC + RTPS_VERSION + RTPS_VENDOR + self._guid_prefix
        # DATA sub-message
        sub_msg = struct.pack(">BBH", MSG_DATA, 0x00, len(payload)) + payload
        return header + sub_msg

    async def _push_loop(self) -> None:
        """Push periodic data to subscribers."""
        try:
            while self._server_running:
                await asyncio.sleep(self._push_interval)
                if not self._subscribers:
                    continue
                for dev_id, behavior in self._behaviors.items():
                    for point_name in behavior._values:
                        topic = behavior.get_topic(point_name)
                        val = behavior.get_value(point_name)
                        msg = self._build_rtps_data_msg(topic, val, dev_id)
                        for sub_topic, writer in list(self._subscribers.items()):
                            if sub_topic == topic or sub_topic == "*":
                                try:
                                    writer.write(msg)
                                    await writer.drain()
                                except Exception as e:
                                    logger.debug("DDS push error: %s", e)
                                    self._subscribers.pop(sub_topic, None)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("DDS push loop error: %s", e)

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = DDSDeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"DDS device created: {device_config.name} ({len(device_config.points)} topics)",
                        device_id=device_config.id)
        logger.info("DDS device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_remove", f"DDS device removed: {device_id}", device_id=device_id)

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
        self._log_debug("recv", "point_write", f"DDS write {point_name}={value}", device_id=device_id)
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
                    "type": "number", "default": 1.0,
                    "description": "Data push interval in seconds"
                },
                "use_tcp": {
                    "type": "boolean", "default": True,
                    "description": "Use TCP transport (true) or UDP (false)"
                },
            },
        }


class DDSProtocolHandler(asyncio.DatagramProtocol):
    """Asyncio UDP protocol handler for DDS."""

    def __init__(self, server: DDSServer):
        self._server = server

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._server.handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("DDS UDP error: %s", exc)
