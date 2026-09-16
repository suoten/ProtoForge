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
        "40001"      → (0, "holding")      5-digit PLC notation (40001-49999)
        "30001"      → (0, "input")        5-digit PLC notation (30001-39999)
        "10001"      → (0, "discrete")     5-digit PLC notation (10001-19999)
        "00001"      → (0, "coil")         5-digit PLC notation (00001-09999)

    :param address: 地址字符串
    :return: (偏移地址, 区域类型) 元组
    :raises ValueError: 地址格式无效
    """
    if not address:
        raise ValueError("Empty address")
    addr_str = str(address).strip().upper().replace(' ', '')

    # 5-digit PLC address notation: 40001-49999, 30001-39999, 10001-19999, 00001-09999
    if len(addr_str) == 5 and addr_str.isdigit():
        addr_num = int(addr_str)
        if 40001 <= addr_num <= 49999:
            return addr_num - 40001, "holding"  # 40001 → address 0
        elif 30001 <= addr_num <= 39999:
            return addr_num - 30001, "input"
        elif 10001 <= addr_num <= 19999:
            return addr_num - 10001, "discrete"
        elif 1 <= addr_num <= 9999:  # 00001-09999 (leading zeros)
            return addr_num - 1, "coil"
        # 5-digit numbers outside standard ranges (e.g. 50000-99999) fall through

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
        raise ValueError(f"Invalid Modbus address: {address}") from None


def point_area(point: PointConfig) -> str:
    """解析点位的 Modbus 存储区类型。

    auto 区域按数据类型自动判定（与 server 写入存储规则一致）：
    bool → 线圈区 (coil)，其他 → 保持寄存器区 (holding)。

    :param point: 点位配置
    :return: "coil" / "discrete" / "input" / "holding"
    """
    _, area = parse_modbus_address(point.address)
    if area == "auto":
        area = "coil" if point.data_type.value == "bool" else "holding"
    return area


def point_reg_count(point: PointConfig) -> int:
    """返回点位占用的寄存器/线圈数（用于地址范围匹配）。"""
    dt = point.data_type.value
    if dt in ("bool", "int16", "uint16"):
        return 1
    elif dt in ("float32", "int32", "uint32"):
        return 2
    elif dt in ("float64",):
        return 4
    elif dt in ("string",):
        return 32
    return 1


# 外部写入功能码 → 写目标存储区映射（TCP/RTU 共用，用于 access 只读校验）
WRITE_FC_AREA_MAP: dict[int, str] = {
    0x05: "coil", 0x06: "holding", 0x0F: "coil",
    0x10: "holding", 0x16: "holding", 0x17: "holding",
}

# 存储区中文名（用于重叠冲突提示）
_AREA_CN_LABELS: dict[str, str] = {
    "coil": "线圈区(0区)",
    "discrete": "离散输入区(1区)",
    "input": "输入寄存器区(3区)",
    "holding": "保持寄存器区(4区)",
}


def find_overlapping_points(points: list[PointConfig]) -> list[str]:
    """检测同设备内点位地址范围是否重叠（Modbus 协议）。

    背景：FLOAT32/INT32/UINT32 占 2 个寄存器、STRING 占 32 个，配置时极易
    因疏忽与相邻点位重叠（如 FLOAT32@2 与 FLOAT32@3 共用寄存器 3）。
    重叠点位互相覆盖数据：固定值失效、读出乱值、正弦波"串味"，
    且这类问题从界面值上几乎无法排查。

    :param points: 点位配置列表
    :return: 冲突描述列表（人类可读中文），无冲突返回空列表。
             地址无法解析（非 Modbus 语义/格式非法）的点位跳过不参与检测。
    """
    entries: list[tuple[str, str, int, int, int]] = []
    for pt in points:
        try:
            addr = parse_modbus_address(pt.address)[0]
            area = point_area(pt)
        except (ValueError, TypeError):
            continue
        count = point_reg_count(pt)
        entries.append((pt.name, area, addr, addr + count, count))

    conflicts: list[str] = []
    for i in range(len(entries)):
        name1, area1, start1, end1, count1 = entries[i]
        for j in range(i + 1, len(entries)):
            name2, area2, start2, end2, count2 = entries[j]
            if area1 == area2 and start1 < end2 and start2 < end1:
                conflicts.append(
                    f"点位 '{name1}'(地址 {start1}, {_AREA_CN_LABELS[area1]}, 占{count1}个寄存器) 与 "
                    f"'{name2}'(地址 {start2}, {_AREA_CN_LABELS[area2]}, 占{count2}个寄存器) "
                    f"地址范围重叠 [{start1}~{end1 - 1}] 与 [{start2}~{end2 - 1}]"
                )
    return conflicts


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
        try:  # FIXED-P1: int()异常保护，非数字值时回退0
            if fc in (1, 5, 15):
                self._coils[address] = int(bool(value))
            elif fc == 2:
                self._discrete_inputs[address] = int(bool(value))
            elif fc in (3, 6, 16, 22, 23):
                self._holding_regs[address] = int(value) & 0xFFFF  # FIXED-H01: FC=0x16(Mask Write)调用时传入的new_val已在server.py中完成掩码计算，此处&0xFFFF截断为16位寄存器是正确的
            elif fc == 4:
                self._input_regs[address] = int(value) & 0xFFFF
        except (ValueError, TypeError) as e:
            logger.warning("Modbus set_point conversion error for fc=%d addr=%d: %s", fc, address, e)

    def set_32bit_point(self, fc: int, address: int, value: Any, data_type: str = "int32") -> None:
        try:  # FIXED-P1: int()/float()异常保护，非数字值时回退0
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
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("Modbus set_32bit_point conversion error for fc=%d addr=%d type=%s: %s", fc, address, data_type, e)
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
            try:
                if fc in (1, 5, 15):
                    self._coils[addr] = int(bool(v))
                elif fc == 2:
                    self._discrete_inputs[addr] = int(bool(v))
                elif fc in (3, 6, 16, 22, 23):
                    self._holding_regs[addr] = int(v) & 0xFFFF
                elif fc == 4:
                    self._input_regs[addr] = int(v) & 0xFFFF
            except (ValueError, TypeError) as e:
                logger.warning("Modbus set_values conversion error for fc=%d addr=%d: %s", fc, addr, e)

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
