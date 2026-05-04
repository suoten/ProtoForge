import asyncio
import time
from typing import Any, Optional

from protoforge.core.generator import DataGenerator
from protoforge.models.device import DeviceConfig, DeviceStatus, GeneratorType, PointConfig, PointValue


class DeviceInstance:
    def __init__(self, config: DeviceConfig, generator: DataGenerator):
        self.config = config
        self._generator = generator
        self._status: DeviceStatus = DeviceStatus.OFFLINE
        self._point_values: dict[str, Any] = {}
        self._point_configs: dict[str, PointConfig] = {}
        self._start_time: Optional[float] = None
        self._lock = asyncio.Lock()

        for point in config.points:
            self._point_configs[point.name] = point
            if point.fixed_value is not None:
                self._point_values[point.name] = point.fixed_value
            else:
                self._point_values[point.name] = self._generator.generate(point)

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def protocol(self) -> str:
        return self.config.protocol

    @property
    def points(self) -> list[PointConfig]:
        return self.config.points

    @property
    def protocol_config(self) -> dict[str, Any]:
        return self.config.protocol_config

    @property
    def status(self) -> DeviceStatus:
        return self._status

    def start(self) -> None:
        self._status = DeviceStatus.ONLINE
        self._start_time = time.time()

    def stop(self) -> None:
        self._status = DeviceStatus.OFFLINE
        self._start_time = None

    async def tick(self) -> None:
        if self._status != DeviceStatus.ONLINE:
            return
        async with self._lock:
            for name, point in self._point_configs.items():
                if point.generator_type != GeneratorType.FIXED:
                    self._point_values[name] = self._generator.generate(point)

    def read_point(self, point_name: str) -> Optional[PointValue]:
        if point_name not in self._point_values:
            return None
        quality = "good"
        if self._status != DeviceStatus.ONLINE:
            quality = "uncertain"
        return PointValue(
            name=point_name,
            value=self._point_values.get(point_name),
            timestamp=time.time(),
            quality=quality,
        )

    def read_all_points(self) -> list[PointValue]:
        result = []
        now = time.time()
        for name, value in list(self._point_values.items()):
            result.append(
                PointValue(
                    name=name,
                    value=value,
                    timestamp=now,
                )
            )
        return result

    async def write_point(self, point_name: str, value: Any) -> bool:
        if point_name not in self._point_configs:
            return False
        point = self._point_configs[point_name]
        if point.access == "r":
            return False
        if point.min_value is not None and point.max_value is not None:
            try:
                num_val = float(value)
                if num_val < point.min_value or num_val > point.max_value:
                    logger.warning(
                        "Write value %s out of range [%s, %s] for point %s",
                        value, point.min_value, point.max_value, point_name,
                    )
            except (ValueError, TypeError):
                pass
        async with self._lock:
            self._point_values[point_name] = value
        return True
