"""
CNC 车床正常加工状态时序数据生成算法
=====================================

设计原则：
  - spindle_speed / spindle_load / spindle_current 由 CncSpindleGenerator 统一驱动。
  - 生成链路：工艺阶段 → 目标转速 → 实际转速(EMA) → 负载 → 电流。
  - 热惯性模型：tool_temperature 使用一阶 RC 滤波，alpha ≈ 0.04/tick。
  - 磨损单调：tool_wear_value 在切削阶段只增不减。
  - 纯 Python 标准库实现，无第三方依赖。

用法：
  generator = BaseMetricGenerator()
  frame = generator.generate(t=0.0, dt=1.0, stage="roughing")
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class StageProfile:
    """某个加工阶段的工艺参数范围及行为特征。"""
    stage: str

    feed_rate_min: float
    feed_rate_max: float
    spindle_speed_min: float
    spindle_speed_max: float
    spindle_current_min: float
    spindle_current_max: float
    spindle_load_min: float
    spindle_load_max: float
    vibration_min: float
    vibration_max: float
    acoustic_min: float
    acoustic_max: float
    temperature_min: float
    temperature_max: float
    surface_roughness_min: float
    surface_roughness_max: float

    # 每 tick 磨损增量的阶段系数（idle/tool_change = 0）
    wear_rate_factor: float
    # 稳定性因子：越高噪声越小，finishing=0.95，roughing=0.6
    stability_factor: float

    # 衍生属性
    @property
    def feed_rate_mid(self) -> float:
        return (self.feed_rate_min + self.feed_rate_max) / 2

    @property
    def spindle_speed_mid(self) -> float:
        return (self.spindle_speed_min + self.spindle_speed_max) / 2

    @property
    def spindle_load_mid(self) -> float:
        return (self.spindle_load_min + self.spindle_load_max) / 2

    @property
    def vibration_mid(self) -> float:
        return (self.vibration_min + self.vibration_max) / 2

    @property
    def acoustic_mid(self) -> float:
        return (self.acoustic_min + self.acoustic_max) / 2

    @property
    def temperature_mid(self) -> float:
        return (self.temperature_min + self.temperature_max) / 2

    @property
    def surface_roughness_mid(self) -> float:
        return (self.surface_roughness_min + self.surface_roughness_max) / 2


@dataclass
class MetricFrame:
    """单个 tick 产出的所有指标快照。"""
    timestamp: float
    stage: str

    feed_rate: float            # mm/min
    spindle_speed: float        # RPM
    spindle_current: float      # A
    spindle_load: float         # %
    vibration_x: float          # mm/s
    vibration_y: float          # mm/s
    vibration_z: float          # mm/s
    acoustic_emission: float    # V（声发射传感器电压，代表强度）
    tool_temperature: float     # °C
    surface_roughness: float    # μm Ra
    tool_wear_value: float      # μm（累积磨损量）


@dataclass
class GeneratorState:
    """跨 tick 需要持久化的生成器内部状态。"""
    material_random_walk: float = 0.0
    thermal_state: float = 28.0
    tool_wear_accumulated: float = 0.0
    last_spindle_load: float = 0.0
    load_lag_buffer: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    last_surface_roughness: float = 1.0
    cycle_phase: float = 0.0
    current_stage: str = "idle"
    # 切削阶段内已经过的秒数（用于 entry/exit ramp 计算）
    cutting_elapsed: float = 0.0
    # 当前切削阶段预估总时长（由状态机传入）
    cutting_total: float = 30.0
    # 状态机内部状态（idle/spinup/cutting/decel/tool_change），用于转速平滑
    spindle_state: str = "idle"
    # 任务级状态：process_running = 主轴保持目标转速；idle = 主轴可以停
    # 由 LatheSimulator 的 _STATE_TO_TASK 映射传入
    task_state: str = "idle"
    # 加工周期状态：air_cut / entry_cut / cutting / exit_cut
    # cycle_state 只描述负载形态，不控制主轴启停或转速档位
    cycle_state: str = "air_cut"


# ---------------------------------------------------------------------------
# SpindleLoadGenerator —— 状态驱动、切入/切出 ramp、周期扰动的主轴负载生成器
# ---------------------------------------------------------------------------

# 切削工艺配置
_PROCESS_CFG: dict[str, dict] = {
    "rough": {
        "base_load":       55.0,
        "slow_freq":        0.10,   # rad/s，慢波频率
        "slow_amp":         5.0,
        "cut_freq":         0.75,   # rad/s，切削波频率
        "cut_amp":          2.5,
        "material_freq":    0.03,
        "material_amp":     4.0,
        "noise_range":      2.0,    # uniform ±noise_range
        "clamp_min":       35.0,
        "clamp_max":       85.0,
        "ema_alpha":        0.10,
        "entry_ramp_s":     6.0,    # 切入 ramp 时长（秒）
        "exit_ramp_s":      5.0,    # 切出 ramp 时长（秒）
        # 低负载基准（air_cut 阶段，用于 ramp 起止参考）
        "air_cut_base":     8.0,
    },
    "semi_finish": {
        "base_load":       38.0,
        "slow_freq":        0.08,
        "slow_amp":         3.5,
        "cut_freq":         0.65,
        "cut_amp":          1.8,
        "material_freq":    0.025,
        "material_amp":     2.5,
        "noise_range":      1.5,
        "clamp_min":       20.0,
        "clamp_max":       65.0,
        "ema_alpha":        0.10,
        "entry_ramp_s":     5.0,
        "exit_ramp_s":      4.0,
        "air_cut_base":     6.0,
    },
    "finish": {
        "base_load":       22.0,
        "slow_freq":        0.06,
        "slow_amp":         2.0,
        "cut_freq":         0.55,
        "cut_amp":          1.0,
        "material_freq":    0.02,
        "material_amp":     1.2,
        "noise_range":      0.8,
        "clamp_min":        8.0,
        "clamp_max":       45.0,
        "ema_alpha":        0.09,
        "entry_ramp_s":     4.0,
        "exit_ramp_s":      3.0,
        "air_cut_base":     5.0,
    },
}

# 非切削状态配置（base / noise / clamp / ema_alpha）
_STATE_CFG: dict[str, dict] = {
    "idle":        {"base": 1.0,  "noise": 0.4,  "lo": 0.0,  "hi": 2.0,   "alpha": 0.35},
    "tool_change": {"base": 3.5,  "noise": 0.6,  "lo": 0.0,  "hi": 8.0,   "alpha": 0.25},
    "spindle_on":  {"base": 4.5,  "noise": 0.5,  "lo": 3.0,  "hi": 8.0,   "alpha": 0.22},
    "air_cut":     {"base": 7.5,  "noise": 0.8,  "lo": 5.0,  "hi": 12.0,  "alpha": 0.20},
}

# stage → process 映射（切削阶段）
_STAGE_TO_PROCESS: dict[str, str] = {
    "roughing":      "rough",
    "semi_finishing": "semi_finish",
    "finishing":      "finish",
}


class SpindleLoadGenerator:
    """
    状态驱动、切入/切出 ramp、周期级扰动的主轴负载生成器。

    支持的 stage 值（由 LatheSimulator 的 _get_metric_stage 传入）：
      idle / tool_change / roughing / semi_finishing / finishing

    内部将切削阶段按 cutting_elapsed / cutting_total 推导出
    entry_cut → cutting → exit_cut 子状态，实现平滑切入切出。
    每个加工周期开始时随机化 cycle_factor / phase 保证周期间差异。
    """

    def __init__(self, rng: random.Random):
        self._rng = rng
        self.prev_load: float = 0.0

        # 周期级随机状态（每次进入切削阶段时刷新）
        self._cycle_id: Optional[str] = None
        self._cycle_factor: float = 1.0   # 0.92~1.08，整体缩放基线
        self._phase1: float = 0.0          # 慢波初相位
        self._phase2: float = 0.0          # 切削波初相位
        self._material_phase: float = 0.0  # 材料漂移初相位

        # 上一个 stage，用于检测切削周期切换
        self._last_stage: str = "idle"

    # ------------------------------------------------------------------

    def _refresh_cycle(self, stage: str) -> None:
        """检测到新的切削周期时刷新周期级随机参数。"""
        cycle_id = stage  # 简单以 stage 变化作为新周期标志
        was_cutting = self._last_stage in _STAGE_TO_PROCESS
        now_cutting = stage in _STAGE_TO_PROCESS
        # 从非切削 → 切削，或切削工艺跳转（粗 → 精），认为是新周期
        if now_cutting and (not was_cutting or stage != self._last_stage):
            self._cycle_factor = self._rng.uniform(0.92, 1.08)
            self._phase1 = self._rng.uniform(0, 2 * math.pi)
            self._phase2 = self._rng.uniform(0, 2 * math.pi)
            self._material_phase = self._rng.uniform(0, 2 * math.pi)
        self._last_stage = stage

    def generate(
        self,
        t: float,
        stage: str,
        cutting_elapsed: float = 0.0,
        cutting_total: float = 30.0,
    ) -> float:
        """
        生成本 tick 的主轴负载（%）。

        Args:
            t:               当前时间（秒），用于波形计算。
            stage:           加工阶段（idle/tool_change/roughing/semi_finishing/finishing）。
            cutting_elapsed: 当前切削阶段已经过的秒数（用于 ramp 计算）。
            cutting_total:   当前切削阶段总时长预估（用于 exit_cut 判断）。

        Returns:
            clamp 后的主轴负载（%）。
        """
        self._refresh_cycle(stage)

        process = _STAGE_TO_PROCESS.get(stage)

        if process is None:
            # 非切削阶段
            cfg = _STATE_CFG.get(stage, _STATE_CFG["idle"])
            slow_wave = math.sin(t * 0.20) * 0.8
            noise = self._rng.uniform(-cfg["noise"], cfg["noise"])
            target = cfg["base"] + slow_wave + noise
            alpha = cfg["alpha"]
            lo, hi = cfg["lo"], cfg["hi"]
        else:
            # 切削阶段：entry_cut → cutting → exit_cut
            pcfg = _PROCESS_CFG[process]
            entry_s = pcfg["entry_ramp_s"]
            exit_s  = pcfg["exit_ramp_s"]
            air_base = pcfg["air_cut_base"]
            eff_base = pcfg["base_load"] * self._cycle_factor

            # 切出判断：距切削结束不足 exit_s 秒
            time_to_end = cutting_total - cutting_elapsed
            in_exit = (time_to_end <= exit_s) and (cutting_elapsed > entry_s)

            if cutting_elapsed <= entry_s:
                # ── entry_cut：从 air_base 平滑爬升到 eff_base ──
                ramp = cutting_elapsed / entry_s           # 0→1
                smooth_ramp = ramp * ramp * (3 - 2 * ramp)  # smoothstep
                target_cutting = self._cutting_target(t, pcfg, eff_base)
                target = air_base + (target_cutting - air_base) * smooth_ramp
                alpha = 0.12
                lo, hi = air_base * 0.5, pcfg["clamp_max"]
            elif in_exit:
                # ── exit_cut：从 eff_base 平滑下降到 air_base ──
                exit_elapsed = exit_s - time_to_end
                ramp = max(0.0, min(1.0, exit_elapsed / exit_s))
                smooth_ramp = ramp * ramp * (3 - 2 * ramp)
                target_cutting = self._cutting_target(t, pcfg, eff_base)
                target = target_cutting * (1.0 - smooth_ramp) + air_base * smooth_ramp
                alpha = 0.13
                lo, hi = air_base * 0.4, pcfg["clamp_max"]
            else:
                # ── cutting：稳定切削平台 ──
                target = self._cutting_target(t, pcfg, eff_base)
                alpha = pcfg["ema_alpha"]
                lo, hi = pcfg["clamp_min"], pcfg["clamp_max"]

        # EMA 平滑
        new_load = self.prev_load + alpha * (target - self.prev_load)
        new_load = max(lo, min(hi, new_load))
        self.prev_load = new_load
        return new_load

    def _cutting_target(self, t: float, pcfg: dict, eff_base: float) -> float:
        """计算切削平台目标负载（含慢波 + 切削波 + 材料漂移 + 小噪声）。"""
        slow_wave      = math.sin(t * pcfg["slow_freq"]     + self._phase1) * pcfg["slow_amp"]
        cut_wave       = math.sin(t * pcfg["cut_freq"]      + self._phase2) * pcfg["cut_amp"]
        material_drift = math.sin(t * pcfg["material_freq"] + self._material_phase) * pcfg["material_amp"]
        noise          = self._rng.uniform(-pcfg["noise_range"], pcfg["noise_range"])
        return eff_base + slow_wave + cut_wave + material_drift + noise


# ---------------------------------------------------------------------------
# CncSpindleGenerator —— spindle_speed / spindle_load / spindle_current 统一联动
# ---------------------------------------------------------------------------

# 工艺阶段 → 主轴目标转速配置
_PROCESS_SPEED_CFG: dict[str, dict] = {
    "rough":        {"target": 2000.0, "noise": 30.0,  "lo": 1800.0, "hi": 2200.0},
    "semi_finish":  {"target": 3000.0, "noise": 40.0,  "lo": 2800.0, "hi": 3200.0},
    "finish":       {"target": 4000.0, "noise": 50.0,  "lo": 3800.0, "hi": 4200.0},
}

# 非切削状态下转速目标（0 = 停止）
_STATE_SPEED_TARGET: dict[str, float] = {
    "idle":        0.0,
    "tool_change": 0.0,
}

# 各状态的转速 EMA alpha（值越小过渡越慢）
_SPEED_ALPHA: dict[str, float] = {
    "idle":        0.20,   # 快速停止
    "tool_change": 0.22,
    "spinup":      0.14,   # 平滑升速
    "cutting":     0.06,   # 稳定运转，微调
    "decel":       0.18,   # 降速
}

# 电流模型配置：各工艺的空载基础电流和负载系数
_PROCESS_CURRENT_CFG: dict[str, dict] = {
    "rough":       {"base": 3.0, "load_factor": 0.20, "noise": 0.4, "lo": 8.0,  "hi": 20.0},
    "semi_finish": {"base": 2.5, "load_factor": 0.16, "noise": 0.3, "lo": 5.0,  "hi": 15.0},
    "finish":      {"base": 2.0, "load_factor": 0.12, "noise": 0.2, "lo": 3.0,  "hi": 10.0},
}

# 非切削状态的电流配置
_STATE_CURRENT_CFG: dict[str, dict] = {
    "idle":        {"base": 0.3,  "noise": 0.15, "lo": 0.0, "hi": 1.0,  "alpha": 0.35},
    "tool_change": {"base": 0.5,  "noise": 0.2,  "lo": 0.0, "hi": 1.5,  "alpha": 0.30},
    "spindle_on":  {"base": 3.2,  "noise": 0.4,  "lo": 2.0, "hi": 5.0,  "alpha": 0.20},
    "air_cut":     {"base": 4.0,  "noise": 0.5,  "lo": 2.5, "hi": 6.0,  "alpha": 0.18},
}

# 电流 EMA alpha（切削阶段，略慢于负载，体现电气滞后）
_CURRENT_ALPHA_CUTTING: dict[str, float] = {
    "entry_cut": 0.10,
    "cutting":   0.10,
    "exit_cut":  0.12,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _ema(prev: float, target: float, alpha: float) -> float:
    return prev + alpha * (target - prev)


class CncSpindleGenerator:
    """
    统一驱动 spindle_speed / spindle_load / spindle_current 的联动生成器。

    生成链路：
        工艺阶段(process) → 目标转速 → 实际转速(EMA) → 负载(SpindleLoadGenerator)
        → 电流(负载+转速映射)

    stage 参数取值：idle / tool_change / roughing / semi_finishing / finishing
    spindle_state 参数取值：idle / tool_change / spinup / cutting / decel
      （由 LatheSimulator 状态机传入，用于控制转速 EMA alpha）
    """

    def __init__(self, rng: random.Random, load_gen: SpindleLoadGenerator):
        self._rng = rng
        self._load_gen = load_gen  # 复用已有的负载生成器

        self.prev_speed: float = 0.0
        self.prev_load: float = 0.0
        self.prev_current: float = 0.0
        self.process: str = "rough"

        self.current_cycle_id: Optional[str] = None
        self.cycle_factor: float = 1.0
        self.phase1: float = 0.0
        self.phase2: float = 0.0
        self.material_phase: float = 0.0
        self.entry_ramp_seconds: float = 6.0
        self.exit_ramp_seconds: float = 4.5
        self._cycle_cutting_load: float = 55.0

    def start_new_cycle(self, cycle_id: str) -> None:
        """每个 rough 切削周期只刷新一次周期级扰动参数。"""
        if cycle_id == self.current_cycle_id:
            return
        self.current_cycle_id = cycle_id
        self.cycle_factor = self._rng.uniform(0.92, 1.08)
        self.phase1 = self._rng.uniform(0, 2 * math.pi)
        self.phase2 = self._rng.uniform(0, 2 * math.pi)
        self.material_phase = self._rng.uniform(0, 2 * math.pi)
        self.entry_ramp_seconds = self._rng.uniform(4.0, 8.0)
        self.exit_ramp_seconds = self._rng.uniform(3.0, 6.0)

    def generate(
        self,
        t: float,
        stage: str,
        spindle_state: str = "cutting",
        cutting_elapsed: float = 0.0,
        cutting_total: float = 30.0,
        task_state: str = "idle",
    ) -> tuple[float, float, float]:
        """
        生成 (spindle_speed, spindle_load, spindle_current)。

        Args:
            t:               当前时间（秒）。
            stage:           MetricGenerator 加工阶段。
            spindle_state:   LatheSimulator 内部状态（idle/spinup/cutting/decel/tool_change）。
            cutting_elapsed: 切削阶段已过秒数（传给负载生成器）。
            cutting_total:   切削阶段总时长（传给负载生成器）。
            task_state:      任务级状态（process_running/idle）。
                             process_running 时主轴保持目标转速，即使 stage=idle（air_cut 间隙）。
        """
        # 本轮优化固定为 rough 正常工况；stage 仍原样写入 MetricFrame/标签。
        process = "rough"
        cycle_state = self._resolve_cycle_state(stage, task_state, cutting_elapsed, cutting_total)
        cycle_id = self._resolve_cycle_id(t, stage, task_state, cutting_elapsed, cutting_total)
        self.start_new_cycle(cycle_id)

        # ── 1. 主轴转速 ────────────────────────────────────────────────────
        speed = self._calc_speed(stage, spindle_state, process, task_state)

        # 保持旧负载生成器的周期状态同步，避免其他调用路径依赖其内部状态。
        self._load_gen.generate(
            t=t,
            stage=stage,
            cutting_elapsed=cutting_elapsed,
            cutting_total=cutting_total,
        )
        # ── 2. 主轴负载（rough 正常工况，cycle_state 只影响负载形态）───────
        load = self._calc_rough_load(t, speed, task_state, cycle_state, cutting_elapsed, cutting_total)

        # ── 3. 主轴电流（由转速 + 负载推导）───────────────────────────────
        current = self._calc_current(stage, spindle_state, process, speed, load, task_state, cycle_state)

        return speed, load, current

    # ------------------------------------------------------------------

    def _calc_speed(
        self,
        stage: str,
        spindle_state: str,
        process: Optional[str],
        task_state: str = "idle",
    ) -> float:
        """
        转速只由任务级状态控制启停；rough 周期状态不切换转速档位。
        """
        if task_state in ("idle", "spindle_off", "tool_change"):
            target = 0.0
            alpha = self._rng.uniform(0.12, 0.25)
        else:
            target = 2000.0
            if spindle_state == "spinup" or self.prev_speed < 1750.0:
                alpha = self._rng.uniform(0.10, 0.18)
            else:
                alpha = self._rng.uniform(0.03, 0.08)

        new_speed = _ema(self.prev_speed, target, alpha)
        if task_state not in ("idle", "spindle_off", "tool_change") and new_speed > 1750.0:
            new_speed += self._rng.uniform(-30.0, 30.0)
        new_speed = _clamp(new_speed, 0.0, 2200.0)
        self.prev_speed = new_speed
        return new_speed

    def _resolve_cycle_state(
        self,
        stage: str,
        task_state: str,
        cutting_elapsed: float,
        cutting_total: float,
    ) -> str:
        if task_state != "process_running":
            return "air_cut"
        if stage not in _STAGE_TO_PROCESS:
            return "air_cut"

        entry_s = max(self.entry_ramp_seconds, 0.1)
        exit_s = max(self.exit_ramp_seconds, 0.1)
        time_to_end = cutting_total - cutting_elapsed
        if cutting_elapsed <= entry_s:
            return "entry_cut"
        if cutting_elapsed > entry_s and time_to_end <= exit_s:
            return "exit_cut"
        return "cutting"

    def _resolve_cycle_id(
        self,
        t: float,
        stage: str,
        task_state: str,
        cutting_elapsed: float,
        cutting_total: float,
    ) -> str:
        if task_state != "process_running":
            return "stopped"
        if stage not in _STAGE_TO_PROCESS:
            return self.current_cycle_id or "air_cut"
        cycle_start = t - cutting_elapsed
        return f"rough:{cycle_start:.0f}:{cutting_total:.0f}"

    def _air_cut_load_target(self, t: float) -> float:
        target = 7.0 + math.sin(t * 0.20) * 1.5 + self._rng.uniform(-0.8, 0.8)
        return _clamp(target, 5.0, 12.0)

    def _rough_cutting_load_target(self, t: float) -> float:
        effective_base = 55.0 * self.cycle_factor
        slow_wave = math.sin(t * 0.10 + self.phase1) * 5.0
        cutting_wave = math.sin(t * 0.75 + self.phase2) * 2.5
        material_drift = math.sin(t * 0.03 + self.material_phase) * 4.0
        small_noise = self._rng.uniform(-2.0, 2.0)
        target = effective_base + slow_wave + cutting_wave + material_drift + small_noise
        return _clamp(target, 35.0, 82.0)

    def _calc_rough_load(
        self,
        t: float,
        speed: float,
        task_state: str,
        cycle_state: str,
        cutting_elapsed: float,
        cutting_total: float,
    ) -> float:
        if speed <= 50.0:
            target = self._rng.uniform(0.0, 2.0)
            alpha = self._rng.uniform(0.30, 0.45)
            lo, hi = 0.0, 2.0
        elif task_state == "process_running":
            air_load = self._air_cut_load_target(t)
            cutting_target = self._rough_cutting_load_target(t)
            self._cycle_cutting_load = cutting_target

            if cycle_state == "air_cut":
                target = air_load
                alpha = self._rng.uniform(0.18, 0.25)
                lo, hi = 5.0, 12.0
            elif cycle_state == "entry_cut":
                ratio = _clamp(cutting_elapsed / max(self.entry_ramp_seconds, 0.1), 0.0, 1.0)
                target = air_load + (cutting_target - air_load) * ratio
                alpha = self._rng.uniform(0.08, 0.14)
                lo, hi = 5.0, 82.0
            elif cycle_state == "cutting":
                target = cutting_target
                alpha = self._rng.uniform(0.08, 0.15)
                lo, hi = 35.0, 82.0
            elif cycle_state == "exit_cut":
                exit_elapsed = max(0.0, self.exit_ramp_seconds - (cutting_total - cutting_elapsed))
                ratio = _clamp(exit_elapsed / max(self.exit_ramp_seconds, 0.1), 0.0, 1.0)
                target = self._cycle_cutting_load * (1.0 - ratio) + air_load * ratio
                alpha = self._rng.uniform(0.10, 0.18)
                lo, hi = 5.0, 82.0
            else:
                target = air_load
                alpha = self._rng.uniform(0.18, 0.25)
                lo, hi = 5.0, 12.0
        else:
            target = self._rng.uniform(0.0, 2.0)
            alpha = self._rng.uniform(0.25, 0.40)
            lo, hi = 0.0, 2.0

        new_load = _ema(self.prev_load, target, alpha)
        if speed > 50.0 and task_state == "process_running":
            min_load = 5.0 if cycle_state in ("air_cut", "entry_cut", "exit_cut") else 35.0
            new_load = _clamp(new_load, min_load, hi)
        else:
            new_load = _clamp(new_load, lo, hi)
        self.prev_load = new_load
        return new_load

    def _calc_current(
        self,
        stage: str,
        spindle_state: str,
        process: Optional[str],
        speed: float,
        load: float,
        task_state: str = "idle",
        cycle_state: str = "air_cut",
    ) -> float:
        """电流由主轴转速和负载推导，避免独立随机曲线。"""
        if speed <= 50.0:
            target = self._rng.uniform(0.0, 0.8)
            alpha = self._rng.uniform(0.25, 0.40)
            lo, hi = 0.0, 0.8
        elif cycle_state == "air_cut":
            target = 3.5 + load * 0.12 + self._rng.uniform(-0.4, 0.4)
            alpha = self._rng.uniform(0.15, 0.25)
            lo, hi = 2.5, 6.0
        elif cycle_state == "entry_cut":
            target = 3.0 + load * 0.17 + self._rng.uniform(-0.5, 0.5)
            alpha = self._rng.uniform(0.08, 0.16)
            lo, hi = 2.5, 17.0
        elif cycle_state == "cutting":
            target = 3.0 + load * 0.18 + self._rng.uniform(-0.6, 0.6)
            alpha = self._rng.uniform(0.08, 0.15)
            lo, hi = 10.0, 17.0
        elif cycle_state == "exit_cut":
            target = 3.0 + load * 0.16 + self._rng.uniform(-0.5, 0.5)
            alpha = self._rng.uniform(0.10, 0.20)
            lo, hi = 2.5, 17.0
        else:
            target = 3.0 + load * 0.12 + self._rng.uniform(-0.4, 0.4)
            alpha = self._rng.uniform(0.15, 0.25)
            lo, hi = 2.5, 6.0

        new_current = _ema(self.prev_current, target, alpha)
        new_current = _clamp(new_current, lo, hi)
        self.prev_current = new_current
        return new_current


# ---------------------------------------------------------------------------
# 阶段配置
# ---------------------------------------------------------------------------

_STAGE_PROFILES: dict[str, StageProfile] = {
    "idle": StageProfile(
        stage="idle",
        feed_rate_min=0.0,    feed_rate_max=5.0,
        spindle_speed_min=0.0, spindle_speed_max=100.0,
        spindle_current_min=0.5, spindle_current_max=2.0,
        spindle_load_min=0.0,  spindle_load_max=5.0,
        vibration_min=0.01,   vibration_max=0.08,
        acoustic_min=0.01,    acoustic_max=0.08,
        temperature_min=25.0, temperature_max=40.0,
        surface_roughness_min=0.3, surface_roughness_max=1.5,
        wear_rate_factor=0.0,
        stability_factor=1.0,
    ),
    "tool_change": StageProfile(
        stage="tool_change",
        feed_rate_min=0.0,    feed_rate_max=20.0,
        spindle_speed_min=0.0, spindle_speed_max=100.0,
        spindle_current_min=1.0, spindle_current_max=4.0,
        spindle_load_min=0.0,  spindle_load_max=8.0,
        vibration_min=0.05,   vibration_max=0.3,
        acoustic_min=0.05,    acoustic_max=0.4,
        temperature_min=25.0, temperature_max=45.0,
        surface_roughness_min=0.3, surface_roughness_max=1.5,
        wear_rate_factor=0.0,
        stability_factor=0.8,
    ),
    "roughing": StageProfile(
        stage="roughing",
        feed_rate_min=800.0,  feed_rate_max=1600.0,
        spindle_speed_min=1200.0, spindle_speed_max=2500.0,
        spindle_current_min=12.0, spindle_current_max=25.0,
        spindle_load_min=45.0, spindle_load_max=80.0,
        vibration_min=0.4,    vibration_max=1.2,
        acoustic_min=0.5,     acoustic_max=1.3,
        temperature_min=45.0, temperature_max=75.0,
        surface_roughness_min=2.0, surface_roughness_max=6.0,
        wear_rate_factor=1.5,
        stability_factor=0.6,
    ),
    "semi_finishing": StageProfile(
        stage="semi_finishing",
        feed_rate_min=400.0,  feed_rate_max=900.0,
        spindle_speed_min=2200.0, spindle_speed_max=3800.0,
        spindle_current_min=8.0,  spindle_current_max=18.0,
        spindle_load_min=30.0, spindle_load_max=60.0,
        vibration_min=0.25,   vibration_max=0.8,
        acoustic_min=0.3,     acoustic_max=0.9,
        temperature_min=40.0, temperature_max=65.0,
        surface_roughness_min=1.0, surface_roughness_max=3.0,
        wear_rate_factor=1.0,
        stability_factor=0.8,
    ),
    "finishing": StageProfile(
        stage="finishing",
        feed_rate_min=100.0,  feed_rate_max=400.0,
        spindle_speed_min=3000.0, spindle_speed_max=5000.0,
        spindle_current_min=5.0,  spindle_current_max=12.0,
        spindle_load_min=15.0, spindle_load_max=40.0,
        vibration_min=0.1,    vibration_max=0.45,
        acoustic_min=0.15,    acoustic_max=0.5,
        temperature_min=35.0, temperature_max=55.0,
        surface_roughness_min=0.3, surface_roughness_max=1.5,
        wear_rate_factor=0.5,
        stability_factor=0.95,
    ),
}

# 阶段切削强度基准系数（归一化到 [0,1] 区间用于 cutting_intensity 计算）
_STAGE_INTENSITY_FACTOR: dict[str, float] = {
    "idle":          0.02,
    "tool_change":   0.05,
    "roughing":      1.00,
    "semi_finishing": 0.65,
    "finishing":     0.35,
}

# 基础磨损速率 μm/tick（roughing 1.5×，finishing 0.5×）
_BASE_WEAR_RATE = 0.002   # μm/tick，在 roughing 阶段约每 500 tick 磨损 1 μm


# ---------------------------------------------------------------------------
# 主生成器
# ---------------------------------------------------------------------------

class BaseMetricGenerator:
    """
    CNC 车床正常加工状态时序数据生成器。

    典型用法：
        gen = BaseMetricGenerator(ambient_temperature=28.0, seed=20260609)
        frame = gen.generate(t=0.0, dt=1.0, stage="roughing")
    """

    def __init__(
        self,
        ambient_temperature: float = 28.0,
        seed: Optional[int] = None,
        thermal_alpha: float = 0.04,
    ):
        self._ambient = ambient_temperature
        self._rng = random.Random(seed)
        self._thermal_alpha = thermal_alpha
        self._state = GeneratorState(
            thermal_state=ambient_temperature,
            last_surface_roughness=1.0,
        )
        # 负载生成器（状态驱动 + ramp + EMA）
        self._spindle_load_gen = SpindleLoadGenerator(self._rng)
        # 主轴联动生成器（speed / load / current 统一驱动）
        self._spindle_gen = CncSpindleGenerator(self._rng, self._spindle_load_gen)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def generate(self, t: float, dt: float, stage: str) -> MetricFrame:
        """
        生成一帧指标数据。

        Args:
            t:     当前时间（秒），用于低频波形计算。
            dt:    时间步长（秒），影响磨损增量和热惯性。
            stage: 加工阶段名称（idle/tool_change/roughing/semi_finishing/finishing）。

        Returns:
            MetricFrame，所有指标均已 clamp 至合理范围。
        """
        profile = self.get_stage_profile(stage)
        state = self._state

        # ── 切削阶段计时维护 ─────────────────────────────────────────────────
        is_cutting = stage in _STAGE_TO_PROCESS
        if is_cutting:
            if state.current_stage not in _STAGE_TO_PROCESS:
                # 刚进入切削阶段，重置计时
                state.cutting_elapsed = 0.0
            else:
                state.cutting_elapsed += dt
        else:
            state.cutting_elapsed = 0.0
        state.current_stage = stage

        # ── 1. 材料扰动（慢变量，低频正弦 + 随机游走）──────────────────────
        material_variation = self._calc_material_variation(t, dt, state)

        # ── 2. 切削周期波动（feed_rate 使用）────────────────────────────────
        cutting_cycle_wave = self._calc_cutting_cycle_wave(t, dt, stage, state, profile)

        # ── 3. feed_rate ──────────────────────────────────────────────────────
        feed_rate = self._calc_feed_rate(profile, cutting_cycle_wave, stage)

        # ── 4. cutting_intensity（供其他指标参考，不再驱动 load）────────────
        cutting_intensity = self._calc_cutting_intensity(
            feed_rate, stage, material_variation, profile
        )

        # ── 5. spindle_speed / spindle_load / spindle_current（联动生成）────
        task_state = getattr(state, "task_state", "idle")
        spindle_state = state.spindle_state
        if stage in _STAGE_TO_PROCESS and task_state == "idle":
            # 兼容直接调用 BaseMetricGenerator.generate(stage="roughing") 的路径：
            # 显式切削阶段代表正常加工中，而不是任务级停机。
            task_state = "process_running"
            if spindle_state == "idle":
                spindle_state = "cutting"
        spindle_speed, spindle_load, spindle_current = self._spindle_gen.generate(
            t=t,
            stage=stage,
            spindle_state=spindle_state,
            cutting_elapsed=state.cutting_elapsed,
            cutting_total=state.cutting_total,
            task_state=task_state,
        )

        # ── 6. vibration（三轴，各有小幅随机偏差）────────────────────────────
        vib_x, vib_y, vib_z = self._calc_vibration(
            profile, spindle_load, feed_rate, stage
        )

        # ── 7. acoustic_emission ─────────────────────────────────────────────
        vibration_rms = (vib_x + vib_y + vib_z) / 3.0
        acoustic_emission = self._calc_acoustic(profile, vibration_rms, spindle_load)

        # ── 8. tool_temperature（热惯性模型）────────────────────────────────
        tool_temperature = self._calc_temperature(
            profile, spindle_load, spindle_current, dt, state
        )

        # ── 9. tool_wear_value（单调递增）────────────────────────────────────
        tool_wear_value = self._calc_tool_wear(profile, spindle_load, dt, state)

        # ── 10. surface_roughness ─────────────────────────────────────────────
        surface_roughness = self._calc_surface_roughness(
            profile, vibration_rms, tool_wear_value, stage, state
        )

        # ── 11. 更新滞后缓冲区 ────────────────────────────────────────────────
        state.load_lag_buffer.pop(0)
        state.load_lag_buffer.append(spindle_load)
        state.last_spindle_load = spindle_load
        state.last_surface_roughness = surface_roughness

        # ── 12. 构造帧 + clamp ────────────────────────────────────────────────
        frame = MetricFrame(
            timestamp=t,
            stage=stage,
            feed_rate=feed_rate,
            spindle_speed=spindle_speed,
            spindle_current=spindle_current,
            spindle_load=spindle_load,
            vibration_x=vib_x,
            vibration_y=vib_y,
            vibration_z=vib_z,
            acoustic_emission=acoustic_emission,
            tool_temperature=tool_temperature,
            surface_roughness=surface_roughness,
            tool_wear_value=tool_wear_value,
        )
        return self.clamp_frame(frame)

    def get_stage_profile(self, stage: str) -> StageProfile:
        if stage not in _STAGE_PROFILES:
            raise ValueError(f"Unknown stage: {stage!r}. Valid: {list(_STAGE_PROFILES)}")
        return _STAGE_PROFILES[stage]

    def reset_wear(self) -> None:
        """换刀后重置磨损量（新刀从 0 开始）。"""
        self._state.tool_wear_accumulated = 0.0

    @property
    def state(self) -> GeneratorState:
        return self._state

    # ------------------------------------------------------------------
    # 各指标计算
    # ------------------------------------------------------------------

    def _calc_material_variation(
        self, t: float, dt: float, state: GeneratorState
    ) -> float:
        """
        材料均匀性扰动，慢变量。
        = 1.0 + 低频正弦（周期60s，幅度±3%）+ 随机游走（±1%/tick）
        """
        slow_sine = 0.03 * math.sin(2 * math.pi * t / 60.0)
        walk_step = self._rng.gauss(0, 0.005) * dt
        state.material_random_walk = max(
            -0.05, min(0.05, state.material_random_walk + walk_step)
        )
        return 1.0 + slow_sine + state.material_random_walk

    def _calc_cutting_cycle_wave(
        self,
        t: float,
        dt: float,
        stage: str,
        state: GeneratorState,
        profile: StageProfile,
    ) -> float:
        """
        切削周期波动（模拟走刀一圈的周期性载荷）。
        roughing 幅度较大（±8%），finishing 幅度较小（±3%）。
        """
        # 切削周期：roughing 约 0.5~1 rpm 对应进给一圈，用简化固定周期模拟
        period_map = {
            "roughing": 8.0,
            "semi_finishing": 6.0,
            "finishing": 4.0,
            "idle": 10.0,
            "tool_change": 10.0,
        }
        amplitude_map = {
            "roughing": 0.08,
            "semi_finishing": 0.055,
            "finishing": 0.03,
            "idle": 0.01,
            "tool_change": 0.02,
        }
        period = period_map.get(stage, 6.0)
        amplitude = amplitude_map.get(stage, 0.05)
        state.cycle_phase = (state.cycle_phase + dt * 2 * math.pi / period) % (
            2 * math.pi
        )
        return 1.0 + amplitude * math.sin(state.cycle_phase)

    def _calc_feed_rate(
        self,
        profile: StageProfile,
        cutting_cycle_wave: float,
        stage: str,
    ) -> float:
        """
        进给速度 = 阶段中值 × 切削波动 + 噪声。
        idle/tool_change 接近 0，finishing 更稳定。
        """
        if stage in ("idle", "tool_change"):
            return max(0.0, self._rng.uniform(profile.feed_rate_min, profile.feed_rate_max))
        noise_ratio = (1.0 - profile.stability_factor) * 0.06
        base = profile.feed_rate_mid * cutting_cycle_wave
        noise = self._rng.gauss(0, base * noise_ratio)
        return max(profile.feed_rate_min, min(profile.feed_rate_max, base + noise))

    def _calc_cutting_intensity(
        self,
        feed_rate: float,
        stage: str,
        material_variation: float,
        profile: StageProfile,
    ) -> float:
        """
        切削强度（0~1），驱动后续所有与切削力相关的指标。
        = normalize(feed_rate) × stage_factor × material_variation
        """
        stage_factor = _STAGE_INTENSITY_FACTOR.get(stage, 0.5)
        if profile.feed_rate_max <= profile.feed_rate_min:
            norm_feed = 0.5
        else:
            norm_feed = (feed_rate - profile.feed_rate_min) / (
                profile.feed_rate_max - profile.feed_rate_min
            )
            norm_feed = max(0.0, min(1.0, norm_feed))
        return max(0.0, min(1.0, norm_feed * stage_factor * material_variation))

    def _calc_vibration(
        self,
        profile: StageProfile,
        spindle_load: float,
        feed_rate: float,
        stage: str,
    ) -> tuple[float, float, float]:
        """
        振动（mm/s），三轴各有独立微偏。
        vibration = base × (1 + load_factor × feed_factor) + noise
        """
        load_norm = (spindle_load - profile.spindle_load_min) / max(
            profile.spindle_load_max - profile.spindle_load_min, 1.0
        )
        feed_norm = (feed_rate - profile.feed_rate_min) / max(
            profile.feed_rate_max - profile.feed_rate_min, 1.0
        )
        vib_base = profile.vibration_min + (
            profile.vibration_max - profile.vibration_min
        ) * load_norm
        vib_combined = vib_base * (1.0 + 0.15 * feed_norm)
        noise_sigma = vib_combined * (1.0 - profile.stability_factor) * 0.08

        # 三轴偏差因子（确定性偏置 + 小噪声，不完全相同）
        vib_x = vib_combined * self._rng.uniform(0.85, 1.15) + self._rng.gauss(0, noise_sigma)
        vib_y = vib_combined * self._rng.uniform(0.90, 1.25) + self._rng.gauss(0, noise_sigma)
        vib_z = vib_combined * self._rng.uniform(0.75, 1.05) + self._rng.gauss(0, noise_sigma)

        return (
            max(0.0, vib_x),
            max(0.0, vib_y),
            max(0.0, vib_z),
        )

    def _calc_acoustic(
        self,
        profile: StageProfile,
        vibration_rms: float,
        spindle_load: float,
    ) -> float:
        """
        声发射（V），受振动（40%权重）和主轴负载（30%权重）影响。
        """
        vib_norm = (vibration_rms - profile.vibration_min) / max(
            profile.vibration_max - profile.vibration_min, 1e-6
        )
        load_norm = (spindle_load - profile.spindle_load_min) / max(
            profile.spindle_load_max - profile.spindle_load_min, 1.0
        )
        acoustic_range = profile.acoustic_max - profile.acoustic_min
        acoustic = profile.acoustic_min + acoustic_range * (
            0.4 * vib_norm + 0.3 * load_norm + 0.3
        )
        noise = self._rng.gauss(0, acoustic_range * 0.03)
        return max(profile.acoustic_min, min(profile.acoustic_max, acoustic + noise))

    def _calc_temperature(
        self,
        profile: StageProfile,
        spindle_load: float,
        spindle_current: float,
        dt: float,
        state: GeneratorState,
    ) -> float:
        """
        刀具温度（°C），一阶热惯性模型，慢变量。
        target = ambient + k1 × load + k2 × current
        thermal_state += alpha × (target - thermal_state) × dt
        """
        k1 = (profile.temperature_max - self._ambient) / max(profile.spindle_load_max, 1.0) * 0.6
        k2 = (profile.temperature_max - self._ambient) / max(profile.spindle_current_max, 1.0) * 0.4
        target_temp = self._ambient + k1 * spindle_load + k2 * spindle_current
        target_temp = max(self._ambient, min(120.0, target_temp))

        alpha = self._thermal_alpha * dt
        state.thermal_state += alpha * (target_temp - state.thermal_state)

        noise = self._rng.gauss(0, 0.3)
        return max(20.0, min(120.0, state.thermal_state + noise))

    def _calc_tool_wear(
        self,
        profile: StageProfile,
        spindle_load: float,
        dt: float,
        state: GeneratorState,
    ) -> float:
        """
        刀具磨损量（μm），只在切削阶段单调递增。
        wear_delta = base_rate × stage_factor × load_factor × dt
        """
        if profile.wear_rate_factor <= 0.0:
            return state.tool_wear_accumulated

        load_norm = (spindle_load - profile.spindle_load_min) / max(
            profile.spindle_load_max - profile.spindle_load_min, 1.0
        )
        wear_delta = (
            _BASE_WEAR_RATE
            * profile.wear_rate_factor
            * (0.5 + 0.5 * load_norm)
            * dt
        )
        state.tool_wear_accumulated += max(0.0, wear_delta)
        return state.tool_wear_accumulated

    def _calc_surface_roughness(
        self,
        profile: StageProfile,
        vibration_rms: float,
        tool_wear_value: float,
        stage: str,
        state: GeneratorState,
    ) -> float:
        """
        表面粗糙度 Ra（μm）。
        idle/tool_change 阶段保持上次值。
        = profile.base × (1 + 0.2 × vib_factor) × (1 + 0.5 × wear_factor) + noise
        """
        if stage in ("idle", "tool_change"):
            return state.last_surface_roughness

        vib_range = profile.vibration_max - profile.vibration_min
        vib_factor = (vibration_rms - profile.vibration_min) / max(vib_range, 1e-6)
        vib_factor = max(0.0, min(1.0, vib_factor))

        # 磨损因子：磨损 50μm 时表面质量开始明显劣化
        wear_factor = min(tool_wear_value / 50.0, 1.0)

        roughness_range = profile.surface_roughness_max - profile.surface_roughness_min
        roughness = (
            profile.surface_roughness_min
            + roughness_range * (0.4 + 0.35 * vib_factor + 0.25 * wear_factor)
        )
        noise = self._rng.gauss(0, roughness_range * 0.03)
        return max(0.0, roughness + noise)

    # ------------------------------------------------------------------
    # clamp 和工具函数
    # ------------------------------------------------------------------

    @staticmethod
    def clamp_frame(frame: MetricFrame) -> MetricFrame:
        frame.feed_rate       = max(0.0, frame.feed_rate)
        frame.spindle_speed   = max(0.0, frame.spindle_speed)
        frame.spindle_current = max(0.0, frame.spindle_current)
        frame.spindle_load    = max(0.0, min(100.0, frame.spindle_load))
        frame.vibration_x     = max(0.0, frame.vibration_x)
        frame.vibration_y     = max(0.0, frame.vibration_y)
        frame.vibration_z     = max(0.0, frame.vibration_z)
        frame.acoustic_emission = max(0.0, frame.acoustic_emission)
        frame.tool_temperature  = max(20.0, min(120.0, frame.tool_temperature))
        frame.surface_roughness = max(0.0, frame.surface_roughness)
        frame.tool_wear_value   = max(0.0, frame.tool_wear_value)
        return frame

    def add_noise(self, value: float, ratio: float) -> float:
        """对 value 叠加比例为 ratio 的高斯噪声。"""
        return value + self._rng.gauss(0, abs(value) * ratio)

    @staticmethod
    def smooth_step(x: float) -> float:
        """S 型平滑函数，x ∈ [0,1] → [0,1]。"""
        x = max(0.0, min(1.0, x))
        return x * x * (3 - 2 * x)

    def random_walk(self, previous: float, step_sigma: float = 0.01) -> float:
        return previous + self._rng.gauss(0, step_sigma)
