from typing import Any

from protoforge.models.device import PointConfig
from protoforge.protocols.base import DeviceBehavior


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


class ModbusDataStore:
    def __init__(self):
        self._coils: dict[int, int] = {}
        self._discrete_inputs: dict[int, int] = {}
        self._holding_regs: dict[int, int] = {}
        self._input_regs: dict[int, int] = {}

    @property
    def coils(self) -> dict[int, int]:
        return self._coils

    @property
    def discrete_inputs(self) -> dict[int, int]:
        return self._discrete_inputs

    @property
    def holding_regs(self) -> dict[int, int]:
        return self._holding_regs

    @property
    def input_regs(self) -> dict[int, int]:
        return self._input_regs

    def set_point(self, fc: int, address: int, value: int) -> None:
        if fc in (1, 5, 15):
            self._coils[address] = int(bool(value))
        elif fc == 2:
            self._discrete_inputs[address] = int(bool(value))
        elif fc in (3, 6, 16, 22, 23):
            self._holding_regs[address] = int(value) & 0xFFFF
        elif fc == 4:
            self._input_regs[address] = int(value) & 0xFFFF

    def get_point(self, fc: int, address: int) -> int:
        if fc in (1, 5, 15):
            return self._coils.get(address, 0)
        elif fc == 2:
            return self._discrete_inputs.get(address, 0)
        elif fc in (3, 6, 16, 22, 23):
            return self._holding_regs.get(address, 0)
        elif fc == 4:
            return self._input_regs.get(address, 0)
        return 0

    def set_values(self, fc: int, address: int, values: list) -> None:
        for i, v in enumerate(values):
            addr = address + i
            if fc in (1, 5, 15):
                self._coils[addr] = int(bool(v))
            elif fc == 2:
                self._discrete_inputs[addr] = int(bool(v))
            elif fc in (3, 6, 16, 22, 23):
                self._holding_regs[addr] = int(v) & 0xFFFF
            elif fc == 4:
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
