import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)


class S7DeviceBehavior(DeviceBehavior):
    S7_AREA_DB = 0x84
    S7_AREA_INPUTS = 0x81
    S7_AREA_OUTPUTS = 0x82
    S7_AREA_MARKERS = 0x83
    S7_AREA_TIMERS = 0x1D
    S7_AREA_COUNTERS = 0x1C

    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._db_data: dict[int, bytearray] = {1: bytearray(1024)}
        self._marker_data: bytearray = bytearray(256)
        self._input_data: bytearray = bytearray(256)
        self._output_data: bytearray = bytearray(256)
        self._point_addresses: dict[str, tuple[int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                self._points[name] = p
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                if fixed_val is not None:
                    self._values[name] = fixed_val
                else:
                    self._values[name] = 0
                self._generators[name] = DynamicValueGenerator(p)
                address = getattr(p, 'address', '0') or '0'
                db_number, offset = self._parse_s7_address(str(address))
                self._point_addresses[name] = (db_number, offset)
                if name in self._values:
                    self._sync_value_to_db(name, self._values[name])

    @staticmethod
    def _parse_s7_address(address: str) -> tuple[int, int]:
        try:
            addr_upper = address.upper().replace(' ', '')
            if addr_upper.startswith('DB'):
                parts = addr_upper.split('.')
                db_number = int(parts[0].replace('DB', '') or '1')
                if len(parts) >= 2:
                    offset_part = parts[1]
                    if offset_part.startswith('DBD'):
                        offset = int(offset_part[3:] or '0')
                    elif offset_part.startswith('DBW'):
                        offset = int(offset_part[3:] or '0')
                    elif offset_part.startswith('DBX'):
                        byte_bit = offset_part[3:]
                        if '.' in byte_bit:
                            byte_str, _ = byte_bit.split('.')
                            offset = int(byte_str or '0')
                        else:
                            offset = int(byte_bit or '0')
                    elif offset_part.startswith('DBB'):
                        offset = int(offset_part[3:] or '0')
                    else:
                        offset = int(''.join(c for c in offset_part if c.isdigit()) or '0')
                    return (db_number, offset)
                return (db_number, 0)
            return (1, int(''.join(c for c in address if c.isdigit()) or '0'))
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

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._sync_value_to_db(point_name, value)
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._sync_value_to_db(point_name, value)

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def get_db_area(self, db_number: int, size: int) -> bytearray:
        if db_number not in self._db_data or len(self._db_data[db_number]) < size:
            self._db_data[db_number] = bytearray(max(size, 1024))
        return self._db_data[db_number]

    def write_db_area(self, db_number: int, offset: int, data: bytes) -> None:
        if db_number not in self._db_data:
            self._db_data[db_number] = bytearray(1024)
        buf = self._db_data[db_number]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data

    def read_area(self, area: int, db_number: int, offset: int, size: int) -> bytes:
        if area == self.S7_AREA_DB:
            buf = self.get_db_area(db_number, offset + size)
            return bytes(buf[offset:offset + size])
        elif area == self.S7_AREA_MARKERS:
            end = min(offset + size, len(self._marker_data))
            return bytes(self._marker_data[offset:end])
        elif area == self.S7_AREA_INPUTS:
            end = min(offset + size, len(self._input_data))
            return bytes(self._input_data[offset:end])
        elif area == self.S7_AREA_OUTPUTS:
            end = min(offset + size, len(self._output_data))
            return bytes(self._output_data[offset:end])
        return b"\x00" * size

    def write_area(self, area: int, db_number: int, offset: int, data: bytes) -> None:
        if area == self.S7_AREA_DB:
            self.write_db_area(db_number, offset, data)
        elif area == self.S7_AREA_MARKERS:
            end = offset + len(data)
            if end > len(self._marker_data):
                self._marker_data.extend(bytearray(end - len(self._marker_data)))
            self._marker_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_INPUTS:
            end = offset + len(data)
            if end > len(self._input_data):
                self._input_data.extend(bytearray(end - len(self._input_data)))
            self._input_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_OUTPUTS:
            end = offset + len(data)
            if end > len(self._output_data):
                self._output_data.extend(bytearray(end - len(self._output_data)))
            self._output_data[offset:offset + len(data)] = data


class S7Server(ProtocolServer):
    protocol_name = "s7"
    protocol_display_name = "Siemens S7"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, S7DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_info: dict[str, dict] = {}
        self._rack_slot_map: dict[tuple[int, int], str] = {}
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
        connection_device_id: str | None = None
        try:
            while self._server_running:
                data = await reader.read(4096)
                if not data:
                    break
                response, device_id = self._process_s7_message(data, connection_device_id)
                if device_id is not None:
                    connection_device_id = device_id
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

    def _process_s7_message(self, data: bytes, device_id: str | None = None) -> tuple[bytes | None, str | None]:
        if len(data) < 4:
            return None, None

        tpkt_len = struct.unpack(">H", data[2:4])[0]
        if len(data) < tpkt_len:
            return None, None

        if len(data) < 10:
            return None, None

        pdu_type = data[4]
        if pdu_type == 0xF0:
            cotp_len = data[5]
            if len(data) < 7 + cotp_len:
                return None, None
            resolved_id = self._resolve_device_from_cotp(data)
            return self._make_cotp_cr_response(), resolved_id

        if len(data) < 17:
            return None, None

        msg_type = data[8]
        if msg_type == 0x01:
            return self._make_s7_connect_response(data), None
        elif msg_type == 0x07:
            return self._make_s7_read_response(data, device_id), None
        elif msg_type == 0x05:
            return self._make_s7_write_response(data, device_id), None
        elif msg_type == 0x04:
            return self._make_s7_szl_response(data, device_id), None

        return None, None

    def _make_cotp_cr_response(self) -> bytes:
        return bytes([
            0x03, 0x00, 0x00, 0x0B,
            0x06,
            0xD0,
            0x00, 0x01,
            0x00, 0x01,
            0xC0,
        ])

    def _resolve_device_from_cotp(self, data: bytes) -> str | None:
        try:
            offset = 11
            while offset + 1 < len(data):
                param_code = data[offset]
                param_len = data[offset + 1]
                if offset + 2 + param_len > len(data):
                    break
                if param_code == 0xC1 and param_len >= 2:
                    tsap = struct.unpack(">H", data[offset + 2:offset + 4])[0]
                    tsap_low = tsap & 0xFF
                    rack = (tsap_low >> 5) & 0x07
                    slot = tsap_low & 0x1F
                    device_id = self._rack_slot_map.get((rack, slot))
                    if device_id:
                        logger.debug("S7 COTP CR resolved rack=%d slot=%d -> device %s",
                                     rack, slot, device_id)
                        return device_id
                    return self._default_device_id
                offset += 2 + param_len
        except (IndexError, struct.error) as e:
            logger.debug("S7 COTP CR parse error: %s", e)
        return self._default_device_id

    def _make_s7_connect_response(self, data: bytes) -> bytes:
        pdu_size_req = 480
        max_amq_caller = 8
        max_amq_callee = 8
        try:
            s7_offset = 0
            for i in range(len(data) - 1):
                if data[i] == 0x32 and data[i + 1] in (0x01, 0x03):
                    s7_offset = i
                    break
            if s7_offset > 0 and len(data) > s7_offset + 18:
                param_start = s7_offset + 14
                if data[param_start] == 0xF0 and len(data) > param_start + 5:
                    pdu_size_req = struct.unpack(">H", data[param_start + 3:param_start + 5])[0]
                    if len(data) > param_start + 7:
                        max_amq_caller = struct.unpack(">H", data[param_start + 5:param_start + 7])[0] or 8
                    if len(data) > param_start + 9:
                        max_amq_callee = struct.unpack(">H", data[param_start + 7:param_start + 9])[0] or 8
        except Exception:
            pass
        pdu_size = min(max(pdu_size_req, 128), 960)
        max_amq_caller = min(max(max_amq_caller, 1), 64)
        max_amq_callee = min(max(max_amq_callee, 1), 64)
        resp = bytearray([
            0x03, 0x00, 0x00, 0x1D,
            0x02, 0xF0, 0x80,
            0x32, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08,
            0x00, 0x00,
            0x00, 0x01,
        ])
        resp += struct.pack(">H", pdu_size)
        resp += struct.pack(">H", max_amq_callee)
        resp += struct.pack(">H", max_amq_caller)
        return bytes(resp)

    def _make_s7_read_response(self, data: bytes, device_id: str | None = None) -> bytes:
        if len(data) < 14:
            return self._make_s7_error_response(data)

        param_start = 14
        if len(data) <= param_start + 2:
            return self._make_s7_error_response(data)

        func_code = data[param_start]
        if func_code != 0x04:
            return self._make_s7_error_response(data)

        item_count = data[param_start + 2] if len(data) > param_start + 2 else 1
        if item_count == 0:
            item_count = 1

        item_offset = param_start + 3
        item_results = []

        for i in range(item_count):
            if item_offset + 12 > len(data):
                item_results.append((0x0A, b"\x00"))
                continue

            item_spec = data[item_offset:item_offset + 12]
            item_offset += 12

            spec_type = item_spec[0]
            if spec_type != 0x12:
                item_results.append((0x0A, b"\x00"))
                continue

            transport_size_code = item_spec[1]
            length = struct.unpack(">H", item_spec[2:4])[0]
            area = item_spec[6]
            db_number = struct.unpack(">H", item_spec[7:9])[0]
            byte_addr = struct.unpack(">H", item_spec[9:11])[0]
            bit_addr = item_spec[11]
            offset = (byte_addr << 3) | (bit_addr & 0x07)

            if transport_size_code == 0x09:
                read_size = (length + 7) // 8
                is_bit = True
            else:
                read_size = length
                is_bit = False

            if read_size <= 0:
                read_size = 1
            if read_size > 65535:
                read_size = 65535

            value_bytes = b"\x00" * read_size
            behavior = self._behaviors.get(device_id or self._default_device_id)
            if behavior:
                value_bytes = behavior.read_area(area, db_number, offset // 8 if is_bit else offset, read_size)

            item_results.append((0xFF, value_bytes))

        data_len = 0
        for result_code, val_bytes in item_results:
            data_len += 1 + 1 + 2 + len(val_bytes)
            if len(val_bytes) % 2 != 0:
                data_len += 1

        param_len = 2 + item_count
        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12]
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">H", param_len)
        resp += struct.pack(">H", data_len)

        resp += bytes([0x04])
        resp += bytes([0x00])
        resp += bytes([item_count])

        for result_code, val_bytes in item_results:
            resp += bytes([result_code])
            if result_code != 0xFF:
                resp += bytes([0x00])
                resp += struct.pack(">H", 0)
            else:
                transport_size = 0x09 if len(val_bytes) <= 1 else 0x04
                resp += bytes([transport_size])
                resp += struct.pack(">H", len(val_bytes))
                resp += val_bytes
                if len(val_bytes) % 2 != 0:
                    resp += bytes([0x00])

        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _make_s7_write_response(self, data: bytes, device_id: str | None = None) -> bytes:
        if len(data) < 14:
            return self._make_s7_error_response(data)

        param_start = 14
        func_code = data[param_start] if len(data) > param_start else 0x05
        item_count = data[param_start + 2] if len(data) > param_start + 2 else 1
        if item_count == 0:
            item_count = 1

        item_offset = param_start + 3
        result_codes = []

        for i in range(item_count):
            if item_offset + 12 > len(data):
                result_codes.append(0x0A)
                continue

            item_spec = data[item_offset:item_offset + 12]
            item_offset += 12

            spec_type = item_spec[0]
            if spec_type != 0x12:
                result_codes.append(0x0A)
                continue

            area = item_spec[6]
            db_number = struct.unpack(">H", item_spec[7:9])[0]
            byte_addr = struct.unpack(">H", item_spec[9:11])[0]
            bit_addr = item_spec[11]
            offset = (byte_addr << 3) | (bit_addr & 0x07)

            write_data = b"\x00\x00\x00\x00"
            data_section_start = param_start + 3 + item_count * 12
            if data_section_start + 4 <= len(data):
                data_item_count = data[data_section_start] if len(data) > data_section_start else 0
                ptr = data_section_start + 1
                for j in range(i + 1):
                    if ptr + 4 > len(data):
                        break
                    rc = data[ptr]
                    ts = data[ptr + 1]
                    dlen = struct.unpack(">H", data[ptr + 2:ptr + 4])[0]
                    if j == i and ptr + 4 + dlen <= len(data):
                        write_data = data[ptr + 4:ptr + 4 + dlen]
                    ptr += 4 + dlen
                    if dlen % 2 != 0:
                        ptr += 1

            behavior = self._behaviors.get(device_id or self._default_device_id)
            if behavior:
                behavior.write_area(area, db_number, offset, write_data)
                area_name = {0x84: "DB", 0x81: "I", 0x82: "Q", 0x83: "M"}.get(area, f"0x{area:02X}")
                self._log_debug("recv", "s7_write",
                                f"写入{area_name}{db_number}偏移{offset}",
                                detail={"area": area_name, "db": db_number, "offset": offset, "len": len(write_data)})
            result_codes.append(0xFF)

        param_len = 2 + item_count
        data_len = item_count

        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12]
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">H", param_len)
        resp += struct.pack(">H", data_len)

        resp += bytes([0x05])
        resp += bytes([0x00])
        resp += bytes([item_count])

        for rc in result_codes:
            resp += bytes([rc])

        resp[2:4] = struct.pack(">H", len(resp))
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

    def _make_s7_szl_response(self, data: bytes, device_id: str | None = None) -> bytes:
        szl_id = struct.unpack(">H", data[26:28])[0] if len(data) >= 28 else 0x0011
        szl_index = struct.unpack(">H", data[28:30])[0] if len(data) >= 30 else 0x0000

        if szl_id == 0x0011:
            szl_data = self._build_szl_module_identification(szl_index)
        elif szl_id == 0x0012:
            szl_data = self._build_szl_component_identification(szl_index)
        elif szl_id == 0x001C:
            szl_data = self._build_szl_cpu_features()
        else:
            szl_data = self._build_szl_module_identification(0x0000)

        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
        ])
        resp += data[10:12] if len(data) > 11 else b"\x00\x00"
        resp += bytes([
            0x00, 0x00, 0x00, 0x00,
        ])
        resp += struct.pack(">H", 2 + len(szl_data))
        resp += bytes([
            0x00, 0x00,
            0xFF,
            0x04,
            0x01,
        ])
        resp += struct.pack(">H", szl_id)
        resp += szl_data
        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _build_szl_module_identification(self, index: int) -> bytes:
        return struct.pack(">HHHHHII",
            0x0001,
            index or 0x0001,
            0x3131,
            0x0001,
            0x0000,
            0x00000000,
            0x00000000,
        ) + b"ProtoForge S7\x00\x00\x00"

    def _build_szl_component_identification(self, index: int) -> bytes:
        return struct.pack(">HHHH",
            0x0001,
            index or 0x0001,
            0x0001,
            0x0000,
        ) + b"6ES7 000-0AA00-0AA0\x00"

    def _build_szl_cpu_features(self) -> bytes:
        return struct.pack(">HHHHHHHH",
            0x0001,
            0x0001,
            0x0001,
            0x0001,
            0x0000,
            0x0000,
            0x0000,
            0x0000,
        )

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
        self._rack_slot_map[(rack, slot)] = device_id

        logger.info("S7 device created: %s (rack=%d, slot=%d)",
                     device_id, rack, slot)
        self._log_debug("system", "device_create",
                        f"创建S7设备 {device_config.name}",
                        device_id=device_id)
        return device_id

    async def remove_device(self, device_id: str) -> None:
        self._device_configs.pop(device_id, None)
        self._behaviors.pop(device_id, None)
        info = self._device_info.pop(device_id, None)
        if info:
            rack = info.get("rack", 0)
            slot = info.get("slot", 1)
            self._rack_slot_map.pop((rack, slot), None)
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
        return behavior.on_write(point_name, value)

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
