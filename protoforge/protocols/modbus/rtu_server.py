import asyncio
import logging
import time
from typing import Any

from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import StartAsyncSerialServer

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


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


class ModbusRtuServer(ProtocolServer):
    protocol_name = "modbus_rtu"
    protocol_display_name = "Modbus RTU"

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: ModbusServerContext | None = None
        self._behaviors: dict[str, ModbusRtuDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._port = "COM1"
        self._baudrate = 9600
        self._parity = "N"
        self._stopbits = 1
        self._bytesize = 8

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._port = config.get("port", "COM1")
        self._baudrate = config.get("baudrate", 9600)
        self._parity = config.get("parity", "N")
        self._stopbits = config.get("stopbits", 1)
        self._bytesize = config.get("bytesize", 8)

        try:
            holding_registers = ModbusSequentialDataBlock(1, [0] * 100)
            input_registers = ModbusSequentialDataBlock(1, [0] * 100)
            coils = ModbusSequentialDataBlock(1, [False] * 100)
            discrete_inputs = ModbusSequentialDataBlock(1, [False] * 100)

            device_context = ModbusDeviceContext(
                hr=holding_registers,
                ir=input_registers,
                co=coils,
                di=discrete_inputs,
            )
            self._context = ModbusServerContext(devices=device_context, single=True)

            for device_config in self._device_configs.values():
                self._apply_device_to_context(device_config)

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus RTU server starting on %s @ %d", self._port, self._baudrate)

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
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Modbus RTU server: %s", e)
            raise

    async def stop(self) -> None:
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Modbus RTU server task error: %s", e)
        self._status = ProtocolStatus.STOPPED
        logger.info("Modbus RTU server stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusRtuDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config

        if self._status == ProtocolStatus.RUNNING:
            self._apply_device_to_context(device_config)

        logger.info("Modbus RTU device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("Modbus RTU device removed: %s", device_id)

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
        if not self._context:
            return
        behavior = self._behaviors.get(config.id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            self._write_register(point, value)

    def _write_register(self, point: PointConfig, value: Any) -> None:
        if not self._context:
            return
        try:
            address = int(point.address) + 1
            if point.data_type.value in ("bool",):
                self._context[0x01].setValues(1, address, [int(bool(value))])
            else:
                self._context[0x01].setValues(3, address, [int(value)])
        except (ValueError, IndexError, KeyError) as e:
            logger.warning("Failed to write register %s: %s", point.address, e)
