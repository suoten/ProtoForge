from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class FaultMode(str, Enum):
    """故障注入模式"""
    INSTANT = "instant"       # 瞬间跳变到异常值，持续 duration 后恢复
    GRADUAL = "gradual"       # 渐进式劣化，随时间线性恶化，到 duration 时达到峰值后恢复


class FaultStatus(str, Enum):
    ACTIVE = "active"
    RECOVERING = "recovering"
    CLEARED = "cleared"


class PointFaultConfig(BaseModel):
    """单个测点的故障行为定义"""
    point: str
    mode: FaultMode = FaultMode.INSTANT

    # INSTANT 模式：直接设置为 target_value（若为 None 则用 multiplier 乘以当前值）
    target_value: Optional[float] = None
    multiplier: Optional[float] = None     # 异常值 = 当前正常值 × multiplier

    # 目标值范围：注入时在 [target_min, target_max] 内随机采样一个实际目标值
    # 设置后会覆盖 target_value，使每次注入的故障严重程度有所不同
    target_min: Optional[float] = None
    target_max: Optional[float] = None

    # GRADUAL 模式：从当前值线性劣化到 target_value 或 multiplier 倍
    # 劣化程度 = progress(0~1) × (target - baseline)
    noise_scale: float = 0.0               # 叠加随机噪声幅度，模拟真实抖动
    nominal_baseline: Optional[float] = None  # 稳态额定基线，设置后替代注入时采样的瞬时值
                                              # 用于周期性信号（如主轴转速）避免在升/降速段注入时基线失真


class FaultTypeDefinition(BaseModel):
    """故障类型定义，描述一种真实故障场景"""
    id: str
    name: str
    description: str
    category: str                          # 故障分类：mechanical / electrical / thermal / process
    default_duration: float = 120.0        # 默认持续时间（秒）
    point_faults: list[PointFaultConfig] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class FaultInjectRequest(BaseModel):
    """故障注入请求"""
    fault_type_id: str
    duration: Optional[float] = None       # 覆盖默认持续时间，None 表示用类型默认值
    intensity: float = 1.0                 # 故障强度系数 0~1，影响劣化幅度


class ActiveFault(BaseModel):
    """当前激活的故障实例"""
    fault_id: str                          # 唯一实例 ID
    device_id: str
    fault_type_id: str
    fault_type_name: str
    status: FaultStatus = FaultStatus.ACTIVE
    intensity: float = 1.0
    duration: float = 120.0
    started_at: float = 0.0
    cleared_at: Optional[float] = None
    baseline_values: dict[str, float] = Field(default_factory=dict)   # 注入时的正常基线值
    resolved_targets: dict[str, float] = Field(default_factory=dict)  # 注入时随机采样的实际目标值


class FaultInfo(BaseModel):
    """故障状态信息（API 响应用）"""
    fault_id: str
    device_id: str
    fault_type_id: str
    fault_type_name: str
    status: FaultStatus
    intensity: float
    duration: float
    elapsed: float
    progress: float                        # 0~1，故障进度
    affected_points: list[str]
    started_at: float
