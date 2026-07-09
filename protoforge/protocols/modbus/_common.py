"""Shared utilities for MODBUS protocol implementation."""

import logging
import re
import struct
from typing import Any

from protoforge.models.device import PointConfig
from protoforge.protocols.behavior import DefaultDeviceBehavior

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Modbus 地址解析
# ---------------------------------------------------------------------------

_MODBUS_ADDR_PATTERN = re.compile(
    r'^(HR|IR|C|COIL|DI|DISCRETE_INPUT|4X|3X|0X|1X)?\s*0*?(\d+)$',
    re.IGNORECASE,
)


def parse_modbus_address(address: str) -> tuple[int, str]:
    """解析 Modbus 地址字符串，返回 (address_int, area_type)。

    支持的格式::

        "100"        → (100, "auto")       纯数字，自动判断
        "HR100"      → (100, "holding")    Holding Register
        "IR100"      → (100, "input")      Input Register
        "C100"       → (100, "coil")       Coil
        "DI100"      → (100, "discrete")   Discrete Input
        "4x100"      → (100, "holding")    Holding Register (4x notation)
        "3x100"      → (100, "input")      Input Register (3x notation)
        "0x100"      → (100, "coil")       Coil (0x notation)
        "1x100"      → (100, "discrete")   Discrete Input (1x notation)
        "400100"     → (100, "holding")    6-digit PLC notation (400001-499999)
        "300100"     → (100, "input")      6-digit PLC notation (300001-399999)
        "000100"     → (100, "coil")       6-digit PLC notation (000001-099999)
        "100100"     → (100, "discrete")   6-digit PLC notation (100001-199999)

    :param address: 地址字符串
    :return: (偏移地址, 区域类型) 元组
    :raises ValueError: 地址格式无效
    """
    if not address:
        raise ValueError("Empty address")
    addr_str = str(address).strip().upper().replace(' ', '')

    # 6-digit PLC address notation: 4xxxxx, 3xxxxx, 0xxxxx, 1xxxxx
    if len(addr_str) >= 6 and addr_str.isdigit():
        prefix = addr_str[0]
        num = int(addr_str[1:])
        if prefix == '4':
            return num - 1, "holding"  # 400001 → address 0
        elif prefix == '3':
            return num - 1, "input"
        elif prefix == '0':
            return num - 1, "coil"
        elif prefix == '1':
            return num - 1, "discrete"

    # Prefix notation: HR100, IR100, C100, DI100, 4x100, etc.
    m = _MODBUS_ADDR_PATTERN.match(addr_str)
    if m:
        prefix = (m.group(1) or '').upper()
        num = int(m.group(2))
        if prefix in ('HR', '4X'):
            return num, "holding"
        elif prefix in ('IR', '3X'):
            return num, "input"
        elif prefix in ('C', 'COIL', '0X'):
            return num, "coil"
        elif prefix in ('DI', 'DISCRETE_INPUT', '1X'):
            return num, "discrete"
        else:
            return num, "auto"

    # Pure number
    try:
        return int(addr_str), "auto"
    except ValueError:
        raise ValueError(f"Invalid Modbus address: {address}")


class ModbusDeviceBehavior(DefaultDeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        super().__init__(points)


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

    def set_coil(self, address: int, value: Any) -> None:
        self._coils[address] = int(bool(value))

    def get_coil(self, address: int) -> int:
        return self._coils.get(address, 0)

    def set_discrete_input(self, address: int, value: Any) -> None:
        self._discrete_inputs[address] = int(bool(value))

    def get_discrete_input(self, address: int) -> int:
        return self._discrete_inputs.get(address, 0)

    def set_point(self, fc: int, address: int, value: int) -> None:
        if fc in (1, 5, 15):
            self._coils[address] = int(bool(value))
        elif fc == 2:
            self._discrete_inputs[address] = int(bool(value))
        elif fc in (3, 6, 16, 22, 23):
            self._holding_regs[address] = int(value) & 0xFFFF  # FIXED-H01: FC=0x16(Mask Write)调用时传入的new_val已在server.py中完成掩码计算，此处&0xFFFF截断为16位寄存器是正确的
        elif fc == 4:
            self._input_regs[address] = int(value) & 0xFFFF

    def set_32bit_point(self, fc: int, address: int, value: Any, data_type: str = "int32") -> None:
        if data_type == "float32":
            data = struct.pack(">f", float(value))
        elif data_type == "int32":
            data = struct.pack(">i", int(value))
        elif data_type == "uint32":
            data = struct.pack(">I", int(value))
        elif data_type == "float64":
            data = struct.pack(">d", float(value))
        else:
            self.set_point(fc, address, int(value))
            return
        regs = self._holding_regs if fc in (3, 6, 16, 22, 23) else self._input_regs
        for j in range(len(data) // 2):
            regs[address + j] = struct.unpack(">H", data[j * 2:j * 2 + 2])[0]

    def get_point(self, fc: int, address: int) -> int:
        if fc in (1, 5, 15):
            return self._coils.get(address, 0)
        elif fc == 2:
            return self._discrete_inputs.get(address, 0)
        elif fc in (3, 6, 16, 22, 23):
            return self._holding_regs.get(address, 0)
        elif fc == 4:
            return self._input_regs.get(address, 0)
        logger.warning("Modbus get_point called with unknown FC=%d, address=%d", fc, address)  # FIXED-L01: 未知FC记录警告
        return 0

    def set_values(self, fc: int, address: int, values: list[Any]) -> None:
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

    def get_values(self, fc: int, address: int, count: int = 1) -> list[Any]:
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
