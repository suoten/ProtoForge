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
    name: str
    address: str
    data_type: DataType = DataType.FLOAT32
    unit: str = ""
    description: str = ""
    access: Literal["r", "w", "rw"] = "rw"

    generator_type: GeneratorType = GeneratorType.FIXED
    generator_config: dict[str, Any] = Field(default_factory=dict)

    min_value: float | None = None
    max_value: float | None = None
    fixed_value: Any | None = None

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
