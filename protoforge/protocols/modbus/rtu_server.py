import asyncio
import logging
import struct
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

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: Any = None
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._port = "COM1"
        self._baudrate = 9600
        self._parity = "N"
        self._stopbits = 1
        self._bytesize = 8
        self._slave_map: dict[str, int] = {}
        self._next_slave_id = 1
        self._data_stores: dict[int, ModbusDataStore] = {}
        self._use_simdata = SIMDATA_AVAILABLE

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
        self._port = config.get("port", "COM1")
        self._baudrate = config.get("baudrate", 9600)
        self._parity = config.get("parity", "N")
        self._stopbits = config.get("stopbits", 1)
        self._bytesize = config.get("bytesize", 8)

        if not StartAsyncSerialServer:
            raise RuntimeError("pymodbus is not installed. Install with: pip install protoforge[modbus]")

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
                self._server_task = asyncio.create_task(
                    self._serve_datastore_only()
                )

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus RTU server starting on %s @ %d (simdata=%s)", self._port, self._baudrate, self._use_simdata)
            self._log_debug("system", "server_start",
                            f"Modbus RTU服务启动 {self._port} @ {self._baudrate}",
                            detail={"port": self._port, "baudrate": self._baudrate, "simdata": self._use_simdata})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Modbus RTU server: %s", e)
            raise

    async def _serve_datastore_only(self) -> None:
        tcp_port = 5021
        logger.info("Modbus RTU running in TCP bridge mode on port %d (pymodbus serial unavailable)", tcp_port)
        try:
            server = await asyncio.start_server(
                self._handle_native_modbus_rtu, "0.0.0.0", tcp_port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Modbus RTU TCP bridge server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_native_modbus_rtu(self, reader: asyncio.StreamReader,
                                          writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                header = await reader.readexactly(7)
                tx_id = struct.unpack(">H", header[0:2])[0]
                proto_id = struct.unpack(">H", header[2:4])[0]
                length = struct.unpack(">H", header[4:6])[0]
                unit_id = header[6]
                if length > 0:
                    payload = await reader.readexactly(length - 1)
                else:
                    payload = b""
                fc = payload[0] if payload else 0
                resp = self._process_modbus_frame(unit_id, fc, payload[1:])
                mbap = struct.pack(">HHHB", tx_id, proto_id, len(resp) + 1, unit_id)
                writer.write(mbap + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_modbus_frame(self, unit_id: int, fc: int, data: bytes) -> bytes:
        slave_id = unit_id if unit_id else 1
        store = self._data_stores.get(slave_id)
        if not store:
            store = self._get_data_store(slave_id)
        try:
            if fc == 0x01:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_coil(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x02:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_discrete_input(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x03:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(3, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x04:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(4, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x05:
                start = struct.unpack(">H", data[0:2])[0] + 1
                val = struct.unpack(">H", data[2:4])[0]
                store.set_coil(start, 1 if val == 0xFF00 else 0)
                return bytes([fc]) + data[0:4]
            elif fc == 0x06:
                start = struct.unpack(">H", data[0:2])[0] + 1
                val = struct.unpack(">H", data[2:4])[0]
                store.set_point(6, start, val)
                return bytes([fc]) + data[0:4]
            elif fc == 0x0F:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                for i in range(count):
                    byte_idx = 5 + i // 8
                    bit_idx = i % 8
                    if byte_idx < len(data):
                        store.set_coil(start + i, 1 if data[byte_idx] & (1 << bit_idx) else 0)
                return bytes([fc]) + data[0:4]
            elif fc == 0x10:
                start = struct.unpack(">H", data[0:2])[0] + 1
                count = struct.unpack(">H", data[2:4])[0]
                for i in range(count):
                    offset = 5 + i * 2
                    if offset + 2 <= len(data):
                        val = struct.unpack(">H", data[offset:offset + 2])[0]
                        store.set_point(16, start + i, val)
                return bytes([fc]) + data[0:4]
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
                    pass
                except Exception as e:
                    logger.warning("Modbus RTU server task error: %s", e)
        except Exception as e:
            logger.warning("Modbus RTU server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Modbus RTU server stopped")
            self._log_debug("system", "server_stop", "Modbus RTU服务停止")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        slave_id = proto_config.get("slave_id", self._next_slave_id)
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
                        f"Modbus RTU设备创建: {device_config.name} (slave_id={slave_id})",
                        device_id=device_config.id,
                        detail={"slave_id": slave_id, "points": len(device_config.points)})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        slave_id = self._slave_map.pop(device_id, None)
        if slave_id is not None:
            self._data_stores.pop(slave_id, None)
        self._clear_default_device(device_id)
        logger.info("Modbus RTU device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除Modbus RTU设备 {device_id}",
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
                "port": {"type": "string", "default": "COM1", "description": "串口设备路径 (如 COM1 或 /dev/ttyUSB0)"},
                "baudrate": {"type": "integer", "default": 9600, "description": "波特率"},
                "parity": {"type": "string", "default": "N", "description": "校验位 (N/E/O)"},
                "stopbits": {"type": "integer", "default": 1, "description": "停止位"},
                "bytesize": {"type": "integer", "default": 8, "description": "数据位"},
            },
        }

    def _apply_device_to_context(self, config: DeviceConfig) -> None:
        behavior = self._behaviors.get(config.id)
        slave_id = self._slave_map.get(config.id, 1)
        store = self._get_data_store(slave_id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            address = int(point.address) + 1
            try:
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
            address = int(point.address) + 1
            if point.data_type.value in ("bool",):
                return bool(store.coils.get(address, 0))
            else:
                return store.holding_regs.get(address, 0)
        except (ValueError, TypeError) as e:
            logger.warning("Failed to read register %s: %s", point.address, e)
            return None
