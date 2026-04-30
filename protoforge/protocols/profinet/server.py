import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

PROFINET_ETH_TYPE = 0x8892
DCP_ETH_TYPE = 0x8892
DCP_SERVICE_GET = 0x03
DCP_SERVICE_SET = 0x04
DCP_SERVICE_IDENTIFY = 0x05
DCP_BLOCK_DEVICE_NAME = 0x02
DCP_BLOCK_IP = 0x01

PNIO_FRAME_ID_RT = 0x8000
PNIO_ALARM_HIGH = 0xFC01


class ProfinetDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0
            self._generators[p.name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def get_input_data(self, config: DeviceConfig) -> bytes:
        data = bytearray()
        for point in config.points:
            val = self._values.get(point.name, 0)
            if point.data_type.value in ("bool",):
                data.append(int(bool(val)))
            elif point.data_type.value in ("int16",):
                data += struct.pack(">h", int(val))
            elif point.data_type.value in ("uint16",):
                data += struct.pack(">H", int(val) & 0xFFFF)
            elif point.data_type.value in ("int32",):
                data += struct.pack(">i", int(val))
            elif point.data_type.value in ("uint32",):
                data += struct.pack(">I", int(val) & 0xFFFFFFFF)
            elif point.data_type.value in ("float32", "float"):
                data += struct.pack(">f", float(val))
            else:
                data += struct.pack(">H", int(val) & 0xFFFF)
        return bytes(data)

    def set_output_data(self, config: DeviceConfig, data: bytes) -> None:
        offset = 0
        for point in config.points:
            if offset >= len(data):
                break
            if point.data_type.value in ("bool",):
                self._values[point.name] = bool(data[offset])
                offset += 1
            elif point.data_type.value in ("int16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">h", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("uint16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">H", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("int32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">i", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("uint32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">I", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("float32", "float"):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">f", data[offset:offset + 4])[0]
                    offset += 4
            else:
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">H", data[offset:offset + 2])[0]
                    offset += 2


class ProfinetServer(ProtocolServer):
    protocol_name = "profinet"
    protocol_display_name = "PROFINET IO"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, ProfinetDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 34964
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._device_name = "protoforge-device"
        self._vendor_id = 0x010A
        self._device_id = 0x0100
        self._input_size = 0
        self._output_size = 0
        self._connected = False
        self._connections: set[asyncio.StreamWriter] = set()

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 34964)
        self._device_name = config.get("device_name", "protoforge-device")
        self._vendor_id = config.get("vendor_id", 0x010A)
        self._device_id = config.get("device_id", 0x0100)
        try:
            self._recalc_data_sizes()
            self._server_running = True
            self._connected = False

            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("PROFINET IO server starting on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"PROFINET IO服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port,
                                    "device_name": self._device_name})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start PROFINET server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.warning("PROFINET server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("PROFINET IO server stopped")
            self._log_debug("system", "server_stop", "PROFINET IO服务停止")

    def _recalc_data_sizes(self) -> None:
        self._input_size = 0
        self._output_size = 0
        for cfg in self._device_configs.values():
            for point in cfg.points:
                sz = self._point_size(point)
                if point.access in ("r", "rw"):
                    self._input_size += sz
                if point.access in ("w", "rw"):
                    self._output_size += sz

    def _point_size(self, point: PointConfig) -> int:
        dt = point.data_type.value
        if dt == "bool":
            return 1
        if dt in ("int16", "uint16"):
            return 2
        if dt in ("int32", "uint32", "float32", "float"):
            return 4
        if dt == "float64":
            return 8
        return 2

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
            logger.error("PROFINET IO server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("PROFINET IO connection from %s", addr)
        self._connections.add(writer)
        self._connected = True
        self._log_debug("inbound", "connect",
                        f"IO Controller连接: {addr[0]}:{addr[1]}",
                        detail={"peer": str(addr)})
        try:
            while self._server_running:
                header = await reader.readexactly(2)
                body_len = struct.unpack(">H", header)[0]
                data = await reader.readexactly(body_len) if body_len > 0 else b""
                response = self._process_tunnel_message(data, addr)
                if response:
                    resp_len = struct.pack(">H", len(response))
                    writer.write(resp_len + response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        finally:
            self._connections.discard(writer)
            self._connected = len(self._connections) > 0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_tunnel_message(self, data: bytes, addr: tuple) -> bytes | None:
        if len(data) < 2:
            return None
        msg_type = data[0]
        if msg_type == 0x01:
            return self._handle_dcp_tunnel(data, addr)
        elif msg_type == 0x02:
            return self._handle_rt_tunnel(data)
        return None

    def _handle_dcp_tunnel(self, data: bytes, addr: tuple) -> bytes | None:
        if len(data) < 6:
            return None
        service_id = data[1]
        xid = struct.unpack(">I", data[2:6])[0] if len(data) >= 6 else 0
        if service_id == DCP_SERVICE_IDENTIFY:
            resp = self._make_dcp_identify_response(data, xid)
            return b"\x01" + resp
        elif service_id == DCP_SERVICE_GET:
            resp = self._make_dcp_get_response(data, xid)
            return b"\x01" + resp
        elif service_id == DCP_SERVICE_SET:
            resp = self._make_dcp_set_response(data, xid)
            return b"\x01" + resp
        return None

    def _make_dcp_identify_response(self, data: bytes, xid: int) -> bytes:
        resp = bytearray()
        resp += struct.pack(">H", self._vendor_id)
        resp += struct.pack(">H", self._device_id)

        name_bytes = self._device_name.encode("utf-8")
        resp += struct.pack(">BH", DCP_BLOCK_DEVICE_NAME, len(name_bytes) + 4)
        resp += name_bytes
        resp += b"\x00" * ((4 - len(name_bytes) % 4) % 4)

        resp += struct.pack(">BHIHII",
                            DCP_BLOCK_IP, 14,
                            0xC0A80101,
                            0xFFFFFF00,
                            0xC0A801FE,
                            0)

        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_IDENTIFY + 1,
                              0x01,
                              xid,
                              0x0001,
                              len(resp))
        return bytes(header + resp)

    def _make_dcp_get_response(self, data: bytes, xid: int) -> bytes:
        resp = bytearray()
        name_bytes = self._device_name.encode("utf-8")
        resp += struct.pack(">BH", DCP_BLOCK_DEVICE_NAME, len(name_bytes) + 4)
        resp += name_bytes

        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_GET + 1,
                              0x01,
                              xid,
                              0x0001,
                              len(resp))
        return bytes(header + resp)

    def _make_dcp_set_response(self, data: bytes, xid: int) -> bytes:
        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_SET + 1,
                              0x01,
                              xid,
                              0x0001,
                              0)
        return bytes(header)

    def _handle_rt_tunnel(self, data: bytes) -> bytes | None:
        behavior = self._behaviors.get(self._default_device_id)
        config = self._device_configs.get(self._default_device_id)
        if not behavior or not config:
            return None

        payload = data[1:]
        if self._output_size > 0 and len(payload) >= self._output_size:
            output_data = payload[:self._output_size]
            behavior.set_output_data(config, output_data)
            self._log_debug("inbound", "cyclic_write",
                            f"PROFINET IO循环写入 {len(output_data)}字节",
                            device_id=self._default_device_id or "",
                            detail={"size": len(output_data)})

        input_data = behavior.get_input_data(config)
        self._log_debug("outbound", "cyclic_read",
                        f"PROFINET IO循环响应 {len(input_data)}字节",
                        device_id=self._default_device_id or "",
                        detail={"size": len(input_data)})
        return b"\x02" + input_data

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ProfinetDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        if proto_config.get("device_name"):
            self._device_name = proto_config["device_name"]
        if proto_config.get("vendor_id"):
            self._vendor_id = int(proto_config["vendor_id"])
        if proto_config.get("device_id"):
            self._device_id = int(proto_config["device_id"])

        self._recalc_data_sizes()

        logger.info("PROFINET IO device created: %s (input=%d, output=%d)",
                     device_config.id, self._input_size, self._output_size)
        self._log_debug("system", "device_created",
                        f"PROFINET设备创建: {device_config.name}",
                        device_id=device_config.id,
                        detail={"input_size": self._input_size,
                                "output_size": self._output_size})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._recalc_data_sizes()
        logger.info("PROFINET device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除PROFINET设备 {device_id}",
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
        success = behavior.on_write(point_name, value)
        if success:
            self._log_debug("system", "write_point",
                            f"PROFINET写入测点: {point_name}={value}",
                            device_id=device_id)
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址(TCP隧道模式)"},
                "port": {"type": "integer", "default": 34964, "description": "TCP隧道端口"},
                "device_name": {"type": "string", "default": "protoforge-device", "description": "PROFINET设备名称(DCP识别用)"},
                "vendor_id": {"type": "integer", "default": 266, "description": "厂商ID(VendorID)"},
                "device_id": {"type": "integer", "default": 256, "description": "设备ID(DeviceID)"},
            },
            "description": "TCP隧道模式 - PROFINET协议帧通过TCP传输，需配套隧道适配器连接真实控制器",
        }
