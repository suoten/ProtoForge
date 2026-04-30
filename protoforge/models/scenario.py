from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from protoforge.models.device import DeviceConfig


class ScenarioStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class RuleType(str, Enum):
    THRESHOLD = "threshold"
    VALUE_CHANGE = "value_change"
    TIMER = "timer"
    SCRIPT = "script"


class Rule(BaseModel):
    id: str
    name: str
    rule_type: RuleType = RuleType.THRESHOLD
    source_device_id: str
    source_point: str
    condition: dict[str, Any] = Field(default_factory=dict)
    target_device_id: str | None = None
    target_point: str | None = None
    target_value: Any | None = None
    enabled: bool = True


class ScenarioConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    devices: list[DeviceConfig] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)


class ScenarioConfigUpdate(BaseModel):
    id: str | None = None
    name: str | None = None
    description: str | None = None
    devices: list[DeviceConfig] | None = None
    rules: list[Rule] | None = None


class ScenarioInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    status: ScenarioStatus = ScenarioStatus.STOPPED
    device_count: int = 0
    rule_count: int = 0
    created_at: str | None = None


class ScenarioDetail(ScenarioInfo):
    devices: list[DeviceConfig] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
