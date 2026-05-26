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
    # 进给堵转 — 工件夹紧松动或切削量过大导致进给卡死
    # 特征：进给速率瞬间降为0，主轴负载和电流急剧升高，主轴仍在转（区别于崩刃）
    # 模式：瞬间注入
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="feed_stall",
        name="进给堵转",
        description="进给轴卡死，进给速率降为零，主轴负载和电流急剧升高，主轴转速维持（区别于崩刃停主轴）",
        category="process",
        default_duration=20.0,
        tags=["进给", "堵转", "突发"],
        point_faults=[
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=2.8, noise_scale=5.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=3.8, noise_scale=1.5),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴过热 — 长时间高负荷或冷却系统故障
    # 特征：主轴负载和电流持续偏高，转速因热保护逐渐降低
    # 模式：渐进式，持续时间较长
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_overheat",
        name="主轴过热",
        description="主轴长时间高负荷运转或冷却不足，spindle_load和spindle_current持续偏高，转速因热保护渐进下降",
        category="thermal",
        default_duration=240.0,
        tags=["主轴", "过热", "渐进"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             multiplier=1.6, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_scale=1.2),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             multiplier=0.6, noise_scale=50.0),
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

    # ------------------------------------------------------------------
    # 刀具磨损加剧 — 主轴负载趋势漂移
    # 特征：spindle_load 基线随时间缓慢爬升（趋势漂移型），电流同步升高
    # 场景：刀具从轻度磨损到需要换刀的完整过程
    # 模式：渐进式，持续时间长
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear_progressive",
        name="刀具磨损加剧",
        description="刀具磨损导致切削阻力持续增大，spindle_load基线缓慢爬升至1.8倍，spindle_current同步升高；进给速度由G代码控制不受影响",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "磨损", "负载", "趋势漂移"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.7, noise_scale=1.5),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具崩刃 — 主轴负载突发脉冲
    # 特征：spindle_load 瞬间冲高（可超120%，FANUC最大输出200%），进给停止，CNC停主轴
    # 场景：刀具突发性失效，机床触发过载报警并停机
    # 模式：瞬间注入，持续时间极短
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_breakage_sudden",
        name="刀具崩刃",
        description="刀具突发性崩刃，spindle_load瞬间冲高至正常值3.2倍（可超120%，FANUC最大输出200%），进给停止，CNC触发过载报警并停主轴",
        category="tool",
        default_duration=10.0,
        tags=["刀具", "崩刃", "突发", "过载"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=3.2, noise_scale=8.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=4.0, noise_scale=3.0),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="alarm_status", mode=FaultMode.INSTANT,
                             target_value=1.0, noise_scale=0.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 过载保护触发 — 负载/进给反向联动异常（关系约束型）
    # 特征：负载超限后CNC自动降进给速率，负载高企与进给降速同时出现
    # 场景：切削参数过激进，CNC自适应保护介入
    # 模式：瞬间注入（持续期间维持异常关系）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_overload_protection",
        name="过载保护触发",
        description="主轴负载超限，CNC自动降低进给速率保护刀具，负载高企与进给降速同时出现",
        category="tool",
        default_duration=120.0,
        tags=["刀具", "过载", "进给", "关系约束"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=1.9, noise_scale=4.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.8, noise_scale=2.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=0.35, noise_scale=15.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 空切检测 — 刀具未接触工件（工况切换型）
    # 特征：spindle_load 跌至空载区间（5-15%），主轴转速和进给速率保持正常
    # 场景：工件装夹偏移、程序坐标错误、工件提前切完
    # 模式：瞬间注入（均值跳变，方差不变）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="air_cutting",
        name="空切检测",
        description="刀具未接触工件，spindle_load跌至空载区间(5-15%)，spindle_current降至空转水平，转速进给保持正常",
        category="tool",
        default_duration=180.0,
        tags=["刀具", "空切", "工况切换", "负载"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_value=8.0, noise_scale=2.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_value=2.5, noise_scale=0.3),
        ],
    ),

    # ------------------------------------------------------------------
    # 积屑瘤 — 切屑粘附刀刃导致周期性负载突刺
    # 特征：spindle_load 在正常基线上出现间歇性冲高后恢复，不是持续爬升
    #       突刺幅度约1.5-2倍基线，持续1-3秒后自行恢复，周期不固定
    # 场景：低速切削、切削液不足、韧性材料（铝合金、不锈钢）加工时常见
    # 模式：瞬间注入（noise_scale 大，模拟随机突刺效果）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="built_up_edge",
        name="积屑瘤",
        description="切屑粘附刀刃，spindle_load在正常基线上出现间歇性突刺（1.5-2倍），突刺后自行恢复，区别于磨损的持续爬升",
        category="tool",
        default_duration=300.0,
        tags=["刀具", "积屑瘤", "突刺", "低速切削"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=1.7, noise_scale=12.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.6, noise_scale=4.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具涂层剥落 — 负载阶跃后在新基线稳定
    # 特征：spindle_load 出现一次阶跃式跳升（区别于缓慢爬升的磨损），
    #       然后在新的高基线上稳定波动，不会继续爬升也不会恢复
    # 场景：涂层质量问题或切削条件恶劣导致涂层突然失效
    # 模式：瞬间注入（立即跳到新基线，持续维持）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="coating_spalling",
        name="刀具涂层剥落",
        description="刀具涂层突然失效，spindle_load阶跃式跳升至1.5倍后在新基线稳定波动，区别于磨损的缓慢爬升和崩刃的瞬间冲高",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "涂层", "阶跃", "工况切换"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=1.5, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.4, noise_scale=1.5),
        ],
    ),

    # ------------------------------------------------------------------
    # 换刀装夹偏移 — 刀具伸出量异常导致负载整体偏高
    # 特征：换刀后 spindle_load 整体偏高（1.4-1.6倍），波动规律正常，
    #       不是空切（负载不低），不是磨损（不随时间爬升）
    # 场景：刀具伸出量偏长、刀柄锥面未清洁、刀具型号装错
    # 模式：瞬间注入（均值整体偏移，方差不变）
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_offset_error",
        name="换刀装夹偏移",
        description="换刀后刀具伸出量或装夹位置异常，spindle_load整体偏高(1.4-1.6倍)，波动规律正常，不随时间变化，区别于磨损和空切",
        category="tool",
        default_duration=3600.0,
        tags=["刀具", "装夹", "工况切换", "负载偏移"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             multiplier=1.5, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.4, noise_scale=1.5),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=5.0),
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
                # 基线为0说明注入时设备处于换刀/停机状态
                # target_value 模式可以直接执行（如崩刃归零、空切归空载）
                # multiplier 模式跳过，避免在零基线上产生无意义的值
                if pf.target_value is None:
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
