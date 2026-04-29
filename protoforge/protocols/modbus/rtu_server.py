import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

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


class ModbusRtuDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0

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


class _ModbusDataStore:
    """兼容 pymodbus 3.x 新旧 API 的数据存储层"""

    def __init__(self):
        self._coils: dict[int, int] = {}
        self._discrete_inputs: dict[int, int] = {}
        self._holding_regs: dict[int, int] = {}
        self._input_regs: dict[int, int] = {}

    def set_values(self, fc: int, address: int, values: list) -> None:
        for i, v in enumerate(values):
            addr = address + i
            if fc in (1, 5, 15):  # coils
                self._coils[addr] = int(bool(v))
            elif fc == 2:  # discrete inputs
                self._discrete_inputs[addr] = int(bool(v))
            elif fc in (3, 6, 16, 22, 23):  # holding registers
                self._holding_regs[addr] = int(v) & 0xFFFF
            elif fc == 4:  # input registers
                self._input_regs[addr] = int(v) & 0xFFFF

    def get_values(self, fc: int, address: int, count: int = 1) -> list:
        result = []
        for i in range(count):
            addr = address + i
            if fc in (1, 5, 15):
                result.append(self._coils.get(addr, 0))
            elif fc == 2:
                result.append(self._discrete_inputs.get(addr, 0))
            elif fc in (3, 6, 16, 22, 23):
                result.append(self._holding_regs.get(addr, 0))
            elif fc == 4:
                result.append(self._input_regs.get(addr, 0))
        return result


class ModbusRtuServer(ProtocolServer):
    protocol_name = "modbus_rtu"
    protocol_display_name = "Modbus RTU"

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: Any = None
        self._behaviors: dict[str, ModbusRtuDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._port = "COM1"
        self._baudrate = 9600
        self._parity = "N"
        self._stopbits = 1
        self._bytesize = 8
        self._slave_map: dict[str, int] = {}
        self._next_slave_id = 1
        self._data_stores: dict[int, _ModbusDataStore] = {}
        self._use_simdata = SIMDATA_AVAILABLE

    def _get_data_store(self, slave_id: int) -> _ModbusDataStore:
        if slave_id not in self._data_stores:
            self._data_stores[slave_id] = _ModbusDataStore()
        return self._data_stores[slave_id]

    def _build_sim_devices(self) -> list:
        devices = []
        all_slave_ids = set(self._slave_map.values())
        if not all_slave_ids:
            all_slave_ids = {1}

        for slave_id in all_slave_ids:
            store = self._get_data_store(slave_id)
            simdata = [
                SimData(1, values=[store._coils.get(i, 0) for i in range(1, 101)], datatype=DataType.BITS),
                SimData(10001, values=[store._discrete_inputs.get(i, 0) for i in range(1, 101)], datatype=DataType.BITS),
                SimData(40001, values=[store._holding_regs.get(i, 0) for i in range(1, 101)], datatype=DataType.REGISTERS),
                SimData(30001, values=[store._input_regs.get(i, 0) for i in range(1, 101)], datatype=DataType.REGISTERS),
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
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

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
        behavior = ModbusRtuDeviceBehavior(device_config.points)
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
                    if self._context is not None:
                        try:
                            if hasattr(self._context, 'slave'):
                                self._context.slave(slave_id, device_context)
                            elif hasattr(self._context, '_devices'):
                                self._context._devices[slave_id] = device_context
                            elif hasattr(self._context, '_slaves'):
                                self._context._slaves[slave_id] = device_context
                        except Exception as e:
                            logger.warning("Failed to add slave %d to context: %s", slave_id, e)
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
        success = await behavior.on_write(point_name, value)
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
                    store._coils[address] = int(bool(value))
                else:
                    store._holding_regs[address] = int(value) & 0xFFFF
            except (ValueError, TypeError) as e:
                logger.warning("Failed to write register %s: %s", point.address, e)
        self._sync_to_pymodbus_context(slave_id, store)

    def _sync_to_pymodbus_context(self, slave_id: int, store: _ModbusDataStore) -> None:
        if not self._context:
            return
        try:
            if OLD_API_AVAILABLE:
                slave_ctx = self._context[slave_id]
                if hasattr(slave_ctx, 'get'):
                    for fx_name, store_data in [
                        ('h', store._holding_regs),
                        ('i', store._input_regs),
                        ('c', store._coils),
                        ('d', store._discrete_inputs),
                    ]:
                        block = slave_ctx.get(fx_name)
                        if block and hasattr(block, 'setValues') and store_data:
                            addresses = sorted(store_data.keys())
                            if addresses:
                                values = [store_data.get(a, 0) for a in addresses]
                                fc = {'h': 3, 'i': 4, 'c': 1, 'd': 2}.get(fx_name, 3)
                                try:
                                    block.setValues(fc, addresses, values)
                                except Exception:
                                    pass
        except Exception as e:
            logger.debug("Failed to sync to pymodbus context: %s", e)

    def _read_register(self, point: PointConfig, slave_id: int = 1) -> Any | None:
        store = self._get_data_store(slave_id)
        try:
            address = int(point.address) + 1
            if point.data_type.value in ("bool",):
                return bool(store._coils.get(address, 0))
            else:
                return store._holding_regs.get(address, 0)
        except (ValueError, TypeError) as e:
            logger.warning("Failed to read register %s: %s", point.address, e)
            return None
