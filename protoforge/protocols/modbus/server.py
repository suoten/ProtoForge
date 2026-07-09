"""MODBUS protocol server implementation."""

import asyncio
import contextlib
import logging
import struct
import time
from collections.abc import Callable
from typing import Any

from protoforge.core.messages import desc, msg  # FIXED: i18n消息常量
from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.modbus._common import ModbusDataStore, ModbusDeviceBehavior, parse_modbus_address

logger = logging.getLogger(__name__)

SIMDATA_AVAILABLE = False
try:
    from pymodbus.simulator import DataType, SimData, SimDevice
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
with contextlib.suppress(ImportError):
    from pymodbus.server import StartAsyncTcpServer


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

    def _build_sim_devices(self) -> list[Any]:
        devices = []
        all_slave_ids = set(self._slave_map.values())
        if not all_slave_ids:
            all_slave_ids = {1}

        for slave_id in all_slave_ids:
            store = self._get_data_store(slave_id)
            # FIXED-M09: 根据实际数据范围动态确定初始化大小，而非硬编码0-99
            max_coil = max((k for k in store.coils), default=99) + 1
            max_di = max((k for k in store.discrete_inputs), default=99) + 1
            max_hr = max((k for k in store.holding_regs), default=99) + 1
            max_ir = max((k for k in store.input_regs), default=99) + 1
            simdata = [
                SimData(1, values=[store.coils.get(i, 0) for i in range(0, max(100, max_coil))], datatype=DataType.BITS),
                SimData(10001, values=[store.discrete_inputs.get(i, 0) for i in range(0, max(100, max_di))], datatype=DataType.BITS),
                SimData(40001, values=[store.holding_regs.get(i, 0) for i in range(0, max(100, max_hr))], datatype=DataType.REGISTERS),
                SimData(30001, values=[store.input_regs.get(i, 0) for i in range(0, max(100, max_ir))], datatype=DataType.REGISTERS),
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
                if length < 1 or length > 253:  # FIXED-N01: MBAP length域范围1-253(Modbus规范)，防止恶意帧导致异常读取
                    continue
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

    # Modbus 异常码
    _EX_ILLEGAL_FUNCTION = 0x01
    _EX_ILLEGAL_DATA_ADDRESS = 0x02
    _EX_ILLEGAL_DATA_VALUE = 0x03

    _FC_NAMES: dict[int, str] = {
        0x01: "Read Coils", 0x02: "Read Discrete Inputs",
        0x03: "Read Holding Registers", 0x04: "Read Input Registers",
        0x05: "Write Single Coil", 0x06: "Write Single Register",
        0x0F: "Write Multiple Coils", 0x10: "Write Multiple Registers",
        0x16: "Mask Write Register", 0x17: "Read/Write Multiple Registers",
    }

    def _err_response(self, fc: int, code: int) -> bytes:
        """生成 Modbus 异常响应帧。

        :param fc: 功能码
        :param code: 异常码 (0x01=非法功能, 0x02=非法地址, 0x03=非法数据值)
        :return: 异常响应字节
        """
        return bytes([fc | 0x80, code])

    def _read_bits(
        self, fc: int, data: bytes, store: ModbusDataStore,
        getter: Callable[[int], int], max_count: int, slave_id: int, fc_name: str,
    ) -> bytes:
        """处理读位操作 (FC01/FC02)。

        :param fc: 功能码 (0x01 或 0x02)
        :param data: PDU 数据部分
        :param store: Modbus 数据存储
        :param getter: 取位值的回调 (get_coil 或 get_discrete_input)
        :param max_count: 最大读取数量
        :param slave_id: 从站 ID (用于日志)
        :param fc_name: 功能码名称 (用于日志)
        :return: 响应 PDU
        """
        if len(data) < 4:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        start = struct.unpack(">H", data[0:2])[0]
        count = struct.unpack(">H", data[2:4])[0]
        if count == 0 or count > max_count:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                        detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
        byte_count = (count + 7) // 8
        bits = bytearray(byte_count)
        for i in range(count):
            if getter(start + i):
                bits[i // 8] |= (1 << (i % 8))
        return bytes([fc, byte_count]) + bytes(bits)

    def _read_regs(
        self, fc: int, data: bytes, store: ModbusDataStore,
        area: int, max_count: int, slave_id: int, fc_name: str,
    ) -> bytes:
        """处理读寄存器操作 (FC03/FC04)。

        :param fc: 功能码 (0x03 或 0x04)
        :param data: PDU 数据部分
        :param store: Modbus 数据存储
        :param area: 数据区 (3=holding, 4=input)
        :param max_count: 最大读取数量
        :param slave_id: 从站 ID (用于日志)
        :param fc_name: 功能码名称 (用于日志)
        :return: 响应 PDU
        """
        if len(data) < 4:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        start = struct.unpack(">H", data[0:2])[0]
        count = struct.unpack(">H", data[2:4])[0]
        if count == 0 or count > max_count:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        self._log_debug("inbound", "modbus_read", f"{fc_name}: addr={start} count={count}",
                        detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
        byte_count = count * 2
        regs = bytearray(byte_count)
        for i in range(count):
            val = store.get_point(area, start + i)
            regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
        return bytes([fc, byte_count]) + bytes(regs)

    def _write_single(
        self, fc: int, data: bytes, target_stores: list[ModbusDataStore],
        is_broadcast: bool, slave_id: int, fc_name: str,
    ) -> bytes | None:
        """处理写单个操作 (FC05/FC06)。

        :param fc: 功能码 (0x05 或 0x06)
        :param data: PDU 数据部分
        :param target_stores: 目标数据存储列表
        :param is_broadcast: 是否广播请求
        :param slave_id: 从站 ID (用于日志)
        :param fc_name: 功能码名称 (用于日志)
        :return: 响应 PDU 或 None (广播)
        """
        if len(data) < 4:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        start = struct.unpack(">H", data[0:2])[0]
        val = struct.unpack(">H", data[2:4])[0]
        if fc == 0x05 and val not in (0xFF00, 0x0000):
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        for s in target_stores:
            if fc == 0x05:
                s.set_coil(start, 1 if val == 0xFF00 else 0)
            else:
                s.set_point(6, start, val)
        self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} val={val}",
                        detail={"fc": fc, "start": start, "value": val, "unit": slave_id})
        return None if is_broadcast else (bytes([fc]) + data[0:4])

    def _write_multiple_coils(
        self, fc: int, data: bytes, target_stores: list[ModbusDataStore],
        is_broadcast: bool, slave_id: int, fc_name: str,
    ) -> bytes | None:
        """处理写多个线圈 (FC0F)。

        :param fc: 功能码 (0x0F)
        :param data: PDU 数据部分
        :param target_stores: 目标数据存储列表
        :param is_broadcast: 是否广播请求
        :param slave_id: 从站 ID (用于日志)
        :param fc_name: 功能码名称 (用于日志)
        :return: 响应 PDU 或 None (广播)
        """
        if len(data) < 5:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        start = struct.unpack(">H", data[0:2])[0]
        count = struct.unpack(">H", data[2:4])[0]
        byte_count = data[4]
        if count == 0 or count > 1968:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        expected_bytes = (count + 7) // 8
        if byte_count != expected_bytes:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        for s in target_stores:
            for i in range(count):
                byte_idx = 5 + i // 8
                bit_idx = i % 8
                if byte_idx < len(data):
                    s.set_coil(start + i, 1 if data[byte_idx] & (1 << bit_idx) else 0)
        self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} count={count}",
                        detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
        return None if is_broadcast else (bytes([fc]) + data[0:4])

    def _write_multiple_regs(
        self, fc: int, data: bytes, target_stores: list[ModbusDataStore],
        is_broadcast: bool, slave_id: int, fc_name: str,
    ) -> bytes | None:
        """处理写多个寄存器 (FC10)。

        :param fc: 功能码 (0x10)
        :param data: PDU 数据部分
        :param target_stores: 目标数据存储列表
        :param is_broadcast: 是否广播请求
        :param slave_id: 从站 ID (用于日志)
        :param fc_name: 功能码名称 (用于日志)
        :return: 响应 PDU 或 None (广播)
        """
        if len(data) < 5:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        start = struct.unpack(">H", data[0:2])[0]
        count = struct.unpack(">H", data[2:4])[0]
        byte_count = data[4]
        if count == 0 or count > 123:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        if byte_count != count * 2:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        for s in target_stores:
            for i in range(count):
                offset = 5 + i * 2
                if offset + 2 <= len(data):
                    val = struct.unpack(">H", data[offset:offset + 2])[0]
                    s.set_point(16, start + i, val)
        self._log_debug("inbound", "modbus_write", f"{fc_name}: addr={start} count={count}",
                        detail={"fc": fc, "start": start, "count": count, "unit": slave_id})
        return None if is_broadcast else (bytes([fc]) + data[0:4])

    def _mask_write_reg(
        self, fc: int, data: bytes, target_stores: list[ModbusDataStore],
        is_broadcast: bool, slave_id: int,
    ) -> bytes | None:
        """处理掩码写寄存器 (FC16)。

        :param fc: 功能码 (0x16)
        :param data: PDU 数据部分
        :param target_stores: 目标数据存储列表
        :param is_broadcast: 是否广播请求
        :param slave_id: 从站 ID (用于日志)
        :return: 响应 PDU 或 None (广播)
        """
        if len(data) < 6:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        addr = struct.unpack(">H", data[0:2])[0]
        and_mask = struct.unpack(">H", data[2:4])[0]
        or_mask = struct.unpack(">H", data[4:6])[0]
        for s in target_stores:
            current = s.get_point(3, addr)
            new_val = (current & and_mask) | (or_mask & ~and_mask)
            new_val &= 0xFFFF
            s.set_point(6, addr, new_val)
        self._log_debug("inbound", "modbus_write",
                        f"MaskWrite: addr={addr} and={and_mask:#06x} or={or_mask:#06x}",
                        detail={"fc": fc, "addr": addr, "unit": slave_id})
        return None if is_broadcast else (bytes([fc]) + data[0:6])

    def _read_write_multiple(
        self, fc: int, data: bytes, store: ModbusDataStore,
        target_stores: list[ModbusDataStore], is_broadcast: bool, slave_id: int,
    ) -> bytes | None:
        """处理读写多个寄存器 (FC17)。

        :param fc: 功能码 (0x17)
        :param data: PDU 数据部分
        :param store: 主数据存储 (用于读取)
        :param target_stores: 目标数据存储列表 (用于写入)
        :param is_broadcast: 是否广播请求
        :param slave_id: 从站 ID (用于日志)
        :return: 响应 PDU 或 None (广播)
        """
        if len(data) < 9:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        r_start = struct.unpack(">H", data[0:2])[0]
        r_count = struct.unpack(">H", data[2:4])[0]
        w_start = struct.unpack(">H", data[4:6])[0]
        w_count = struct.unpack(">H", data[6:8])[0]
        if r_count == 0 or r_count > self._MAX_READ_REGISTERS or w_count == 0 or w_count > 121:
            return self._err_response(fc, self._EX_ILLEGAL_DATA_VALUE)
        for s in target_stores:
            for i in range(w_count):
                offset = 9 + i * 2
                if offset + 2 <= len(data):
                    val = struct.unpack(">H", data[offset:offset + 2])[0]
                    s.set_point(6, w_start + i, val)
        if is_broadcast:
            return None
        r_byte_count = r_count * 2
        regs = bytearray(r_byte_count)
        for i in range(r_count):
            val = store.get_point(3, r_start + i)
            regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
        self._log_debug("inbound", "modbus_rw",
                        f"ReadWriteMultiple: r={r_start}/{r_count} w={w_start}/{w_count}",
                        detail={"fc": fc, "r_start": r_start, "w_start": w_start, "unit": slave_id})
        return bytes([fc, r_byte_count]) + bytes(regs)

    def _process_modbus_frame(self, unit_id: int, fc: int, data: bytes) -> bytes | None:
        """处理 Modbus PDU 帧，根据功能码分派到对应处理器。

        支持 FC01-FC06, FC0F, FC10, FC16, FC17 共 10 种功能码。
        广播请求 (unit_id=0) 对读操作不返回响应，对写操作遍历所有从站。

        :param unit_id: MBAP Unit ID (0=广播, 1-247=从站)
        :param fc: 功能码
        :param data: PDU 数据部分 (不含功能码)
        :return: 响应 PDU 字节，或 None (广播/无需响应)
        """
        is_broadcast = (unit_id == 0)
        slave_id = unit_id if unit_id else 1
        fc_name = self._FC_NAMES.get(fc, f"FC{fc:02X}")

        # 广播读操作不返回响应
        if is_broadcast and fc in (0x01, 0x02, 0x03, 0x04):
            return None

        # 广播写入时遍历所有从站
        target_stores = list(self._data_stores.values()) if is_broadcast else [self._get_data_store(slave_id)]
        if not target_stores:
            return None
        store = target_stores[0]

        try:
            if fc == 0x01:
                return self._read_bits(fc, data, store, store.get_coil, self._MAX_READ_COILS, slave_id, fc_name)
            elif fc == 0x02:
                return self._read_bits(fc, data, store, store.get_discrete_input, self._MAX_READ_COILS, slave_id, fc_name)
            elif fc == 0x03:
                return self._read_regs(fc, data, store, 3, self._MAX_READ_REGISTERS, slave_id, fc_name)
            elif fc == 0x04:
                return self._read_regs(fc, data, store, 4, self._MAX_READ_REGISTERS, slave_id, fc_name)
            elif fc in (0x05, 0x06):
                return self._write_single(fc, data, target_stores, is_broadcast, slave_id, fc_name)
            elif fc == 0x0F:
                return self._write_multiple_coils(fc, data, target_stores, is_broadcast, slave_id, fc_name)
            elif fc == 0x10:
                return self._write_multiple_regs(fc, data, target_stores, is_broadcast, slave_id, fc_name)
            elif fc == 0x16:
                return self._mask_write_reg(fc, data, target_stores, is_broadcast, slave_id)
            elif fc == 0x17:
                return self._read_write_multiple(fc, data, store, target_stores, is_broadcast, slave_id)
            else:
                return self._err_response(fc, self._EX_ILLEGAL_FUNCTION)
        except (IndexError, struct.error):
            return self._err_response(fc, self._EX_ILLEGAL_DATA_ADDRESS)

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

        # 检查点位是否存在且可写
        config = self._device_configs.get(device_id)
        if config:
            point = next((p for p in config.points if p.name == point_name), None)
            if point is None:
                logger.warning("Modbus write_point: point '%s' not found on device %s", point_name, device_id)
                return False
            if point.access not in ("w", "rw"):
                logger.warning("Modbus write_point: point '%s' is read-only on device %s", point_name, device_id)
                return False

        # 更新协议层 behavior 内部状态
        success = behavior.on_write(point_name, value)
        if success:
            # 将写入值同步到 Modbus 数据存储（holding registers / coils）
            self._apply_device_to_context(
                self._device_configs.get(device_id, DeviceConfig(id=device_id, name="", protocol="modbus_tcp"))
            )
            # 通过 on_write 回调传播到 DeviceInstance，确保内部状态一致
            if self._on_write:
                try:
                    await self._on_write(device_id, point_name, value)
                except Exception as e:
                    logger.warning("Modbus write_point: on_write callback error for %s.%s: %s", device_id, point_name, e)
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
            try:
                addr, area = parse_modbus_address(point.address)
                if area == "coil":
                    store.coils[addr] = int(bool(value))
                elif area == "discrete":
                    store.discrete_inputs[addr] = int(bool(value))
                elif area == "input":
                    if point.data_type.value in ("float32",):
                        data = struct.pack(">f", float(value))
                        store.input_regs[addr] = struct.unpack(">H", data[0:2])[0]
                        store.input_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
                    else:
                        store.input_regs[addr] = int(value) & 0xFFFF
                else:  # holding or auto
                    if point.data_type.value in ("bool",):
                        store.coils[addr] = int(bool(value))
                    elif point.data_type.value in ("float32",):
                        data = struct.pack(">f", float(value))
                        store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                        store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
                    elif point.data_type.value in ("float64",):
                        data = struct.pack(">d", float(value))
                        for j in range(4):
                            store.holding_regs[addr + j] = struct.unpack(">H", data[j * 2:j * 2 + 2])[0]
                    elif point.data_type.value in ("int32",):
                        data = struct.pack(">i", int(value))
                        store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                        store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
                    elif point.data_type.value in ("uint32",):
                        data = struct.pack(">I", int(value))
                        store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                        store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
                    elif point.data_type.value in ("string",):
                        encoded = str(value).encode("utf-8")
                        if len(encoded) % 2:
                            encoded += b'\x00'
                        for j in range(0, len(encoded), 2):
                            word = encoded[j:j + 2]
                            store.holding_regs[addr + j // 2] = struct.unpack(">H", word)[0]
                    else:
                        store.holding_regs[addr] = int(value) & 0xFFFF
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
            address, area = parse_modbus_address(point.address)
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
