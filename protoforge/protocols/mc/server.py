import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class McDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[dict]):
        self._points = {p["name"]: p for p in points}
        self._values: dict[str, Any] = {}
        self._device_memory: dict[int, bytearray] = {}
        for p in points:
            self._values[p["name"]] = p.get("fixed_value", 0)

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def read_memory(self, area_code: int, size: int) -> bytearray:
        if area_code not in self._device_memory or len(self._device_memory[area_code]) < size:
            self._device_memory[area_code] = bytearray(max(size, 1024))
        return self._device_memory[area_code][:size]

    def write_memory(self, area_code: int, offset: int, data: bytes) -> None:
        if area_code not in self._device_memory:
            self._device_memory[area_code] = bytearray(1024)
        buf = self._device_memory[area_code]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data


class McServer(ProtocolServer):
    protocol_name = "mc"
    protocol_display_name = "Mitsubishi MC"

    SLMP_3E_BIN_SUBHEADER = 0x0054

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, McDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 5000
        self._network = 0
        self._station = 0
        self._pc = 0xFF
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5000)
        self._network = config.get("network", 0)
        self._station = config.get("station", 0)
        self._pc = config.get("pc", 0xFF)
        self._status = ProtocolStatus.RUNNING
        self._server_running = True
        self._server_task = asyncio.create_task(self._serve())
        logger.info("MC server started on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        self._server_running = False
        self._status = ProtocolStatus.STOPPED
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("MC server stopped")

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
            logger.error("MC server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("MC connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(4096)
                if not data:
                    break
                response = self._process_slmp(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_slmp(self, data: bytes) -> bytes | None:
        if len(data) < 11:
            return None

        subheader = struct.unpack("<H", data[0:2])[0]
        if subheader != self.SLMP_3E_BIN_SUBHEADER:
            return self._make_error_response(data, 0xC059)

        network = data[2]
        pc = data[3]
        req_dest_io = struct.unpack("<H", data[4:6])[0]
        req_dest_station = data[6]
        req_data_len = struct.unpack("<H", data[7:9])[0]
        cpu_monitor_timer = struct.unpack("<H", data[9:11])[0]

        if len(data) < 15:
            return self._make_error_response(data, 0xC059)

        cmd = struct.unpack("<H", data[11:13])[0]
        subcmd = struct.unpack("<H", data[13:15])[0]

        if cmd == 0x0401:
            return self._handle_read(data, subcmd)
        elif cmd == 0x1401:
            return self._handle_write(data, subcmd)
        elif cmd == 0x0001:
            return self._handle_batch_read(data, subcmd)

        return self._make_error_response(data, 0xC059)

    def _handle_read(self, data: bytes, subcmd: int) -> bytes:
        if len(data) < 21:
            return self._make_error_response(data, 0xC059)

        start_addr = struct.unpack("<H", data[15:17])[0]
        device_code = data[17]
        word_count = struct.unpack("<H", data[18:20])[0]

        if subcmd == 0x0000:
            read_len = word_count * 2
        elif subcmd == 0x0001:
            read_len = word_count
        else:
            return self._make_error_response(data, 0xC059)

        read_data = bytearray(read_len)
        for behavior in self._behaviors.values():
            mem = behavior.read_memory(device_code, start_addr + read_len)
            read_data = mem[start_addr:start_addr + read_len]
            break

        resp = bytearray()
        resp += struct.pack("<H", self.SLMP_3E_BIN_SUBHEADER)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", read_len + 2)
        resp += struct.pack("<H", 0x0000)
        resp += read_data

        return bytes(resp)

    def _handle_write(self, data: bytes, subcmd: int) -> bytes:
        if len(data) < 21:
            return self._make_error_response(data, 0xC059)

        start_addr = struct.unpack("<H", data[15:17])[0]
        device_code = data[17]
        word_count = struct.unpack("<H", data[18:20])[0]

        if subcmd == 0x0000:
            write_len = word_count * 2
        elif subcmd == 0x0001:
            write_len = word_count
        else:
            return self._make_error_response(data, 0xC059)

        write_data = data[20:20 + write_len]
        for behavior in self._behaviors.values():
            behavior.write_memory(device_code, start_addr, write_data)
            break

        resp = bytearray()
        resp += struct.pack("<H", self.SLMP_3E_BIN_SUBHEADER)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", 0x0000)

        return bytes(resp)

    def _handle_batch_read(self, data: bytes, subcmd: int) -> bytes:
        return self._handle_read(data, subcmd)

    def _make_error_response(self, data: bytes, error_code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", self.SLMP_3E_BIN_SUBHEADER)
        if len(data) >= 7:
            resp += data[2:7]
        else:
            resp += bytes([0, 0, 0, 0, 0])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", error_code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = McDeviceBehavior([p.model_dump() for p in device_config.points])
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        logger.info("MC device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("MC device removed: %s", device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []
        now = time.time()
        return [PointValue(name=p.name, value=behavior.get_value(p.name), timestamp=now) for p in config.points]

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "MC 服务器监听地址"},
                "port": {"type": "integer", "default": 5000, "description": "MC 端口 (默认5000)"},
                "network": {"type": "integer", "default": 0, "description": "网络号"},
                "station": {"type": "integer", "default": 0, "description": "站号"},
                "pc": {"type": "integer", "default": 255, "description": "PC号 (0xFF=自身)"},
            },
        }
