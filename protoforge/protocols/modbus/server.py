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

from pymodbus.server import StartAsyncTcpServer


class ModbusDeviceBehavior(DeviceBehavior):
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


class ModbusTcpServer(ProtocolServer):
    protocol_name = "modbus_tcp"
    protocol_display_name = "Modbus TCP"

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: Any = None
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 5020
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
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5020)

        try:
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
                    StartAsyncTcpServer(context=self._context, address=(self._host, self._port))
                )
            else:
                logger.warning("Neither SimData nor old API available, Modbus TCP server starting in data-store-only mode")
                self._server_task = asyncio.create_task(
                    self._serve_datastore_only()
                )

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus TCP server starting on %s:%d (simdata=%s)", self._host, self._port, self._use_simdata)
            self._log_debug("system", "server_start",
                            f"Modbus TCP服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port, "simdata": self._use_simdata})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Modbus TCP server: %s", e)
            raise

    async def stop(self) -> None:
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Modbus TCP server task error: %s", e)
        self._status = ProtocolStatus.STOPPED
        logger.info("Modbus TCP server stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config

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
            await self._apply_device_to_context(device_config)

        logger.info("Modbus device created: %s (slave_id=%d)", device_config.id, slave_id)
        self._log_debug("system", "device_created",
                        f"Modbus设备创建: {device_config.name} (slave_id={slave_id})",
                        device_id=device_config.id,
                        detail={"slave_id": slave_id, "points": len(device_config.points)})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("Modbus device removed: %s", device_id)

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
            await self._apply_device_to_context(
                self._device_configs.get(device_id, DeviceConfig(id=device_id, name="", protocol="modbus_tcp"))
            )
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址"},
                "port": {"type": "integer", "default": 5020, "description": "监听端口"},
            },
        }

    async def _apply_device_to_context(self, config: DeviceConfig) -> None:
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

    async def _read_register(self, point: PointConfig, slave_id: int = 1) -> Any | None:
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
