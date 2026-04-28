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

    def tick(self) -> None:
        if self._status != DeviceStatus.ONLINE:
            return
        for name, point in self._point_configs.items():
            if point.generator_type != GeneratorType.FIXED:
                self._point_values[name] = self._generator.generate(point)

    def read_point(self, point_name: str) -> Optional[PointValue]:
        if point_name not in self._point_values:
            return None
        return PointValue(
            name=point_name,
            value=self._point_values[point_name],
            timestamp=time.time(),
        )

    def read_all_points(self) -> list[PointValue]:
        result = []
        now = time.time()
        for name in self._point_values:
            result.append(
                PointValue(
                    name=name,
                    value=self._point_values[name],
                    timestamp=now,
                )
            )
        return result

    def write_point(self, point_name: str, value: Any) -> bool:
        if point_name not in self._point_configs:
            return False
        point = self._point_configs[point_name]
        if point.access == "r":
            return False
        self._point_values[point_name] = value
        return True
