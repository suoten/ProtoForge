import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

ETHERCAT_ETH_TYPE = 0x88A4

ECAT_CMD_NOP = 0x00
ECAT_CMD_APRD = 0x01
ECAT_CMD_APWR = 0x02
ECAT_CMD_APRW = 0x03
ECAT_CMD_FPRD = 0x04
ECAT_CMD_FPWR = 0x05
ECAT_CMD_FPRW = 0x06
ECAT_CMD_BRD = 0x07
ECAT_CMD_BWR = 0x08
ECAT_CMD_BRW = 0x09
ECAT_CMD_LRD = 0x0A
ECAT_CMD_LWR = 0x0B
ECAT_CMD_LRW = 0x0C
ECAT_CMD_RW = 0x0D

ECAT_STATE_INIT = 0x01
ECAT_STATE_PREOP = 0x02
ECAT_STATE_BOOT = 0x03
ECAT_STATE_SAFEOP = 0x04
ECAT_STATE_OP = 0x08

ECAT_DL_STATUS = 0x0110
ECAT_AL_STATUS = 0x0130
ECAT_AL_STATUS_CODE = 0x0134
ECAT_STATION_ADDR = 0x0010

ECAT_ERR_UNSUPPORTED = 0x0001
ECAT_ERR_NO_SLAVE = 0x0002


class EtherCATDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._config: DeviceConfig | None = None
        self._pd_input: bytearray = bytearray()
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0
            self._generators[p.name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._sync_values_to_pd_input()
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._sync_values_to_pd_input()

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                self._sync_values_to_pd_input()
                return value
        return self._values.get(point_name, 0)

    def _sync_values_to_pd_input(self) -> None:
        if not self._config:
            return
        self._pd_input = bytearray()
        for point in self._config.points:
            val = self._values.get(point.name, 0)
            if point.data_type.value in ("bool",):
                self._pd_input.append(int(bool(val)))
            elif point.data_type.value in ("int16",):
                self._pd_input += struct.pack("<h", int(val))
            elif point.data_type.value in ("uint16",):
                self._pd_input += struct.pack("<H", int(val) & 0xFFFF)
            elif point.data_type.value in ("int32",):
                self._pd_input += struct.pack("<i", int(val))
            elif point.data_type.value in ("uint32",):
                self._pd_input += struct.pack("<I", int(val) & 0xFFFFFFFF)
            elif point.data_type.value in ("float32", "float"):
                self._pd_input += struct.pack("<f", float(val))
            else:
                self._pd_input += struct.pack("<H", int(val) & 0xFFFF)

    def get_pd_input(self, config: DeviceConfig) -> bytes:
        if self._pd_input:
            return bytes(self._pd_input)
        data = bytearray()
        for point in config.points:
            val = self._values.get(point.name, 0)
            if point.data_type.value in ("bool",):
                data.append(int(bool(val)))
            elif point.data_type.value in ("int16",):
                data += struct.pack("<h", int(val))
            elif point.data_type.value in ("uint16",):
                data += struct.pack("<H", int(val) & 0xFFFF)
            elif point.data_type.value in ("int32",):
                data += struct.pack("<i", int(val))
            elif point.data_type.value in ("uint32",):
                data += struct.pack("<I", int(val) & 0xFFFFFFFF)
            elif point.data_type.value in ("float32", "float"):
                data += struct.pack("<f", float(val))
            else:
                data += struct.pack("<H", int(val) & 0xFFFF)
        return bytes(data)

    def set_pd_output(self, config: DeviceConfig, data: bytes) -> None:
        offset = 0
        for point in config.points:
            if offset >= len(data):
                break
            if point.data_type.value in ("bool",):
                self._values[point.name] = bool(data[offset])
                offset += 1
            elif point.data_type.value in ("int16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack("<h", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("uint16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack("<H", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("int32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack("<i", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("uint32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack("<I", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("float32", "float"):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack("<f", data[offset:offset + 4])[0]
                    offset += 4
            else:
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack("<H", data[offset:offset + 2])[0]
                    offset += 2


class EtherCATServer(ProtocolServer):
    protocol_name = "ethercat"
    protocol_display_name = "EtherCAT"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, EtherCATDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 34980
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._slave_addr = 0x1001
        self._al_state = ECAT_STATE_INIT
        self._input_size = 0
        self._output_size = 0
        self._pd_input = bytearray()
        self._pd_output = bytearray()
        self._esc_regs: dict[int, bytes] = {}

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 34980)
        self._slave_addr = config.get("slave_address", 0x1001)
        try:
            self._init_esc_regs()
            self._al_state = ECAT_STATE_INIT
            self._esc_regs[ECAT_AL_STATUS] = struct.pack("<B", self._al_state)
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("EtherCAT server starting on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"EtherCAT服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start EtherCAT server: %s", e)
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
            logger.warning("EtherCAT server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("EtherCAT server stopped")
            self._log_debug("system", "server_stop", "EtherCAT服务停止")

    def _init_esc_regs(self) -> None:
        self._esc_regs[0x0000] = struct.pack("<H", 0x0444)
        self._esc_regs[ECAT_STATION_ADDR] = struct.pack("<H", self._slave_addr)
        self._esc_regs[ECAT_DL_STATUS] = struct.pack("<H", 0x0004)
        self._esc_regs[ECAT_AL_STATUS] = struct.pack("<B", self._al_state)
        self._esc_regs[ECAT_AL_STATUS_CODE] = struct.pack("<H", 0x0000)
        self._esc_regs[0x0500] = struct.pack("<H", 0x0000)
        self._esc_regs[0x0502] = struct.pack("<H", 0x0000)

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
        self._pd_input = bytearray(self._input_size)
        self._pd_output = bytearray(self._output_size)

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
            logger.error("EtherCAT server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("EtherCAT connection from %s", addr)
        self._log_debug("inbound", "connect",
                        f"EtherCAT Master连接: {addr[0]}:{addr[1]}",
                        detail={"peer": str(addr)})
        try:
            while self._server_running:
                try:
                    header = await reader.readexactly(2)
                except asyncio.IncompleteReadError:
                    break
                length = struct.unpack("<H", header)[0]
                if length > 0:
                    try:
                        payload = await reader.readexactly(length)
                    except asyncio.IncompleteReadError:
                        break
                    response = self._process_frame(header + payload)
                    if response:
                        writer.write(response)
                        await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_frame(self, data: bytes) -> bytes | None:
        if len(data) < 12:
            return None

        cmd = data[2]
        idx = data[3]
        address = struct.unpack("<I", data[4:8])[0]
        length_flags = struct.unpack("<H", data[8:10])[0]
        irq = struct.unpack("<H", data[10:12])[0]

        data_len = length_flags & 0x07FF
        more_follow = (length_flags >> 15) & 0x01

        payload = data[12:12 + data_len] if len(data) >= 12 + data_len else b""

        result_data = b""
        working_counter = 0x0000

        if cmd in (ECAT_CMD_APRD, ECAT_CMD_FPRD, ECAT_CMD_BRD, ECAT_CMD_LRD):
            result_data, working_counter = self._handle_read(cmd, address, data_len, payload)
        elif cmd in (ECAT_CMD_APWR, ECAT_CMD_FPWR, ECAT_CMD_BWR, ECAT_CMD_LWR):
            result_data, working_counter = self._handle_write(cmd, address, data_len, payload)
        elif cmd in (ECAT_CMD_APRW, ECAT_CMD_FPRW, ECAT_CMD_BRW, ECAT_CMD_LRW, ECAT_CMD_RW):
            result_data, working_counter = self._handle_read_write(cmd, address, data_len, payload)
        elif cmd == ECAT_CMD_NOP:
            working_counter = 0x0001

        resp_len = len(result_data)
        resp = bytearray()
        resp.append(cmd)
        resp.append(idx)
        resp += struct.pack("<I", address)
        resp += struct.pack("<H", resp_len | (more_follow << 15))
        resp += struct.pack("<H", irq)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<H", working_counter)
        resp += result_data

        return struct.pack("<H", len(resp)) + bytes(resp)

    def _handle_read(self, cmd: int, address: int, length: int,
                     payload: bytes) -> tuple[bytes, int]:
        if address >= 0x1000 and address < 0x2000:
            reg_data = self._read_esc_reg(address, length)
            if reg_data:
                return reg_data, 0x0001
            return b"\x00" * length, 0x0001

        if address >= 0x10000000:
            offset = address & 0x0FFFFFFF
            behavior = self._behaviors.get(self._default_device_id)
            config = self._device_configs.get(self._default_device_id)
            if behavior and config:
                input_data = behavior.get_pd_input(config)
                if offset < len(input_data):
                    end = min(offset + length, len(input_data))
                    return input_data[offset:end], 0x0001

        return b"\x00" * length, 0x0001

    def _handle_write(self, cmd: int, address: int, length: int,
                      payload: bytes) -> tuple[bytes, int]:
        if address >= 0x1000 and address < 0x2000:
            self._write_esc_reg(address, payload[:length])
            return b"", 0x0001

        if address >= 0x10000000:
            offset = address & 0x0FFFFFFF
            behavior = self._behaviors.get(self._default_device_id)
            config = self._device_configs.get(self._default_device_id)
            if behavior and config:
                behavior.set_pd_output(config, payload[:length])
                self._log_debug("inbound", "pdo_write",
                                f"EtherCAT PDO写入 {length}字节",
                                device_id=self._default_device_id or "",
                                detail={"size": length})
            return b"", 0x0001

        return b"", 0x0001

    def _handle_read_write(self, cmd: int, address: int, length: int,
                           payload: bytes) -> tuple[bytes, int]:
        read_data, wc1 = self._handle_read(cmd, address, length, payload)
        _, wc2 = self._handle_write(cmd, address, length, payload)
        return read_data, max(wc1, wc2)

    def _read_esc_reg(self, address: int, length: int) -> bytes | None:
        for reg_addr, reg_data in self._esc_regs.items():
            if address >= reg_addr and address < reg_addr + len(reg_data):
                offset = address - reg_addr
                end = min(offset + length, len(reg_data))
                return reg_data[offset:end]
        return None

    def _write_esc_reg(self, address: int, data: bytes) -> None:
        for reg_addr in list(self._esc_regs.keys()):
            reg_data = self._esc_regs[reg_addr]
            if address >= reg_addr and address < reg_addr + len(reg_data):
                offset = address - reg_addr
                new_data = bytearray(reg_data)
                end = min(offset + len(data), len(new_data))
                new_data[offset:end] = data[:end - offset]
                self._esc_regs[reg_addr] = bytes(new_data)
                if address == ECAT_AL_STATUS:
                    requested_state = data[0] if data else self._al_state
                    self._handle_al_state_transition(requested_state)
                return
        self._esc_regs[address] = data

    def _handle_al_state_transition(self, requested_state: int) -> None:
        valid_transitions = {
            ECAT_STATE_INIT: (ECAT_STATE_INIT, ECAT_STATE_PREOP, ECAT_STATE_BOOT),
            ECAT_STATE_PREOP: (ECAT_STATE_INIT, ECAT_STATE_PREOP, ECAT_STATE_SAFEOP),
            ECAT_STATE_BOOT: (ECAT_STATE_INIT, ECAT_STATE_BOOT),
            ECAT_STATE_SAFEOP: (ECAT_STATE_INIT, ECAT_STATE_PREOP, ECAT_STATE_SAFEOP, ECAT_STATE_OP),
            ECAT_STATE_OP: (ECAT_STATE_INIT, ECAT_STATE_PREOP, ECAT_STATE_SAFEOP, ECAT_STATE_OP),
        }
        current = self._al_state
        allowed = valid_transitions.get(current, (ECAT_STATE_INIT,))
        if requested_state in allowed:
            self._al_state = requested_state
            self._esc_regs[ECAT_AL_STATUS] = struct.pack("<B", self._al_state)
            self._esc_regs[ECAT_AL_STATUS_CODE] = struct.pack("<H", 0x0000)
            state_names = {0x01: "INIT", 0x02: "PREOP", 0x03: "BOOT", 0x04: "SAFEOP", 0x08: "OP"}
            self._log_debug("inbound", "state_change",
                            f"EtherCAT AL状态: {state_names.get(current, hex(current))} -> {state_names.get(requested_state, hex(requested_state))}",
                            detail={"from": current, "to": requested_state})
        else:
            self._esc_regs[ECAT_AL_STATUS_CODE] = struct.pack("<H", 0x0016)
            self._log_debug("inbound", "state_change_error",
                            f"EtherCAT AL非法状态转换: 0x{current:02X} -> 0x{requested_state:02X}",
                            detail={"from": current, "to": requested_state, "error_code": 0x0016})

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = EtherCATDeviceBehavior(device_config.points)
        behavior._config = device_config
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        if proto_config.get("slave_address"):
            self._slave_addr = int(proto_config["slave_address"])

        self._recalc_data_sizes()

        logger.info("EtherCAT device created: %s (input=%d, output=%d)",
                     device_config.id, self._input_size, self._output_size)
        self._log_debug("system", "device_created",
                        f"EtherCAT设备创建: {device_config.name}",
                        device_id=device_config.id,
                        detail={"input_size": self._input_size,
                                "output_size": self._output_size})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._recalc_data_sizes()
        logger.info("EtherCAT device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除EtherCAT设备 {device_id}",
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
                            f"EtherCAT写入测点: {point_name}={value}",
                            device_id=device_id)
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址"},
                "port": {"type": "integer", "default": 34980, "description": "EtherCAT帧服务端口"},
                "slave_address": {"type": "integer", "default": 4097, "description": "从站地址(Station Address)"},
            },
        }
