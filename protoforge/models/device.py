"""Module: device."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DataType(str, Enum):
    BOOL = "bool"
    INT16 = "int16"
    INT32 = "int32"
    UINT16 = "uint16"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING = "string"


# ---------------------------------------------------------------------------
#  写入值归一（FIXED: 布尔量读写异常 — UI 显示 true/11 而协议寄存器为 0/1）
# ---------------------------------------------------------------------------

_BOOL_TRUE_STRINGS = ("true", "1", "on", "yes")
_BOOL_FALSE_STRINGS = ("false", "0", "off", "no", "", "none", "null")


def normalize_point_value(data_type: "DataType | str", value: Any) -> Any:
    """按点位 data_type 归一写入值，不可表示时抛 ValueError。

    背景（用户实测 bug）：UI 快速写入 bool 点位 11 → UI 显示 11、线圈却是 1；
    向 uint16 点位写字符串 "true" → int("true") 转换失败被静默吞掉，
    原始字符串入库（UI 显示 true、寄存器保持 0），界面值与协议线上的值不一致。

    归一规则：
    - bool:       True/False 原样；数字 → 非零为 True（与 Modbus 线圈语义一致）；
                  字符串 "true"/"1"/"on"/"yes" → True，"false"/"0"/"off"/"no" → False，
                  其余字符串抛 ValueError（此前会静默变成 False）
    - float32/64: 转换为 float，非数值抛 ValueError
    - int16/32:   转换为 int 并钳制到有符号范围
    - uint16/32:  转换为 int 并钳制到无符号范围
    - string:     转换为 str
    - 其他类型:   原样返回

    :param data_type: 点位数据类型（DataType 枚举或字符串）
    :param value: 待归一的写入值
    :return: 归一后的值（保证与协议寄存器编码一致）
    :raises ValueError: 值无法用该数据类型表示时
    """
    dt = data_type.value if isinstance(data_type, DataType) else str(data_type)

    if dt == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in _BOOL_TRUE_STRINGS:
                return True
            if v in _BOOL_FALSE_STRINGS:
                return False
        raise ValueError(
            f"Cannot represent {value!r} as bool (use true/false, 1/0, on/off, yes/no)"
        )

    if dt in ("float32", "float64"):
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Cannot represent {value!r} as {dt}") from None
        if num != num or num in (float("inf"), float("-inf")):
            raise ValueError(f"Invalid float value: {value!r}")
        return num

    if dt in ("int16", "int32", "uint16", "uint32"):
        try:
            num = int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"Cannot represent {value!r} as {dt}") from None
        if dt == "int16":
            return max(-32768, min(32767, num))
        if dt == "uint16":
            return max(0, min(65535, num))
        if dt == "int32":
            return max(-2147483648, min(2147483647, num))
        return max(0, min(4294967295, num))

    if dt == "string":
        return str(value)

    return value


class GeneratorType(str, Enum):
    FIXED = "fixed"
    CONSTANT = "constant"
    RANDOM = "random"
    RANDOM_WALK = "random_walk"
    SINE = "sine"
    TRIANGLE = "triangle"
    SAWTOOTH = "sawtooth"
    SQUARE = "square"
    INCREMENT = "increment"
    SCRIPT = "script"
    PHYSICAL = "physical"


class PointConfig(BaseModel):
    # FIXED: 支持 access_mode 别名，前端发送 access_mode 但后端字段名为 access
    # populate_by_name=True 允许同时使用 access 和 access_mode
    model_config = {"populate_by_name": True}

    name: str
    address: str
    data_type: DataType = DataType.FLOAT32
    unit: str = ""
    description: str = ""
    access: Literal["r", "w", "rw"] = Field(default="rw", validation_alias="access_mode")

    generator_type: GeneratorType = GeneratorType.FIXED
    generator_config: dict[str, Any] = Field(default_factory=dict)

    min_value: float | None = None
    max_value: float | None = None
    fixed_value: Any | None = None
    deadband: float = 0.0

    @model_validator(mode="after")
    def validate_min_max(self):
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"min_value ({self.min_value}) must be <= max_value ({self.max_value}) for point '{self.name}'")
        return self


class DeviceConfig(BaseModel):
    id: str
    name: str
    protocol: str
    template_id: str | None = None
    points: list[PointConfig] = Field(default_factory=list)
    protocol_config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] | None = None


class PointValue(BaseModel):
    name: str
    value: Any
    timestamp: float = 0.0
    quality: str = "good"
    quality_code: int | None = None  # OPC UA StatusCode (32-bit)，None 表示未计算
    simulated: bool = False


class DeviceStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    ERROR = "error"
    STARTING = "starting"


class DeviceInfo(BaseModel):
    id: str
    name: str
    protocol: str
    template_id: str | None = None
    status: DeviceStatus = DeviceStatus.OFFLINE
    points: list[PointValue] = Field(default_factory=list)
    created_at: str | None = None
    protocol_config: dict[str, Any] | None = None
    edgelite_status: dict[str, Any] | None = None
    protocol_active: bool = True
