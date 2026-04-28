import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class S7DeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._values: dict[str, Any] = {}
        self._db_data: dict[int, bytearray] = {1: bytearray(1024)}
        self._point_addresses: dict[str, tuple[int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                if fixed_val is not None:
                    self._values[name] = fixed_val
                address = getattr(p, 'address', '0') or '0'
                db_number, offset = self._parse_s7_address(str(address))
                self._point_addresses[name] = (db_number, offset)
                if name in self._values:
                    self._sync_value_to_db(name, self._values[name])

    @staticmethod
    def _parse_s7_address(address: str) -> tuple[int, int]:
        try:
            if '.' in address.upper():
                parts = address.upper().split('.')
                db_number = int(parts[0].replace('DB', '') or '1')
                offset_str = parts[-1]
                offset = int(''.join(c for c in offset_str if c.isdigit()) or '0')
                return (db_number, offset)
            return (1, int(address))
        except (ValueError, IndexError):
            return (1, 0)

    def _sync_value_to_db(self, point_name: str, value: Any) -> None:
        if point_name not in self._point_addresses:
            return
        db_number, offset = self._point_addresses[point_name]
        try:
            if isinstance(value, float):
                data = struct.pack(">f", value)
            elif isinstance(value, bool):
                data = struct.pack(">?", value)
            else:
                data = struct.pack(">i", int(value))
            self.write_db_area(db_number, offset, data)
        except (ValueError, TypeError, struct.error):
            pass

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._sync_value_to_db(point_name, value)
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def get_db_area(self, db_number: int, size: int) -> bytearray:
        if db_number not in self._db_data or len(self._db_data[db_number]) < size:
            self._db_data[db_number] = bytearray(max(size, 1024))
        return self._db_data[db_number][:size]

    def write_db_area(self, db_number: int, offset: int, data: bytes) -> None:
        if db_number not in self._db_data:
            self._db_data[db_number] = bytearray(1024)
        buf = self._db_data[db_number]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data


class S7Server(ProtocolServer):
    protocol_name = "s7"
    protocol_display_name = "Siemens S7"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, S7DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_info: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 102
        self._rack = 0
        self._slot = 1
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 102)
        self._rack = config.get("rack", 0)
        self._slot = config.get("slot", 1)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("S7 server started on %s:%d (rack=%d, slot=%d)",
                         self._host, self._port, self._rack, self._slot)
            self._log_debug("system", "server_start",
                            f"S7服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start S7 server: %s", e)
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
            logger.warning("S7 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("S7 server stopped")
            self._log_debug("system", "server_stop", "S7服务停止")

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
            logger.error("S7 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("S7 connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(4096)
                if not data:
                    break
                response = self._process_s7_message(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            logger.debug("S7 connection closed: %s", addr)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("S7 writer close error: %s", e)

    def _process_s7_message(self, data: bytes) -> bytes | None:
        if len(data) < 4:
            return None

        tpkt_len = struct.unpack(">H", data[2:4])[0]
        if len(data) < tpkt_len:
            return None

        if len(data) < 10:
            return None

        pdu_type = data[4]
        if pdu_type == 0xF0:
            cotp_len = data[5]
            if len(data) < 7 + cotp_len:
                return None
            return self._make_cotp_cr_response()

        if len(data) < 17:
            return None

        msg_type = data[8]
        if msg_type == 0x01:
            return self._make_s7_connect_response(data)
        elif msg_type == 0x07:
            return self._make_s7_read_response(data)
        elif msg_type == 0x05:
            return self._make_s7_write_response(data)

        return None

    def _make_cotp_cr_response(self) -> bytes:
        return bytes([
            0x03, 0x00, 0x00, 0x0B,
            0x06,
            0xD0,
            0x00, 0x01,
            0x00, 0x01,
            0xC0,
        ])

    def _make_s7_connect_response(self, data: bytes) -> bytes:
        resp = bytearray([
            0x03, 0x00, 0x00, 0x1D,
            0x02, 0xF0, 0x80,
            0x32, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08,
            0x00, 0x00,
            0x00, 0x01,
            0x00, 0x08,
            0x00, 0x00,
            0x01, 0x00,
            0x01, 0x01,
            0x00,
            0x09, 0x00, 0x04, 0x00, 0x03, 0x01,
        ])
        return bytes(resp)

    def _make_s7_read_response(self, data: bytes) -> bytes:
        if len(data) < 31:
            return self._make_s7_error_response(data)

        area = data[26]
        db_number = struct.unpack(">H", data[27:29])[0]
        offset = struct.unpack(">H", data[29:31])[0]

        value_bytes = b"\x00\x00\x00\x00"
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            db_data = behavior.get_db_area(db_number, offset + 4)
            value_bytes = bytes(db_data[offset:offset + 4])

        result = 0xFF

        resp = bytearray([
            0x03, 0x00, 0x00, 0x1B,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12]
        resp += bytes([
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x04,
            0x00, 0x00,
            0x04, 0x00,
            result,
            0x04,
        ])
        resp += value_bytes

        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _make_s7_write_response(self, data: bytes) -> bytes:
        if len(data) >= 31:
            area = data[26]
            db_number = struct.unpack(">H", data[27:29])[0]
            offset = struct.unpack(">H", data[29:31])[0]
            write_data = data[35:39] if len(data) >= 39 else b"\x00\x00\x00\x00"
            behavior = self._behaviors.get(self._default_device_id)
            if behavior:
                behavior.write_db_area(db_number, offset, write_data)
                self._log_debug("recv", "s7_write",
                                f"写入DB{db_number}偏移{offset}",
                                detail={"db": db_number, "offset": offset, "len": len(write_data)})

        resp = bytearray([
            0x03, 0x00, 0x00, 0x19,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12]
        resp += bytes([
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x02,
            0x00, 0x00,
            0x01, 0x00,
            0xFF,
        ])
        return bytes(resp)

    def _make_s7_error_response(self, data: bytes) -> bytes:
        resp = bytearray([
            0x03, 0x00, 0x00, 0x15,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12] if len(data) > 11 else b"\x00\x00"
        resp += bytes([
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x02,
            0x00, 0x00,
            0x01, 0x00,
            0x85,
        ])
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        self._device_configs[device_id] = device_config

        behavior = S7DeviceBehavior(device_config.points)
        self._behaviors[device_id] = behavior
        self._update_default_device(device_id)

        proto_config = device_config.protocol_config or {}
        rack = proto_config.get("rack", self._rack)
        slot = proto_config.get("slot", self._slot)

        self._device_info[device_id] = {
            "module_name": device_config.name,
            "serial_number": f"PF-{device_id[:8].upper()}",
            "hardware_revision": "1",
            "firmware_revision": "V1.0.0",
            "rack": rack,
            "slot": slot,
            "db_count": 1,
            "mb_count": 256,
            "ew_count": 256,
            "aw_count": 256,
        }

        logger.info("S7 device created: %s (rack=%d, slot=%d)",
                     device_id, rack, slot)
        self._log_debug("system", "device_create",
                        f"创建S7设备 {device_config.name}",
                        device_id=device_id)
        return device_id

    async def remove_device(self, device_id: str) -> None:
        self._device_configs.pop(device_id, None)
        self._behaviors.pop(device_id, None)
        self._device_info.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("S7 device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除S7设备 {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []

        values = []
        for point in config.points:
            val = behavior.get_value(point.name)
            values.append(PointValue(
                name=point.name,
                value=val,
                timestamp=time.time(),
            ))
        return values

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": "S7 服务器监听地址",
                },
                "port": {
                    "type": "integer",
                    "default": 102,
                    "description": "S7 端口 (默认102)",
                },
                "rack": {
                    "type": "integer",
                    "default": 0,
                    "description": "机架号",
                },
                "slot": {
                    "type": "integer",
                    "default": 1,
                    "description": "槽号",
                },
            },
        }
