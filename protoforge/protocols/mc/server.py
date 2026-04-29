import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class McDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._device_memory: dict[int, bytearray] = {}
        self._point_addresses: dict[str, tuple[int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                address = getattr(p, 'address', '0') or '0'
                device_code, offset = self._parse_mc_address(str(address))
                self._point_addresses[name] = (device_code, offset)
                self._sync_value_to_memory(name, self._values[name])

    @staticmethod
    def _parse_mc_address(address: str) -> tuple[int, int]:
        try:
            if ':' in address:
                parts = address.split(':')
                device_code = int(parts[0])
                offset = int(parts[1]) if len(parts) > 1 else 0
                return (device_code, offset)
            return (0x44, int(address))
        except (ValueError, IndexError):
            return (0x44, 0)

    def _sync_value_to_memory(self, point_name: str, value: Any) -> None:
        if point_name not in self._point_addresses:
            return
        device_code, offset = self._point_addresses[point_name]
        try:
            if isinstance(value, float):
                data = struct.pack("<f", value)
            else:
                data = struct.pack("<H", int(value) & 0xFFFF)
            self.write_memory(device_code, offset, data)
        except (ValueError, TypeError, struct.error):
            pass

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._sync_value_to_memory(point_name, value)
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
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 5000
        self._network = 0
        self._station = 0
        self._pc = 0xFF
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5000)
        self._network = config.get("network", 0)
        self._station = config.get("station", 0)
        self._pc = config.get("pc", 0xFF)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("MC server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"MC服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start MC server: %s", e)
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
            logger.warning("MC server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MC server stopped")
            self._log_debug("system", "server_stop", "MC服务停止")

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
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            mem = behavior.read_memory(device_code, start_addr + read_len)
            read_data = mem[start_addr:start_addr + read_len]

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
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            behavior.write_memory(device_code, start_addr, write_data)
            for name, (p_code, p_offset) in behavior._point_addresses.items():
                if p_code == device_code and p_offset == start_addr:
                    try:
                        if len(write_data) >= 4:
                            behavior._values[name] = struct.unpack("<f", write_data[:4])[0]
                        elif len(write_data) >= 2:
                            behavior._values[name] = struct.unpack("<H", write_data[:2])[0]
                    except (struct.error, IndexError):
                        pass
                    break
            self._log_debug("recv", "mc_write",
                            f"写入设备{device_code}偏移{start_addr}",
                            detail={"device": device_code, "offset": start_addr, "len": len(write_data)})

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
        behavior = McDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        self._device_params[device_config.id] = {
            "network": proto_config.get("network", self._network),
            "station": proto_config.get("station", self._station),
            "pc": proto_config.get("pc", self._pc),
        }

        logger.info("MC device created: %s (network=%d, station=%d, pc=%d)",
                     device_config.id,
                     self._device_params[device_config.id]["network"],
                     self._device_params[device_config.id]["station"],
                     self._device_params[device_config.id]["pc"])
        self._log_debug("system", "device_create",
                        f"创建MC设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_params.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("MC device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除MC设备 {device_id}",
                        device_id=device_id)

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
