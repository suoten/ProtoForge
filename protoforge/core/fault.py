"""
故障注入模块 (FaultInjector)

设计原则：
- 完全独立，不修改 device.py / engine.py 现有逻辑
- 通过 apply(device) 在每次 tick 后覆盖测点值，device 本身无感知
- 支持四种场景：异常注入、自动恢复、多指标联动、渐进式劣化
"""
import logging
import random
import time
import uuid
from typing import Any, Optional

from protoforge.models.fault import (
    ActiveFault,
    FaultInfo,
    FaultInjectRequest,
    FaultMode,
    FaultStatus,
    FaultTypeDefinition,
    PointFaultConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内置故障类型定义（基于真实工业场景）
# ---------------------------------------------------------------------------

BUILTIN_FAULT_TYPES: list[FaultTypeDefinition] = [

    # ------------------------------------------------------------------
    # 刀具磨损 — 最常见的机加工故障
    # 特征：切削阻力增大 → 主轴电流缓慢爬升，振动幅度增大，进给速率被系统压低
    # 模式：渐进式，持续数分钟，模拟刀具从轻度磨损到需要换刀的过程
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear",
        name="刀具磨损",
        description="刀具切削刃磨损，切削阻力增大，主轴电流升高，振动增大，进给速率下降",
        category="mechanical",
        default_duration=300.0,
        tags=["刀具", "磨损", "渐进"],
        point_faults=[
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=2.2, noise_scale=0.8),
            PointFaultConfig(point="vibration_x", mode=FaultMode.GRADUAL,
                             multiplier=3.0, noise_scale=0.3),
            PointFaultConfig(point="vibration_y", mode=FaultMode.GRADUAL,
                             multiplier=3.0, noise_scale=0.3),
            PointFaultConfig(point="vibration_z", mode=FaultMode.GRADUAL,
                             multiplier=3.5, noise_scale=0.4),
            PointFaultConfig(point="feed_rate", mode=FaultMode.GRADUAL,
                             multiplier=0.45, noise_scale=20.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具崩刃 — 突发性刀具失效
    # 特征：瞬间冲击 → 振动突增，电流瞬间峰值，进给立即停止
    # 模式：瞬间注入，持续时间短（机床通常会触发报警停机）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_breakage",
        name="刀具崩刃",
        description="刀具突发性崩刃，振动剧烈突增，主轴电流峰值，进给停止",
        category="mechanical",
        default_duration=15.0,
        tags=["刀具", "崩刃", "突发"],
        point_faults=[
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=4.5, noise_scale=2.0),
            PointFaultConfig(point="vibration_x", mode=FaultMode.INSTANT,
                             multiplier=8.0, noise_scale=1.5),
            PointFaultConfig(point="vibration_y", mode=FaultMode.INSTANT,
                             multiplier=8.0, noise_scale=1.5),
            PointFaultConfig(point="vibration_z", mode=FaultMode.INSTANT,
                             multiplier=10.0, noise_scale=2.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴过热 — 长时间高负荷或冷却系统故障
    # 特征：主轴电流持续偏高，转速因热保护逐渐降低
    # 模式：渐进式，持续时间较长
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_overheat",
        name="主轴过热",
        description="主轴长时间高负荷运转或冷却不足，电流持续偏高，转速因热保护下降",
        category="thermal",
        default_duration=240.0,
        tags=["主轴", "过热", "渐进"],
        point_faults=[
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_scale=1.2),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             multiplier=0.6, noise_scale=50.0),
            PointFaultConfig(point="vibration_x", mode=FaultMode.GRADUAL,
                             multiplier=1.5, noise_scale=0.2),
            PointFaultConfig(point="vibration_z", mode=FaultMode.GRADUAL,
                             multiplier=1.5, noise_scale=0.2),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴轴承故障 — 轴承磨损或润滑不足
    # 特征：振动频率特征变化，整体振动幅度升高，电流略升
    # 模式：渐进式
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_bearing_fault",
        name="主轴轴承故障",
        description="主轴轴承磨损或润滑不足，振动幅度持续升高，伴随电流轻微上升",
        category="mechanical",
        default_duration=360.0,
        tags=["主轴", "轴承", "渐进"],
        point_faults=[
            PointFaultConfig(point="vibration_x", mode=FaultMode.GRADUAL,
                             multiplier=4.0, noise_scale=0.5),
            PointFaultConfig(point="vibration_y", mode=FaultMode.GRADUAL,
                             multiplier=4.0, noise_scale=0.5),
            PointFaultConfig(point="vibration_z", mode=FaultMode.GRADUAL,
                             multiplier=5.0, noise_scale=0.8),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.3, noise_scale=0.5),
        ],
    ),

    # ------------------------------------------------------------------
    # 进给堵转 — 工件夹紧松动或切削量过大导致进给卡死
    # 特征：进给速率瞬间降为 0，主轴电流急剧升高
    # 模式：瞬间注入
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="feed_stall",
        name="进给堵转",
        description="进给轴卡死，进给速率降为零，主轴电流急剧升高",
        category="process",
        default_duration=20.0,
        tags=["进给", "堵转", "突发"],
        point_faults=[
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=3.8, noise_scale=1.5),
            PointFaultConfig(point="vibration_z", mode=FaultMode.INSTANT,
                             multiplier=5.0, noise_scale=1.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 振动异常 — 工件装夹松动或共振
    # 特征：三轴振动突然大幅增加，其他指标基本正常
    # 模式：瞬间注入
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="vibration_spike",
        name="振动异常",
        description="工件装夹松动或切削共振，三轴振动突然大幅增加",
        category="mechanical",
        default_duration=60.0,
        tags=["振动", "装夹", "突发"],
        point_faults=[
            PointFaultConfig(point="vibration_x", mode=FaultMode.INSTANT,
                             multiplier=6.0, noise_scale=1.0),
            PointFaultConfig(point="vibration_y", mode=FaultMode.INSTANT,
                             multiplier=6.0, noise_scale=1.0),
            PointFaultConfig(point="vibration_z", mode=FaultMode.INSTANT,
                             multiplier=7.0, noise_scale=1.2),
        ],
    ),

    # ------------------------------------------------------------------
    # 切削液不足 — 冷却润滑失效
    # 特征：热量积累 → 振动缓慢升高，电流缓慢升高，进给略降
    # 模式：渐进式，速度较慢
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="coolant_failure",
        name="切削液不足",
        description="切削液供给不足，冷却润滑失效，热量积累导致振动和电流缓慢升高",
        category="process",
        default_duration=480.0,
        tags=["切削液", "冷却", "渐进"],
        point_faults=[
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.6, noise_scale=0.8),
            PointFaultConfig(point="vibration_x", mode=FaultMode.GRADUAL,
                             multiplier=2.0, noise_scale=0.3),
            PointFaultConfig(point="vibration_y", mode=FaultMode.GRADUAL,
                             multiplier=2.0, noise_scale=0.3),
            PointFaultConfig(point="vibration_z", mode=FaultMode.GRADUAL,
                             multiplier=2.5, noise_scale=0.4),
            PointFaultConfig(point="feed_rate", mode=FaultMode.GRADUAL,
                             multiplier=0.75, noise_scale=15.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 电源波动 — 供电不稳定
    # 特征：主轴转速和进给速率出现随机波动，电流不稳定
    # 模式：瞬间注入（持续期间持续抖动）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="power_fluctuation",
        name="电源波动",
        description="供电电压不稳定，主轴转速和进给速率出现随机波动",
        category="electrical",
        default_duration=90.0,
        tags=["电源", "波动", "突发"],
        point_faults=[
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=300.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=5.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=150.0),
        ],
    ),
]

# 按 id 索引
_FAULT_TYPE_MAP: dict[str, FaultTypeDefinition] = {ft.id: ft for ft in BUILTIN_FAULT_TYPES}


# ---------------------------------------------------------------------------
# FaultInjector
# ---------------------------------------------------------------------------

class FaultInjector:
    """
    故障注入器，完全独立于 DeviceInstance。

    使用方式：
        injector = FaultInjector()
        injector.inject(device, request)   # 注入故障
        injector.apply(device)             # 每次 tick 后调用，覆盖测点值
        injector.clear(device_id)          # 手动清除
    """

    def __init__(self):
        # device_id -> ActiveFault
        self._active: dict[str, ActiveFault] = {}

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def inject(self, device: Any, request: FaultInjectRequest) -> FaultInfo:
        """向设备注入故障，返回故障信息"""
        fault_type = _FAULT_TYPE_MAP.get(request.fault_type_id)
        if not fault_type:
            raise ValueError(f"Unknown fault type: {request.fault_type_id}")

        duration = request.duration if request.duration is not None else fault_type.default_duration

        # 记录注入时各测点的当前基线值
        baseline: dict[str, float] = {}
        for pf in fault_type.point_faults:
            val = device._point_values.get(pf.point)
            if val is not None:
                try:
                    baseline[pf.point] = float(val)
                except (TypeError, ValueError):
                    baseline[pf.point] = 0.0

        fault = ActiveFault(
            fault_id=uuid.uuid4().hex[:12],
            device_id=device.id,
            fault_type_id=fault_type.id,
            fault_type_name=fault_type.name,
            intensity=max(0.0, min(1.0, request.intensity)),
            duration=duration,
            started_at=time.time(),
            baseline_values=baseline,
        )
        self._active[device.id] = fault
        logger.info("Fault injected: device=%s type=%s duration=%.0fs",
                    device.id, fault_type.id, duration)
        return self._to_info(fault, fault_type)

    def apply(self, device: Any) -> None:
        """
        在 device.tick() 之后调用，将故障效果覆盖到 _point_values。
        故障超时后自动清除。
        """
        fault = self._active.get(device.id)
        if not fault:
            return

        now = time.time()
        elapsed = now - fault.started_at

        if elapsed >= fault.duration:
            self._expire(device, fault)
            return

        fault_type = _FAULT_TYPE_MAP.get(fault.fault_type_id)
        if not fault_type:
            return

        # progress: 0.0（刚注入）→ 1.0（达到峰值）
        progress = min(elapsed / fault.duration, 1.0)

        for pf in fault_type.point_faults:
            if pf.point not in device._point_values:
                continue
            baseline = fault.baseline_values.get(pf.point, 0.0)
            if baseline == 0.0:
                # 基线为 0 时用当前值兜底，避免乘法无效
                try:
                    baseline = float(device._point_values[pf.point]) or 1.0
                except (TypeError, ValueError):
                    continue

            device._point_values[pf.point] = self._compute_value(
                pf, baseline, progress, fault.intensity
            )

    def clear(self, device_id: str) -> bool:
        """手动清除故障，不恢复基线（让生成器自然恢复）"""
        if device_id not in self._active:
            return False
        fault = self._active.pop(device_id)
        fault.status = FaultStatus.CLEARED
        fault.cleared_at = time.time()
        logger.info("Fault cleared manually: device=%s type=%s", device_id, fault.fault_type_id)
        return True

    def get_fault(self, device_id: str) -> Optional[FaultInfo]:
        fault = self._active.get(device_id)
        if not fault:
            return None
        fault_type = _FAULT_TYPE_MAP.get(fault.fault_type_id)
        return self._to_info(fault, fault_type)

    def list_active(self) -> list[FaultInfo]:
        result = []
        for fault in self._active.values():
            fault_type = _FAULT_TYPE_MAP.get(fault.fault_type_id)
            result.append(self._to_info(fault, fault_type))
        return result

    @staticmethod
    def list_fault_types() -> list[FaultTypeDefinition]:
        return BUILTIN_FAULT_TYPES

    @staticmethod
    def get_fault_type(fault_type_id: str) -> Optional[FaultTypeDefinition]:
        return _FAULT_TYPE_MAP.get(fault_type_id)

    # ------------------------------------------------------------------
    # 内部逻辑
    # ------------------------------------------------------------------

    def _compute_value(
        self,
        pf: PointFaultConfig,
        baseline: float,
        progress: float,
        intensity: float,
    ) -> float:
        """根据故障配置和当前进度计算覆盖值"""
        if pf.mode == FaultMode.INSTANT:
            # 瞬间模式：直接用目标值，不随时间变化
            if pf.target_value is not None:
                target = pf.target_value
            elif pf.multiplier is not None:
                target = baseline * (1.0 + (pf.multiplier - 1.0) * intensity)
            else:
                target = baseline
        else:
            # 渐进模式：随 progress 线性劣化
            if pf.target_value is not None:
                target = baseline + (pf.target_value - baseline) * progress * intensity
            elif pf.multiplier is not None:
                target = baseline * (1.0 + (pf.multiplier - 1.0) * progress * intensity)
            else:
                target = baseline

        # 叠加随机噪声，模拟真实信号抖动
        if pf.noise_scale > 0:
            target += random.gauss(0, pf.noise_scale * intensity)

        return round(max(0.0, target), 4)

    def _expire(self, device: Any, fault: ActiveFault) -> None:
        """故障到期，从 active 中移除，让生成器自然恢复正常值"""
        self._active.pop(device.id, None)
        logger.info("Fault expired: device=%s type=%s", device.id, fault.fault_type_id)

    @staticmethod
    def _to_info(fault: ActiveFault, fault_type: Optional[FaultTypeDefinition]) -> FaultInfo:
        now = time.time()
        elapsed = now - fault.started_at
        progress = min(elapsed / fault.duration, 1.0)
        affected = [pf.point for pf in fault_type.point_faults] if fault_type else []
        return FaultInfo(
            fault_id=fault.fault_id,
            device_id=fault.device_id,
            fault_type_id=fault.fault_type_id,
            fault_type_name=fault.fault_type_name,
            status=fault.status,
            intensity=fault.intensity,
            duration=fault.duration,
            elapsed=round(elapsed, 1),
            progress=round(progress, 3),
            affected_points=affected,
            started_at=fault.started_at,
        )


# 全局单例
fault_injector = FaultInjector()
