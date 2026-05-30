import asyncio
import logging
import os
import socket
import struct
import sys
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.modbus._common import ModbusDeviceBehavior, ModbusDataStore

logger = logging.getLogger(__name__)

SIMDATA_AVAILABLE = False
try:
    from pymodbus.simulator import SimData, SimDevice, DataType
    SIMDATA_AVAILABLE = True
except ImportError:
    DataType = None

OLD_API_AVAILABLE = False
try:
    from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
    OLD_API_AVAILABLE = True
except ImportError:
    pass

StartAsyncSerialServer = None
try:
    from pymodbus.server import StartAsyncSerialServer
except ImportError:
    pass


class ModbusRtuServer(ProtocolServer):
    protocol_name = "modbus_rtu"
    protocol_display_name = "Modbus RTU"

    _MAX_READ_COILS = 2000
    _MAX_READ_REGISTERS = 125
    _VALID_BAUDRATES = {2400, 4800, 9600, 19200, 38400, 57600, 115200}

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: Any = None
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._port = "/dev/ttyUSB0" if sys.platform != "win32" else "COM1"
        self._baudrate = 9600
        self._parity = "N"
        self._stopbits = 1
        self._bytesize = 8
        self._slave_map: dict[str, int] = {}
        self._next_slave_id = 1
        self._data_stores: dict[int, ModbusDataStore] = {}
        self._use_simdata = SIMDATA_AVAILABLE

    def _on_server_task_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Modbus RTU server task failed: %s", e)
            self._status = ProtocolStatus.ERROR

    def _add_slave_to_context(self, slave_id: int, device_context: Any) -> None:
        if self._context is None:
            return
        try:
            if hasattr(self._context, '__setitem__'):
                self._context[slave_id] = device_context
            elif hasattr(self._context, 'slave'):
                self._context.slave(slave_id, device_context)
            else:
                logger.debug("No supported method to add slave %d to context", slave_id)
        except Exception as e:
            logger.warning("Failed to add slave %d to context: %s", slave_id, e)

    def _get_data_store(self, slave_id: int) -> ModbusDataStore:
        if slave_id not in self._data_stores:
            self._data_stores[slave_id] = ModbusDataStore()
        return self._data_stores[slave_id]

    def _build_sim_devices(self) -> list:
        devices = []
        all_slave_ids = set(self._slave_map.values())
        if not all_slave_ids:
            all_slave_ids = {1}

        for slave_id in all_slave_ids:
            store = self._get_data_store(slave_id)
            simdata = [
                SimData(1, values=[store.coils.get(i, 0) for i in range(1, 101)], datatype=DataType.BITS),
                SimData(10001, values=[store.discrete_inputs.get(i, 0) for i in range(1, 101)], datatype=DataType.BITS),
                SimData(40001, values=[store.holding_regs.get(i, 0) for i in range(1, 101)], datatype=DataType.REGISTERS),
                SimData(30001, values=[store.input_regs.get(i, 0) for i in range(1, 101)], datatype=DataType.REGISTERS),
            ]
            devices.append(SimDevice(slave_id, simdata=simdata))
        return devices

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        default_port = "/dev/ttyUSB0" if sys.platform != "win32" else "COM1"
        self._port = config.get("port", default_port)
        self._baudrate = config.get("baudrate", 9600)
        if self._baudrate not in self._VALID_BAUDRATES:
            raise ValueError(
                f"Invalid baudrate {self._baudrate}. Must be one of: {sorted(self._VALID_BAUDRATES)}"
            )
        self._parity = config.get("parity", "N")
        if self._parity not in ("N", "E", "O"):
            raise ValueError(f"Parity must be N (None), E (Even), or O (Odd) (got '{self._parity}')")
        self._stopbits = config.get("stopbits", 1)
        if self._stopbits not in (1, 1.5, 2):
            raise ValueError(f"Stop bits must be 1, 1.5, or 2 (got {self._stopbits})")
        self._bytesize = config.get("bytesize", 8)
        if self._bytesize not in (5, 6, 7, 8):
            raise ValueError(f"Data bits (bytesize) must be 5, 6, 7, or 8 (got {self._bytesize})")

        if not StartAsyncSerialServer:
            raise RuntimeError("pymodbus is not installed. Install with: pip install protoforge[modbus]")

        if not self._port.startswith("/dev/") and not self._port.startswith("COM"):
            logger.info("Non-standard serial port path %s, attempting direct connection", self._port)
        elif not os.path.exists(self._port):
            # 从配置中获取 TCP bridge 端口，默认 5021，但会自动检测可用端口
            tcp_bridge_port = config.get("tcp_bridge_port", 5021)
            self._validate_port(tcp_bridge_port)
            tcp_bridge_port = self._find_available_port(tcp_bridge_port)
            logger.warning("Serial port %s does not exist, starting in TCP bridge mode on port %d", self._port, tcp_bridge_port)
            self._status = ProtocolStatus.RUNNING
            self._server_task = asyncio.create_task(self._serve_datastore_only(tcp_bridge_port))
            self._log_debug("system", "server_start",
                            f"Modbus RTU serial port {self._port} not found, falling back to TCP bridge mode on port {tcp_bridge_port}")
            return

        try:
            if self._use_simdata:
                devices = self._build_sim_devices()
                self._server_task = asyncio.create_task(
                    StartAsyncSerialServer(
                        context=devices,
                        port=self._port,
                        baudrate=self._baudrate,
                        parity=self._parity,
                        stopbits=self._stopbits,
                        bytesize=self._bytesize,
                    )
                )
            elif OLD_API_AVAILABLE:
                slaves_dict = {}
                for device_config in self._device_configs.values():
                    slave_id = self._slave_map.get(device_config.id, self._next_slave_id)
                    if device_config.id not in self._slave_map:
                        self._slave_map[device_config.id] = slave_id
                        self._next_slave_id = max(self._next_slave_id, slave_id + 1)
                    slaves_dict[slave_id] = ModbusDeviceContext(
                        hr=ModbusSequentialDataBlock(1, [0] * 100),
                        ir=ModbusSequentialDataBlock(1, [0] * 100),
                        co=ModbusSequentialDataBlock(1, [False] * 100),
                        di=ModbusSequentialDataBlock(1, [False] * 100),
                    )
                if not slaves_dict:
                    slaves_dict[1] = ModbusDeviceContext(
                        hr=ModbusSequentialDataBlock(1, [0] * 100),
                        ir=ModbusSequentialDataBlock(1, [0] * 100),
                        co=ModbusSequentialDataBlock(1, [False] * 100),
                        di=ModbusSequentialDataBlock(1, [False] * 100),
                    )
                self._context = ModbusServerContext(devices=slaves_dict, single=False)
                self._server_task = asyncio.create_task(
                    StartAsyncSerialServer(
                        context=self._context,
                        port=self._port,
                        baudrate=self._baudrate,
                        parity=self._parity,
                        stopbits=self._stopbits,
                        bytesize=self._bytesize,
                    )
                )
            else:
                logger.warning("Neither SimData nor old API available, Modbus RTU server starting in data-store-only mode")
                fallback_port = self._find_available_port(config.get("tcp_bridge_port", 5021))
                self._server_task = asyncio.create_task(
                    self._serve_datastore_only(fallback_port)
                )

            if self._server_task:
                self._server_task.add_done_callback(self._on_server_task_done)

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus RTU server starting on %s @ %d (simdata=%s)", self._port, self._baudrate, self._use_simdata)
            self._log_debug("system", "server_start",
                            f"Modbus RTU service started: {self._port} @ {self._baudrate}",
                            detail={"port": self._port, "baudrate": self._baudrate, "simdata": self._use_simdata})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Modbus RTU server: %s", e)
            raise

    @staticmethod
    def _find_available_port(start_port: int, max_tries: int = 10) -> int:
        """从 start_port 开始寻找一个可用端口。"""
        for port in range(start_port, start_port + max_tries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex(("127.0.0.1", port))
                    if result != 0:
                        return port  # 端口未被占用
            except Exception:
                return port  # 无法检测，假设可用
        return start_port  # 全部被占用，返回原始端口让后续报错

    async def _serve_datastore_only(self, tcp_port: int = 5021) -> None:
        logger.info("Modbus RTU running in TCP bridge mode on port %d (pymodbus serial unavailable)", tcp_port)
        try:
            server = await asyncio.start_server(
                self._handle_native_modbus_rtu, "0.0.0.0", tcp_port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("Modbus RTU server task cancelled")
        except Exception as e:
            logger.error("Modbus RTU TCP bridge server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_native_modbus_rtu(self, reader: asyncio.StreamReader,
                                          writer: asyncio.StreamWriter) -> None:
        _RTU_CONN_TIMEOUT = 30  # FIXED-P0: TCP桥接模式添加读取超时，防止恶意客户端挂起连接
        try:
            while True:
                try:
                    header = await asyncio.wait_for(reader.readexactly(7), timeout=_RTU_CONN_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                tx_id = struct.unpack(">H", header[0:2])[0]
                proto_id = struct.unpack(">H", header[2:4])[0]
                length = struct.unpack(">H", header[4:6])[0]
                unit_id = header[6]
                if length > 1:
                    payload = await asyncio.wait_for(reader.readexactly(length - 1), timeout=_RTU_CONN_TIMEOUT)
                else:
                    payload = b""
                fc = payload[0] if payload else 0
                resp = self._process_modbus_frame(unit_id, fc, payload[1:])
                mbap = struct.pack(">HHHB", tx_id, proto_id, len(resp) + 1, unit_id)
                writer.write(mbap + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError, BrokenPipeError, ConnectionAbortedError) as e:
            logger.debug("Modbus RTU connection handler error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Modbus RTU writer close error: %s", e)

    def _process_modbus_frame(self, unit_id: int, fc: int, data: bytes) -> bytes:
        slave_id = unit_id if unit_id else 1
        store = self._data_stores.get(slave_id)
        if not store:  # FIXED-P1: 未注册的slave_id返回异常码02，而非自动创建存储
            return bytes([fc | 0x80, 0x02])
        # FIXED-P0: 校验 data 最小长度，避免畸形报文导致 struct.unpack 崩溃
        if len(data) < 4 and fc in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
            return bytes([fc | 0x80, 0x02])  # Illegal Data Address
        try:
            if fc == 0x01:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count > self._MAX_READ_COILS:  # FIXED-P1: RTU添加读取数量上限校验
                    return bytes([fc | 0x80, 0x03])
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_coil(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x02:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count > self._MAX_READ_COILS:  # FIXED-P1: RTU添加读取数量上限校验
                    return bytes([fc | 0x80, 0x03])
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_discrete_input(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x03:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count > self._MAX_READ_REGISTERS:  # FIXED-P1: RTU添加读取数量上限校验
                    return bytes([fc | 0x80, 0x03])
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(3, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x04:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count > self._MAX_READ_REGISTERS:  # FIXED-P1: RTU添加读取数量上限校验
                    return bytes([fc | 0x80, 0x03])
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(4, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x05:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                store.set_coil(start, 1 if val == 0xFF00 else 0)
                return bytes([fc]) + data[0:4]
            elif fc == 0x06:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                store.set_point(6, start, val)
                return bytes([fc]) + data[0:4]
            elif fc == 0x0F:
                # FIXED-P0: 校验最小长度
                if len(data) < 5:
                    return bytes([fc | 0x80, 0x02])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                for i in range(count):
                    byte_idx = 5 + i // 8
                    bit_idx = i % 8
                    if byte_idx < len(data):
                        store.set_coil(start + i, 1 if data[byte_idx] & (1 << bit_idx) else 0)
                return bytes([fc]) + data[0:4]
            elif fc == 0x10:
                # FIXED-P0: 校验最小长度
                if len(data) < 5:
                    return bytes([fc | 0x80, 0x02])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                for i in range(count):
                    offset = 5 + i * 2
                    if offset + 2 <= len(data):
                        val = struct.unpack(">H", data[offset:offset + 2])[0]
                        store.set_point(16, start + i, val)
                return bytes([fc]) + data[0:4]
            elif fc == 0x16:
                if len(data) < 6:  # FIXED-P1: FC0x16需addr(2)+and_mask(2)+or_mask(2)=6字节，原值10错误
                    return bytes([fc | 0x80, 0x02])
                ref_addr = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                and_mask = struct.unpack(">H", data[2:4])[0]
                or_mask = struct.unpack(">H", data[4:6])[0]
                current = store.get_point(3, ref_addr)
                new_val = (current & and_mask) | (or_mask & ~and_mask)
                new_val = new_val & 0xFFFF
                store.set_point(16, ref_addr, new_val)
                return bytes([fc]) + data[0:6]
            elif fc == 0x17:
                if len(data) < 9:  # FIXED-P1: FC0x17需r_start(2)+r_count(2)+w_start(2)+w_count(2)+w_byte_count(1)=9字节，原值10错误
                    return bytes([fc | 0x80, 0x02])
                read_start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                read_count = struct.unpack(">H", data[2:4])[0]
                write_start = struct.unpack(">H", data[4:6])[0]  # FIXED-P0: 移除+1偏移
                write_count = struct.unpack(">H", data[6:8])[0]
                write_byte_count = data[8] if len(data) > 8 else 0
                for i in range(write_count):
                    offset = 9 + i * 2
                    if offset + 2 <= len(data):
                        val = struct.unpack(">H", data[offset:offset + 2])[0]
                        store.set_point(16, write_start + i, val)
                byte_count = read_count * 2
                regs = bytearray(byte_count)
                for i in range(read_count):
                    val = store.get_point(3, read_start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            else:
                return bytes([fc | 0x80, 0x01])
        except (IndexError, struct.error):
            return bytes([fc | 0x80, 0x02])

    async def stop(self) -> None:
        try:
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("Modbus RTU task cancelled")
                except Exception as e:
                    logger.warning("Modbus RTU server task error: %s", e)
        except Exception as e:
            logger.warning("Modbus RTU server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Modbus RTU server stopped")
            self._log_debug("system", "server_stop", "Modbus RTU service stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config
        await self._update_default_device_async(device_config.id)

        proto_config = device_config.protocol_config or {}
        slave_id = proto_config.get("slave_id", self._next_slave_id)
        if not isinstance(slave_id, int) or slave_id < 1 or slave_id > 247:
            raise ValueError(
                f"Modbus slave_id must be between 1 and 247 (got {slave_id}). "
                "0 is broadcast, 248-255 are reserved per Modbus specification."
            )
        async with self._behaviors_lock:
            self._slave_map[device_config.id] = slave_id
            self._next_slave_id = max(self._next_slave_id, slave_id + 1)

        if self._status == ProtocolStatus.RUNNING:
            self._get_data_store(slave_id)
            if not self._use_simdata and OLD_API_AVAILABLE:
                try:
                    device_context = ModbusDeviceContext(
                        hr=ModbusSequentialDataBlock(1, [0] * 100),
                        ir=ModbusSequentialDataBlock(1, [0] * 100),
                        co=ModbusSequentialDataBlock(1, [False] * 100),
                        di=ModbusSequentialDataBlock(1, [False] * 100),
                    )
                    self._add_slave_to_context(slave_id, device_context)
                except Exception as e:
                    logger.warning("Failed to create ModbusDeviceContext: %s", e)
            self._apply_device_to_context(device_config)

        logger.info("Modbus RTU device created: %s (slave_id=%d)", device_config.id, slave_id)
        self._log_debug("system", "device_created",
                        f"Modbus RTU device created: {device_config.name} (slave_id={slave_id})",
                        device_id=device_config.id,
                        detail={"slave_id": slave_id, "points": len(device_config.points)})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:  # FIXED: W3 - add _behaviors_lock protection for _behaviors and _device_configs access
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
            slave_id = self._slave_map.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock保护，防止与帧处理并发
            if slave_id is not None:
                self._data_stores.pop(slave_id, None)
        await self._clear_default_device_async(device_id)
        logger.info("Modbus RTU device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"Removed Modbus RTU device: {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        config = self._device_configs.get(device_id)
        if not config:
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
            self._apply_device_to_context(
                self._device_configs.get(device_id, DeviceConfig(id=device_id, name="", protocol="modbus_rtu"))
            )
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "port": {"type": "string", "default": "/dev/ttyUSB0", "description": "Serial port path (Linux: /dev/ttyUSB0, Windows: COM1)"},
                "baudrate": {"type": "integer", "default": 9600, "description": "Baud rate"},
                "parity": {"type": "string", "default": "N", "description": "Parity (N/E/O)"},
                "stopbits": {"type": "integer", "default": 1, "description": "Stop bits"},
                "bytesize": {"type": "integer", "default": 8, "description": "Data bits"},
            },
        }

    def _apply_device_to_context(self, config: DeviceConfig) -> None:
        behavior = self._behaviors.get(config.id)
        slave_id = self._slave_map.get(config.id, 1)
        store = self._get_data_store(slave_id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            try:  # FIXED-P0: 移除+1偏移，与TCP保持一致
                address = int(point.address)
                if point.data_type.value in ("bool",):
                    store.coils[address] = int(bool(value))
                elif point.data_type.value in ("float32",):
                    data = struct.pack(">f", float(value))
                    store.holding_regs[address] = struct.unpack(">H", data[0:2])[0]
                    store.holding_regs[address + 1] = struct.unpack(">H", data[2:4])[0]
                elif point.data_type.value in ("float64",):
                    data = struct.pack(">d", float(value))
                    for j in range(4):
                        store.holding_regs[address + j] = struct.unpack(">H", data[j * 2:j * 2 + 2])[0]
                elif point.data_type.value in ("int32",):
                    data = struct.pack(">i", int(value))
                    store.holding_regs[address] = struct.unpack(">H", data[0:2])[0]
                    store.holding_regs[address + 1] = struct.unpack(">H", data[2:4])[0]
                elif point.data_type.value in ("uint32",):
                    data = struct.pack(">I", int(value))
                    store.holding_regs[address] = struct.unpack(">H", data[0:2])[0]
                    store.holding_regs[address + 1] = struct.unpack(">H", data[2:4])[0]
                elif point.data_type.value in ("string",):  # FIXED-P0: 添加string类型处理，与TCP对齐
                    encoded = str(value).encode("utf-8")
                    for j in range(0, min(len(encoded), 62), 2):
                        store.holding_regs[address + j // 2] = struct.unpack(">H", encoded[j:j+2].ljust(2, b'\x00'))[0]
                else:
                    store.holding_regs[address] = int(value) & 0xFFFF
            except (ValueError, TypeError) as e:
                logger.warning("Failed to write register %s: %s", point.address, e)
        self._sync_to_pymodbus_context(slave_id, store)

    def _sync_to_pymodbus_context(self, slave_id: int, store: ModbusDataStore) -> None:
        if not self._context:
            return
        try:
            if OLD_API_AVAILABLE:
                slave_ctx = self._context[slave_id]
                if hasattr(slave_ctx, 'get'):
                    for fx_name, store_data in [
                        ('h', store.holding_regs),
                        ('i', store.input_regs),
                        ('c', store.coils),
                        ('d', store.discrete_inputs),
                    ]:
                        block = slave_ctx.get(fx_name)
                        if block and hasattr(block, 'setValues') and store_data:
                            fc = {'h': 3, 'i': 4, 'c': 1, 'd': 2}.get(fx_name, 3)
                            is_bool = fc in (1, 2)
                            for addr in sorted(store_data.keys()):
                                val = bool(store_data[addr]) if is_bool else store_data[addr]
                                try:
                                    block.setValues(fc, addr, [val])
                                except Exception as exc:
                                    logger.debug("pymodbus setValues failed for fc=%d addr=%d: %s", fc, addr, exc)
        except Exception as e:
            logger.debug("Failed to sync to pymodbus context: %s", e)

    def _read_register(self, point: PointConfig, slave_id: int = 1) -> Any | None:
        store = self._get_data_store(slave_id)
        try:
            address = int(point.address)
            dt = point.data_type.value
            if dt in ("bool",):
                return bool(store.coils.get(address, 0))
            elif dt in ("float32",):  # FIXED-P1: 添加float32/int32/uint32/string支持，与TCP对齐
                regs = [store.holding_regs.get(address + i, 0) for i in range(2)]
                return struct.unpack(">f", struct.pack(">HH", *regs))[0]
            elif dt in ("float64",):
                regs = [store.holding_regs.get(address + i, 0) for i in range(4)]
                return struct.unpack(">d", struct.pack(">HHHH", *regs))[0]
            elif dt in ("int32",):
                regs = [store.holding_regs.get(address + i, 0) for i in range(2)]
                return struct.unpack(">i", struct.pack(">HH", *regs))[0]
            elif dt in ("uint32",):
                regs = [store.holding_regs.get(address + i, 0) for i in range(2)]
                return struct.unpack(">I", struct.pack(">HH", *regs))[0]
            elif dt in ("int16",):
                raw = store.holding_regs.get(address, 0)
                return struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]
            elif dt in ("string",):
                result = bytearray()
                for i in range(32):
                    w = store.holding_regs.get(address + i, 0)
                    result += struct.pack(">H", w)
                    if w & 0xFF == 0:
                        break
                return result.rstrip(b'\x00').decode("utf-8", errors="replace")
            else:
                return store.holding_regs.get(address, 0)
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("Failed to read register %s: %s", point.address, e)
            return None
