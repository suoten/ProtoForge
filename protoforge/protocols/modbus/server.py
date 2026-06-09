import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.modbus._common import ModbusDeviceBehavior, ModbusDataStore
from protoforge.core.messages import msg, desc  # FIXED: i18n消息常量

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

StartAsyncTcpServer = None
try:
    from pymodbus.server import StartAsyncTcpServer
except ImportError:
    pass


class ModbusTcpServer(ProtocolServer):
    protocol_name = "modbus_tcp"
    protocol_display_name = "Modbus TCP"

    _MAX_READ_COILS = 2000  # FIXED-P0: Modbus规范FC01/02最多读2000个位(原值125与_MAX_READ_REGISTERS互反)
    _MAX_READ_REGISTERS = 125  # FIXED-P0: Modbus规范FC03/04最多读125个寄存器(原值2000与_MAX_READ_COILS互反)

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: Any = None
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 5020
        self._requested_port = 5020
        self._slave_map: dict[str, int] = {}
        self._next_slave_id = 1
        self._data_stores: dict[int, ModbusDataStore] = {}
        self._use_simdata = SIMDATA_AVAILABLE
        self._server_running = False  # FIXED-P0: _handle_native_modbus引用此属性但未初始化

    @property
    def actual_port(self) -> int:
        """返回协议服务器实际监听的端口"""
        return self._port

    @property
    def requested_port(self) -> int:
        """返回用户配置的端口"""
        return self._requested_port

    def _on_server_task_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Modbus TCP server task failed: %s", e)
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
                SimData(1, values=[store.coils.get(i, 0) for i in range(0, 100)], datatype=DataType.BITS),
                SimData(10001, values=[store.discrete_inputs.get(i, 0) for i in range(0, 100)], datatype=DataType.BITS),
                SimData(40001, values=[store.holding_regs.get(i, 0) for i in range(0, 100)], datatype=DataType.REGISTERS),
                SimData(30001, values=[store.input_regs.get(i, 0) for i in range(0, 100)], datatype=DataType.REGISTERS),
            ]
            devices.append(SimDevice(slave_id, simdata=simdata))
        return devices

    async def _serve_datastore_only(self) -> None:
        logger.info("Modbus TCP running in native frame mode (pymodbus SimData/OldAPI unavailable)")
        try:
            server = await asyncio.start_server(
                self._handle_native_modbus, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("Modbus server task cancelled")
        except Exception as e:
            logger.error("Modbus native frame server error: %s", e)
            self._status = ProtocolStatus.ERROR

    _CONN_TIMEOUT = 30  # FIXED: 连接读取超时秒数，防止Slowloris攻击

    async def _handle_native_modbus(self, reader: asyncio.StreamReader,
                                     writer: asyncio.StreamWriter) -> None:
        try:
            while self._server_running:
                header = await asyncio.wait_for(reader.readexactly(7), timeout=self._CONN_TIMEOUT)  # FIXED: 添加读取超时
                tx_id = struct.unpack(">H", header[0:2])[0]
                proto_id = struct.unpack(">H", header[2:4])[0]
                if proto_id != 0:  # FIXED-P2: MBAP Protocol ID必须为0(Modbus规范)
                    continue
                length = struct.unpack(">H", header[4:6])[0]
                unit_id = header[6]
                if length > 0:
                    payload = await asyncio.wait_for(reader.readexactly(length - 1), timeout=self._CONN_TIMEOUT)  # FIXED: 添加读取超时
                else:
                    payload = b""
                fc = payload[0] if payload else 0
                resp = self._process_modbus_frame(unit_id, fc, payload[1:])
                if resp is None:
                    continue
                mbap = struct.pack(">HHHB", tx_id, proto_id, len(resp) + 1, unit_id)
                writer.write(mbap + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError, asyncio.TimeoutError, BrokenPipeError, ConnectionAbortedError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Modbus TCP writer close error: %s", e)

    def _process_modbus_frame(self, unit_id: int, fc: int, data: bytes) -> bytes | None:
        is_broadcast = (unit_id == 0)
        slave_id = unit_id if unit_id else 1
        fc_names = {0x01: "Read Coils", 0x02: "Read Discrete Inputs", 0x03: "Read Holding Registers",
                    0x04: "Read Input Registers", 0x05: "Write Single Coil", 0x06: "Write Single Register",
                    0x0F: "Write Multiple Coils", 0x10: "Write Multiple Registers"}
        fc_name = fc_names.get(fc, f"FC{fc:02X}")
        if is_broadcast and fc in (0x01, 0x02, 0x03, 0x04):
            return None
        # 广播写入时遍历所有从站
        target_stores = list(self._data_stores.values()) if is_broadcast else [self._get_data_store(slave_id)]
        store = target_stores[0]  # 用于读取和日志
        try:
            if fc == 0x01:
                if len(data) < 4:  # FIXED-P1: 前置长度校验，数据不足返回Illegal Data Value(0x03)而非被外层捕获返回0x02
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移，Modbus spec地址从0开始
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_COILS:  # FIXED-P0: FC01读线圈应检查_MAX_READ_COILS(2000)；FIXED-P2: count==0校验
                    return bytes([fc | 0x80, 0x03])
                self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_coil(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x02:
                if len(data) < 4:  # FIXED-P1: 前置长度校验
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移，Modbus spec地址从0开始
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_COILS:  # FIXED-P0: FC02读离散输入应检查_MAX_READ_COILS(2000)；FIXED-P2: count==0校验
                    return bytes([fc | 0x80, 0x03])
                self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_discrete_input(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x03:
                if len(data) < 4:  # FIXED-P0: 前置长度校验，数据不足时返回Illegal Data Value(0x03)
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移，Modbus spec定义地址从0开始
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_REGISTERS:  # FIXED-P0: FC0x03应检查_MAX_READ_REGISTERS(2000)而非_MAX_READ_COILS(125)；FIXED-P2: count==0校验
                    return bytes([fc | 0x80, 0x03])
                self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(3, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x04:
                if len(data) < 4:  # FIXED-P0: 前置长度校验
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_REGISTERS:  # FIXED-P0: FC0x04应检查_MAX_READ_REGISTERS(2000)而非_MAX_READ_COILS(125)；FIXED-P2: count==0校验
                    return bytes([fc | 0x80, 0x03])
                self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(4, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x05:
                if len(data) < 4:
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                if val not in (0xFF00, 0x0000):  # FIXED-P2: FC05值校验，非0xFF00/0x0000返回异常码0x03
                    return bytes([fc | 0x80, 0x03])
                for s in target_stores:
                    s.set_coil(start, 1 if val == 0xFF00 else 0)
                self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} val={val}",
                                detail={"fc": fc, "start": start, "value": val, "unit": slave_id})
                return None if is_broadcast else (bytes([fc]) + data[0:4])
            elif fc == 0x06:
                if len(data) < 4:
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                for s in target_stores:
                    s.set_point(6, start, val)
                self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} val={val}",
                                detail={"fc": fc, "start": start, "value": val, "unit": slave_id})
                return None if is_broadcast else (bytes([fc]) + data[0:4])
            elif fc == 0x0F:
                if len(data) < 5:  # FIXED-P0: 前置长度校验(需start+count+byte_count=5字节)
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = data[4]
                if count == 0 or count > 1968:  # FIXED-P2: count==0校验；FC0F最多写1968个线圈
                    return bytes([fc | 0x80, 0x03])
                expected_bytes = (count + 7) // 8
                if byte_count != expected_bytes:  # FIXED-P2: byte_count与count一致性校验
                    return bytes([fc | 0x80, 0x03])
                for s in target_stores:
                    for i in range(count):
                        byte_idx = 5 + i // 8
                        bit_idx = i % 8
                        if byte_idx < len(data):
                            s.set_coil(start + i, 1 if data[byte_idx] & (1 << bit_idx) else 0)
                self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                return None if is_broadcast else (bytes([fc]) + data[0:4])
            elif fc == 0x10:
                if len(data) < 5:
                    return bytes([fc | 0x80, 0x03])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = data[4]
                if count == 0 or count > 123:  # FIXED-P2: count==0校验；FC10最多写123个寄存器(规范要求)
                    return bytes([fc | 0x80, 0x03])
                if byte_count != count * 2:  # FIXED-P2: byte_count与count一致性校验
                    return bytes([fc | 0x80, 0x03])
                for s in target_stores:
                    for i in range(count):
                        offset = 5 + i * 2
                        if offset + 2 <= len(data):
                            val = struct.unpack(">H", data[offset:offset + 2])[0]
                            s.set_point(16, start + i, val)
                self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} count={count}",
                                detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
                return None if is_broadcast else (bytes([fc]) + data[0:4])
            elif fc == 0x16:
                if len(data) < 6:  # FIXED-P0: 前置长度校验(需addr+and_mask+or_mask=6字节)
                    return bytes([fc | 0x80, 0x03])
                addr = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                and_mask = struct.unpack(">H", data[2:4])[0]
                or_mask = struct.unpack(">H", data[4:6])[0]
                for s in target_stores:
                    current = s.get_point(3, addr)
                    new_val = (current & and_mask) | (or_mask & ~and_mask)
                    new_val &= 0xFFFF
                    s.set_point(6, addr, new_val)
                self._log_debug("inbound", "modbus_write", f"MaskWrite: addr={addr} and={and_mask:#06x} or={or_mask:#06x}",
                                detail={"fc": fc, "addr": addr, "unit": slave_id})
                return None if is_broadcast else (bytes([fc]) + data[0:6])
            elif fc == 0x17:
                if len(data) < 9:  # FIXED-P0: 前置长度校验(需r_start+r_count+w_start+w_count+w_byte_count=9字节)
                    return bytes([fc | 0x80, 0x03])
                r_start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                r_count = struct.unpack(">H", data[2:4])[0]
                w_start = struct.unpack(">H", data[4:6])[0]  # FIXED-P0: 移除+1偏移
                w_count = struct.unpack(">H", data[6:8])[0]
                if r_count > self._MAX_READ_REGISTERS or w_count > 121:  # FIXED-P0: 统一用_MAX_READ_REGISTERS
                    return bytes([fc | 0x80, 0x03])
                w_byte_count = data[8]
                for s in target_stores:
                    for i in range(w_count):
                        offset = 9 + i * 2
                        if offset + 2 <= len(data):
                            val = struct.unpack(">H", data[offset:offset + 2])[0]
                            s.set_point(6, w_start + i, val)
                if is_broadcast:  # FIXED-P1: 广播请求不应返回响应
                    return None
                r_byte_count = r_count * 2
                regs = bytearray(r_byte_count)
                for i in range(r_count):
                    val = store.get_point(3, r_start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                self._log_debug("inbound", "modbus_rw", f"ReadWriteMultiple: r={r_start}/{r_count} w={w_start}/{w_count}",
                                detail={"fc": fc, "r_start": r_start, "w_start": w_start, "unit": slave_id})
                return bytes([fc, r_byte_count]) + bytes(regs)
            else:
                return bytes([fc | 0x80, 0x01])
        except (IndexError, struct.error):
            return bytes([fc | 0x80, 0x02])

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._requested_port = config.get("port", 5020)
        self._validate_port(self._requested_port)
        self._port = self._requested_port

        if not StartAsyncTcpServer:
            raise RuntimeError("pymodbus is not installed. Install with: pip install pymodbus")

        try:
            self._server_running = True  # FIXED-P0: native模式需要此标志
            if self._use_simdata:
                devices = self._build_sim_devices()
                self._server_task = asyncio.create_task(
                    StartAsyncTcpServer(context=devices, address=(self._host, self._port))
                )
            elif OLD_API_AVAILABLE:
                slaves_dict = {}
                for device_config in self._device_configs.values():
                    slave_id = self._slave_map.get(device_config.id, self._next_slave_id)
                    if device_config.id not in self._slave_map:
                        self._slave_map[device_config.id] = slave_id
                        self._next_slave_id = max(self._next_slave_id, slave_id + 1)
                    slaves_dict[slave_id] = ModbusDeviceContext(
                        hr=ModbusSequentialDataBlock(0, [0] * 100),
                        ir=ModbusSequentialDataBlock(0, [0] * 100),
                        co=ModbusSequentialDataBlock(0, [False] * 100),
                        di=ModbusSequentialDataBlock(0, [False] * 100),
                    )
                if not slaves_dict:
                    slaves_dict[1] = ModbusDeviceContext(
                        hr=ModbusSequentialDataBlock(0, [0] * 100),
                        ir=ModbusSequentialDataBlock(0, [0] * 100),
                        co=ModbusSequentialDataBlock(0, [False] * 100),
                        di=ModbusSequentialDataBlock(0, [False] * 100),
                    )
                self._context = ModbusServerContext(devices=slaves_dict, single=False)
                self._server_task = asyncio.create_task(
                    StartAsyncTcpServer(context=self._context, address=(self._host, self._port))
                )
            else:
                logger.warning("Neither SimData nor old API available, Modbus TCP server starting in data-store-only mode")
                self._server_task = asyncio.create_task(
                    self._serve_datastore_only()
                )

            if self._server_task:
                self._server_task.add_done_callback(self._on_server_task_done)

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus TCP server starting on %s:%d (simdata=%s)", self._host, self._port, self._use_simdata)
            self._log_debug("system", "server_start",
                            msg("modbus_tcp", "service_started", host=self._host, port=self._port),  # FIXED: 中文硬编码→i18n常量
                            detail={"host": self._host, "port": self._port, "simdata": self._use_simdata})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Modbus TCP server: %s", e)
            raise

    async def stop(self) -> None:
        self._server_running = False  # FIXED-P0: 停止native模式循环
        try:
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("Modbus TCP task cancelled")
                except Exception as e:
                    logger.warning("Modbus TCP server task error: %s", e)
        except Exception as e:
            logger.warning("Modbus TCP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Modbus TCP server stopped")
            self._log_debug("system", "server_stop", msg("modbus_tcp", "service_stopped"))  # FIXED: 中文硬编码→i18n常量

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
                        hr=ModbusSequentialDataBlock(0, [0] * 100),
                        ir=ModbusSequentialDataBlock(0, [0] * 100),
                        co=ModbusSequentialDataBlock(0, [False] * 100),
                        di=ModbusSequentialDataBlock(0, [False] * 100),
                    )
                    self._add_slave_to_context(slave_id, device_context)
                except Exception as e:
                    logger.warning("Failed to create ModbusDeviceContext: %s", e)
            self._apply_device_to_context(device_config)

        logger.info("Modbus device created: %s (slave_id=%d)", device_config.id, slave_id)
        self._log_debug("system", "device_created",
                        msg("modbus_tcp", "device_created", name=device_config.name),  # FIXED: 中文硬编码→i18n常量
                        device_id=device_config.id,
                        detail={"slave_id": slave_id, "points": len(device_config.points)})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:  # FIXED: 添加锁保护
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
            slave_id = self._slave_map.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock保护，防止与_process_modbus_frame并发
            if slave_id is not None:
                self._data_stores.pop(slave_id, None)
        await self._clear_default_device_async(device_id)  # FIXED: 使用异步锁版本
        logger.info("Modbus device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        msg("modbus_tcp", "device_removed", id=device_id),  # FIXED: 中文硬编码→i18n常量
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
                self._device_configs.get(device_id, DeviceConfig(id=device_id, name="", protocol="modbus_tcp"))
            )
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address")},  # FIXED: 中文硬编码→i18n常量
                "port": {"type": "integer", "default": 5020, "description": desc("listen_port")},  # FIXED: 中文硬编码→i18n常量
            },
        }

    def _apply_device_to_context(self, config: DeviceConfig) -> None:
        behavior = self._behaviors.get(config.id)
        slave_id = self._slave_map.get(config.id, 1)
        store = self._get_data_store(slave_id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            try:  # FIXED-P0: int(point.address)移入try内，非数字地址时跳过该点而非崩溃；移除+1偏移
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
                elif point.data_type.value in ("string",):
                    encoded = str(value).encode("utf-8")
                    if len(encoded) % 2:
                        encoded += b'\x00'
                    for j in range(0, len(encoded), 2):
                        word = encoded[j:j + 2]
                        store.holding_regs[address + j // 2] = struct.unpack(">H", word)[0]
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
            address = int(point.address)  # FIXED-P0: 移除+1偏移
            dt = point.data_type.value
            if dt in ("bool",):
                return bool(store.coils.get(address, 0))
            elif dt in ("float32",):
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
            elif dt in ("uint16",):
                return store.holding_regs.get(address, 0)
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
