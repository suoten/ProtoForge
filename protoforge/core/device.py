import time
from typing import Any, Callable, Optional

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
        # 可选的 tick 后处理钩子，由外部模块（如 FaultInjector）注册
        self._post_tick_hooks: list[Callable[["DeviceInstance"], None]] = []

        for point in config.points:
            self._point_configs[point.name] = point
            if point.fixed_value is not None:
                self._point_values[point.name] = point.fixed_value
            else:
                self._point_values[point.name] = self._generator.generate(point)

    def register_post_tick_hook(self, hook: Callable[["DeviceInstance"], None]) -> None:
        """注册 tick 后处理钩子，外部模块通过此接口介入，不修改 tick 逻辑本身"""
        if hook not in self._post_tick_hooks:
            self._post_tick_hooks.append(hook)

    def unregister_post_tick_hook(self, hook: Callable[["DeviceInstance"], None]) -> None:
        self._post_tick_hooks = [h for h in self._post_tick_hooks if h != hook]

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
        # 执行后处理钩子（故障注入等外部模块在此覆盖测点值）
        for hook in self._post_tick_hooks:
            try:
                hook(self)
            except Exception:
                pass

    def read_point(self, point_name: str) -> Optional[PointValue]:
        if point_name not in self._point_values:
            return None
        return PointValue(
            name=point_name,
            value=self._point_values[point_name],
            timestamp=time.time(),
            quality="good" if self._status == DeviceStatus.ONLINE else "bad",
        )

    def read_all_points(self) -> list[PointValue]:
        quality = "good" if self._status == DeviceStatus.ONLINE else "bad"
        result = []
        now = time.time()
        for name in self._point_values:
            result.append(
                PointValue(
                    name=name,
                    value=self._point_values[name],
                    timestamp=now,
                    quality=quality,
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
