import asyncio
import logging
import time
from typing import Any

from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import StartAsyncTcpServer

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


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


class ModbusTcpServer(ProtocolServer):
    protocol_name = "modbus_tcp"
    protocol_display_name = "Modbus TCP"

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._context: ModbusServerContext | None = None
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 5020

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5020)

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
                await self._apply_device_to_context(device_config)

            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus TCP server starting on %s:%d", self._host, self._port)

            self._server_task = asyncio.create_task(
                StartAsyncTcpServer(
                    context=self._context,
                    address=(self._host, self._port),
                )
            )
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

        if self._status == ProtocolStatus.RUNNING:
            await self._apply_device_to_context(device_config)

        logger.info("Modbus device created: %s", device_config.id)
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
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": "监听地址",
                },
                "port": {
                    "type": "integer",
                    "default": 5020,
                    "description": "监听端口",
                },
            },
        }

    async def _apply_device_to_context(self, config: DeviceConfig) -> None:
        if not self._context:
            return
        behavior = self._behaviors.get(config.id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            await self._write_register(point, value)

    async def _write_register(self, point: PointConfig, value: Any) -> None:
        if not self._context:
            return
        try:
            address = int(point.address) + 1
            if point.data_type.value in ("bool",):
                await self._context.async_setValues(0x01, 1, address, [int(bool(value))])
            else:
                await self._context.async_setValues(0x01, 3, address, [int(value)])
        except (ValueError, IndexError, KeyError, TypeError) as e:
            logger.warning("Failed to write register %s: %s", point.address, e)

    async def _read_register(self, point: PointConfig) -> Any | None:
        if not self._context:
            return None
        try:
            address = int(point.address) + 1
            if point.data_type.value in ("bool",):
                values = await self._context.async_getValues(0x01, 1, address, 1)
                return bool(values[0])
            else:
                values = await self._context.async_getValues(0x01, 3, address, 1)
                return values[0]
        except (ValueError, IndexError, KeyError, TypeError) as e:
            logger.warning("Failed to read register %s: %s", point.address, e)
            return None
