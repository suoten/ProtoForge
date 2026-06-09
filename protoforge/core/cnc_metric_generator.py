"""
CNC 车床正常加工状态时序数据生成算法
=====================================

设计原则：
  - 所有指标由切削强度 cutting_intensity 统一驱动，禁止各自独立随机。
  - 热惯性模型：tool_temperature 使用一阶 RC 滤波，alpha ≈ 0.04/tick。
  - 电流滞后：spindle_current 对 spindle_load 有 1~3 tick 的一阶滞后。
  - 磨损单调：tool_wear_value 在切削阶段只增不减。
  - 噪声比例：roughing > semi_finishing > finishing，稳定性反向。
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
    # 材料扰动随机游走值（慢变量，[-0.05, +0.05]）
    material_random_walk: float = 0.0
    # 热状态（tool_temperature 的平滑变量）
    thermal_state: float = 28.0
    # 刀具累积磨损（μm，单调不减）
    tool_wear_accumulated: float = 0.0
    # 上一 tick 的 spindle_load（用于电流滞后计算）
    last_spindle_load: float = 0.0
    # 滞后缓冲区（最多保存 3 tick 历史）
    load_lag_buffer: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # 上一 tick 的 surface_roughness（idle 阶段保持上次值）
    last_surface_roughness: float = 1.0
    # 切削周期相位（用于 cutting_cycle_wave）
    cycle_phase: float = 0.0
    # 当前阶段
    current_stage: str = "idle"


# ---------------------------------------------------------------------------
# SpindleLoadGenerator —— 状态驱动、EMA 平滑的主轴负载生成器
# ---------------------------------------------------------------------------

# 各工艺阶段的负载基线及允许范围
_PROCESS_LOAD_CONFIG: dict[str, dict] = {
    "rough": {
        "base": 55.0,
        "slow_amp": 6.0,    # 慢周期波动幅度（%）
        "cut_amp": 4.0,     # 切削周期扰动幅度（%）
        "noise_sigma": 2.5, # 高斯噪声标准差（%）
        "clamp_min": 35.0,
        "clamp_max": 85.0,
        "ema_alpha": 0.18,  # 较快响应，粗加工负载变化快
    },
    "semi_finish": {
        "base": 38.0,
        "slow_amp": 4.0,
        "cut_amp": 2.5,
        "noise_sigma": 1.5,
        "clamp_min": 22.0,
        "clamp_max": 65.0,
        "ema_alpha": 0.15,
    },
    "finish": {
        "base": 22.0,
        "slow_amp": 2.5,
        "cut_amp": 1.5,
        "noise_sigma": 0.8,
        "clamp_min": 12.0,
        "clamp_max": 42.0,
        "ema_alpha": 0.12,  # 较慢响应，精加工负载更平稳
    },
}

# 各驱动状态的负载基线及 EMA 系数
_STATE_LOAD_CONFIG: dict[str, dict] = {
    "idle":        {"base": 1.5,  "noise_sigma": 0.3, "clamp_min": 0.0,  "clamp_max": 5.0,  "ema_alpha": 0.10},
    "tool_change": {"base": 4.0,  "noise_sigma": 0.8, "clamp_min": 0.0,  "clamp_max": 10.0, "ema_alpha": 0.12},
    "spindle_on":  {"base": 8.0,  "noise_sigma": 1.2, "clamp_min": 3.0,  "clamp_max": 18.0, "ema_alpha": 0.15},
    "air_cut":     {"base": 15.0, "noise_sigma": 2.0, "clamp_min": 8.0,  "clamp_max": 28.0, "ema_alpha": 0.16},
    # "cutting" state delegates to _PROCESS_LOAD_CONFIG
}

# stage 名称 → 内部 process 名称映射
_STAGE_TO_PROCESS: dict[str, str] = {
    "roughing":       "rough",
    "semi_finishing":  "semi_finish",
    "finishing":       "finish",
}

# stage 名称 → 驱动状态映射（非切削阶段）
_STAGE_TO_STATE: dict[str, str] = {
    "idle":        "idle",
    "tool_change": "tool_change",
}


class SpindleLoadGenerator:
    """
    状态驱动、EMA 平滑的主轴负载生成器。

    内部维护 prev_load 跨 tick 状态，使负载曲线连续平滑，
    避免随机脉冲。各切削工艺有独立基线和 clamp 范围，
    idle/tool_change 等非切削状态接近 0。

    stage 参数取值：idle / tool_change / roughing / semi_finishing / finishing
    """

    def __init__(self, rng: random.Random):
        self._rng = rng
        self.prev_load: float = 0.0

    def generate(
        self,
        t: float,
        stage: str,
        material_variation: float = 1.0,
        slow_phase: float = 0.0,
        cut_phase: float = 0.0,
    ) -> float:
        """
        生成本 tick 的主轴负载（%）。

        Args:
            t:                当前时间（秒），保留供未来扩展。
            stage:            加工阶段（idle/tool_change/roughing/semi_finishing/finishing）。
            material_variation: 材料扰动系数（≈1.0，±5%）。
            slow_phase:       慢周期相位（弧度），由外部统一维护。
            cut_phase:        切削周期相位（弧度），由外部统一维护。

        Returns:
            clamp 后的主轴负载（%）。
        """
        process = _STAGE_TO_PROCESS.get(stage)

        if process is not None:
            # 切削阶段：使用工艺基线
            cfg = _PROCESS_LOAD_CONFIG[process]
            slow_wave = cfg["slow_amp"] * math.sin(slow_phase)
            cut_wave  = cfg["cut_amp"]  * math.sin(cut_phase)
            noise     = self._rng.gauss(0, cfg["noise_sigma"])
            mat_delta = (material_variation - 1.0) * cfg["base"] * 0.5  # 材料变化影响基线的 50%
            target    = cfg["base"] + slow_wave + cut_wave + noise + mat_delta
            alpha     = cfg["ema_alpha"]
            lo, hi    = cfg["clamp_min"], cfg["clamp_max"]
        else:
            # 非切削阶段：使用状态基线
            state_key = _STAGE_TO_STATE.get(stage, "idle")
            cfg = _STATE_LOAD_CONFIG[state_key]
            noise  = self._rng.gauss(0, cfg["noise_sigma"])
            target = cfg["base"] + noise
            alpha  = cfg["ema_alpha"]
            lo, hi = cfg["clamp_min"], cfg["clamp_max"]

        # EMA 平滑
        new_load = self.prev_load + alpha * (target - self.prev_load)
        # clamp
        new_load = max(lo, min(hi, new_load))
        self.prev_load = new_load
        return new_load


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
        # 热惯性系数（每 tick 向目标温度靠近的比例）
        self._thermal_alpha = thermal_alpha
        self._state = GeneratorState(
            thermal_state=ambient_temperature,
            last_surface_roughness=1.0,
        )
        # 主轴负载生成器（状态驱动 + EMA 平滑）
        self._spindle_load_gen = SpindleLoadGenerator(self._rng)

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
        state.current_stage = stage

        # ── 1. 材料扰动（慢变量，低频正弦 + 随机游走）──────────────────────
        material_variation = self._calc_material_variation(t, dt, state)

        # ── 2. 切削周期波动 ──────────────────────────────────────────────────
        cutting_cycle_wave = self._calc_cutting_cycle_wave(t, dt, stage, state, profile)

        # ── 3. feed_rate ──────────────────────────────────────────────────────
        feed_rate = self._calc_feed_rate(profile, cutting_cycle_wave, stage)

        # ── 4. spindle_speed ──────────────────────────────────────────────────
        spindle_speed = self._calc_spindle_speed(profile, stage)

        # ── 5. cutting_intensity（归一化切削强度）────────────────────────────
        cutting_intensity = self._calc_cutting_intensity(
            feed_rate, stage, material_variation, profile
        )

        # ── 6. spindle_load（状态驱动 + EMA 平滑）────────────────────────────
        # 慢波相位（约 90 s 周期）和切削相位复用 cycle_phase
        slow_phase = 2 * math.pi * t / 90.0
        spindle_load = self._calc_spindle_load(
            profile, stage, material_variation, slow_phase, state.cycle_phase
        )

        # ── 7. spindle_current（对 load 有 1~2 tick 滞后）────────────────────
        spindle_current = self._calc_spindle_current(profile, spindle_load, state)

        # ── 8. vibration（三轴，各有小幅随机偏差）────────────────────────────
        vib_x, vib_y, vib_z = self._calc_vibration(
            profile, spindle_load, feed_rate, stage
        )

        # ── 9. acoustic_emission ─────────────────────────────────────────────
        vibration_rms = (vib_x + vib_y + vib_z) / 3.0
        acoustic_emission = self._calc_acoustic(profile, vibration_rms, spindle_load)

        # ── 10. tool_temperature（热惯性模型）────────────────────────────────
        tool_temperature = self._calc_temperature(
            profile, spindle_load, spindle_current, dt, state
        )

        # ── 11. tool_wear_value（单调递增）────────────────────────────────────
        tool_wear_value = self._calc_tool_wear(profile, spindle_load, dt, state)

        # ── 12. surface_roughness ─────────────────────────────────────────────
        surface_roughness = self._calc_surface_roughness(
            profile, vibration_rms, tool_wear_value, stage, state
        )

        # ── 13. 更新滞后缓冲区 ────────────────────────────────────────────────
        state.load_lag_buffer.pop(0)
        state.load_lag_buffer.append(spindle_load)
        state.last_spindle_load = spindle_load
        state.last_surface_roughness = surface_roughness

        # ── 14. 构造帧 + clamp ────────────────────────────────────────────────
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

    def _calc_spindle_speed(self, profile: StageProfile, stage: str) -> float:
        """
        主轴转速正常状态下稳定。
        roughing 允许 2% 波动，finishing 允许 0.8% 波动。
        """
        if stage in ("idle", "tool_change"):
            return self._rng.uniform(profile.spindle_speed_min, profile.spindle_speed_max)
        noise_pct = {
            "roughing": 0.020,
            "semi_finishing": 0.015,
            "finishing": 0.008,
        }.get(stage, 0.015)
        base = profile.spindle_speed_mid
        noise = self._rng.gauss(0, base * noise_pct)
        return max(profile.spindle_speed_min, min(profile.spindle_speed_max, base + noise))

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

    def _calc_spindle_load(
        self,
        profile: StageProfile,
        stage: str,
        material_variation: float,
        slow_phase: float,
        cut_phase: float,
    ) -> float:
        """
        主轴负载（%）—— 委托给 SpindleLoadGenerator。
        使用状态驱动基线 + EMA 平滑，避免随机脉冲行为。
        """
        return self._spindle_load_gen.generate(
            t=0.0,  # t 保留，当前未使用
            stage=stage,
            material_variation=material_variation,
            slow_phase=slow_phase,
            cut_phase=cut_phase,
        )

    def _calc_spindle_current(
        self,
        profile: StageProfile,
        spindle_load: float,
        state: GeneratorState,
    ) -> float:
        """
        主轴电流（A），对负载有 1~2 tick 滞后（一阶低通）。
        current = idle_current + k × lag_load + noise
        k 由阶段电流范围和负载范围反推。
        """
        # 滞后混合：60% 当前负载 + 25% 上一 tick + 15% 两 tick 前
        lag_load = spindle_load * 0.60 + state.load_lag_buffer[1] * 0.25 + state.load_lag_buffer[0] * 0.15
        # 线性映射：load_min → current_min，load_max → current_max
        load_range = profile.spindle_load_max - profile.spindle_load_min
        current_range = profile.spindle_current_max - profile.spindle_current_min
        if load_range > 0:
            k = current_range / load_range
        else:
            k = 0.0
        current_base = profile.spindle_current_min + k * (lag_load - profile.spindle_load_min)
        noise = self._rng.gauss(
            0,
            (profile.spindle_current_max - profile.spindle_current_min)
            * (1.0 - profile.stability_factor)
            * 0.03,
        )
        return max(profile.spindle_current_min, min(profile.spindle_current_max, current_base + noise))

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
