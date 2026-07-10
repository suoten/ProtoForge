"""Module: scenario."""

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
    COLLABORATION = "collaboration"  # 多设备协同联动（链式动作）


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
    # 协同规则扩展字段（rule_type == COLLABORATION 时使用）
    actions: list[dict[str, Any]] = Field(default_factory=list)  # 多动作链
    cooldown: float = 0.0  # 规则级冷却（秒），>0 时两次触发间至少间隔该时长


class ScenarioConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    devices: list[DeviceConfig] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    # 时间序列回放配置（"真正的仿真"——历史数据驱动）
    replay_config: dict[str, Any] | None = None  # {"source": ..., "speed": 1.0, "loop": False, "time_field": "ts"}


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
