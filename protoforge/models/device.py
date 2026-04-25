from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DataType(str, Enum):
    BOOL = "bool"
    INT16 = "int16"
    INT32 = "int32"
    UINT16 = "uint16"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING = "string"


class GeneratorType(str, Enum):
    FIXED = "fixed"
    RANDOM = "random"
    SINE = "sine"
    TRIANGLE = "triangle"
    SAWTOOTH = "sawtooth"
    SCRIPT = "script"


class PointConfig(BaseModel):
    name: str
    address: str
    data_type: DataType = DataType.FLOAT32
    unit: str = ""
    description: str = ""
    access: str = "rw"

    generator_type: GeneratorType = GeneratorType.FIXED
    generator_config: dict[str, Any] = Field(default_factory=dict)

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    fixed_value: Optional[Any] = None


class DeviceConfig(BaseModel):
    id: str
    name: str
    protocol: str
    template_id: Optional[str] = None
    points: list[PointConfig] = Field(default_factory=list)
    protocol_config: dict[str, Any] = Field(default_factory=dict)


class PointValue(BaseModel):
    name: str
    value: Any
    timestamp: float = 0.0
    quality: str = "good"


class DeviceStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    ERROR = "error"


class DeviceInfo(BaseModel):
    id: str
    name: str
    protocol: str
    template_id: Optional[str] = None
    status: DeviceStatus = DeviceStatus.OFFLINE
    points: list[PointValue] = Field(default_factory=list)
    created_at: Optional[str] = None
