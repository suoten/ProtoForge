from typing import Any

from protoforge.models.device import PointConfig
from protoforge.protocols.behavior import DefaultDeviceBehavior


class ModbusDeviceBehavior(DefaultDeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        super().__init__(points)


class ModbusDataStore:
    def __init__(self):
        self._coils: dict[int, bool] = {}
        self._discrete_inputs: dict[int, bool] = {}
        self._holding_regs: dict[int, int] = {}
        self._input_regs: dict[int, int] = {}

    @property
    def coils(self) -> dict[int, int]:
        return {k: int(v) for k, v in self._coils.items()}

    @property
    def discrete_inputs(self) -> dict[int, int]:
        return {k: int(v) for k, v in self._discrete_inputs.items()}

    @property
    def holding_regs(self) -> dict[int, int]:
        return self._holding_regs

    @property
    def input_regs(self) -> dict[int, int]:
        return self._input_regs

    def set_coil(self, address: int, value: Any) -> None:
        self._coils[address] = bool(value)

    def get_coil(self, address: int) -> int:
        return int(self._coils.get(address, False))

    def set_discrete_input(self, address: int, value: Any) -> None:
        self._discrete_inputs[address] = bool(value)

    def get_discrete_input(self, address: int) -> int:
        return int(self._discrete_inputs.get(address, False))

    def set_point(self, fc: int, address: int, value: int) -> None:
        if fc in (1, 5, 15):
            self._coils[address] = bool(value)
        elif fc == 2:
            self._discrete_inputs[address] = bool(value)
        elif fc in (3, 6, 16, 22, 23):
            self._holding_regs[address] = int(value) & 0xFFFF
        elif fc == 4:
            self._input_regs[address] = int(value) & 0xFFFF

    def get_point(self, fc: int, address: int) -> int:
        if fc in (1, 5, 15):
            return int(self._coils.get(address, False))
        elif fc == 2:
            return int(self._discrete_inputs.get(address, False))
        elif fc in (3, 6, 16, 22, 23):
            return self._holding_regs.get(address, 0)
        elif fc == 4:
            return self._input_regs.get(address, 0)
        return 0

    def set_values(self, fc: int, address: int, values: list) -> None:
        for i, v in enumerate(values):
            addr = address + i
            if fc in (1, 5, 15):
                self._coils[addr] = bool(v)
            elif fc == 2:
                self._discrete_inputs[addr] = bool(v)
            elif fc in (3, 6, 16, 22, 23):
                self._holding_regs[addr] = int(v) & 0xFFFF
            elif fc == 4:
                self._input_regs[addr] = int(v) & 0xFFFF

    def get_values(self, fc: int, address: int, count: int = 1) -> list:
        result = []
        for i in range(count):
            addr = address + i
            if fc in (1, 5, 15):
                result.append(int(self._coils.get(addr, False)))
            elif fc == 2:
                result.append(int(self._discrete_inputs.get(addr, False)))
            elif fc in (3, 6, 16, 22, 23):
                result.append(self._holding_regs.get(addr, 0))
            elif fc == 4:
                result.append(self._input_regs.get(addr, 0))
        return result
