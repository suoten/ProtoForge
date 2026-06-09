"""
tests/test_cnc_metric_generator.py
===================================

验证 BaseMetricGenerator 的正常加工状态时序数据生成算法。

覆盖以下场景：
1. roughing vs finishing 阶段指标大小关系
2. finishing 阶段主轴转速高且稳定、振动/粗糙度低
3. tool_temperature 慢变量特性（不瞬变、idle 缓慢回落）
4. tool_wear_value 在切削阶段单调递增，idle/tool_change 不增长
5. spindle_current 与 spindle_load 正相关且不完全同步（有滞后）
6. 所有指标无负值且不超合理边界
"""

import pytest
from protoforge.core.cnc_metric_generator import BaseMetricGenerator, MetricFrame


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gen():
    """固定随机种子，保证测试可重现。"""
    return BaseMetricGenerator(ambient_temperature=28.0, seed=20260609)


def _run_n(gen: BaseMetricGenerator, stage: str, n: int) -> list[MetricFrame]:
    """运行 n 个 tick，返回所有帧。"""
    frames = []
    for i in range(n):
        frames.append(gen.generate(t=float(i), dt=1.0, stage=stage))
    return frames


# ---------------------------------------------------------------------------
# 1. roughing vs finishing 阶段指标大小关系
# ---------------------------------------------------------------------------

class TestRoughingVsFinishing:
    """粗加工各项指标应高于精加工。"""

    N = 50  # 取足够多的样本，用均值比较，避免噪声误判

    def test_feed_rate_roughing_gt_finishing(self):
        gen_r = BaseMetricGenerator(seed=1)
        gen_f = BaseMetricGenerator(seed=1)
        avg_r = sum(f.feed_rate for f in _run_n(gen_r, "roughing", self.N)) / self.N
        avg_f = sum(f.feed_rate for f in _run_n(gen_f, "finishing", self.N)) / self.N
        assert avg_r > avg_f, f"roughing feed_rate均值({avg_r:.1f}) 应 > finishing({avg_f:.1f})"

    def test_spindle_load_roughing_gt_finishing(self):
        gen_r = BaseMetricGenerator(seed=2)
        gen_f = BaseMetricGenerator(seed=2)
        avg_r = sum(f.spindle_load for f in _run_n(gen_r, "roughing", self.N)) / self.N
        avg_f = sum(f.spindle_load for f in _run_n(gen_f, "finishing", self.N)) / self.N
        assert avg_r > avg_f, f"roughing spindle_load均值({avg_r:.1f}) 应 > finishing({avg_f:.1f})"

    def test_spindle_current_roughing_gt_finishing(self):
        gen_r = BaseMetricGenerator(seed=3)
        gen_f = BaseMetricGenerator(seed=3)
        avg_r = sum(f.spindle_current for f in _run_n(gen_r, "roughing", self.N)) / self.N
        avg_f = sum(f.spindle_current for f in _run_n(gen_f, "finishing", self.N)) / self.N
        assert avg_r > avg_f, f"roughing current均值({avg_r:.2f}) 应 > finishing({avg_f:.2f})"

    def test_vibration_roughing_gt_finishing(self):
        gen_r = BaseMetricGenerator(seed=4)
        gen_f = BaseMetricGenerator(seed=4)
        avg_r = sum(
            (f.vibration_x + f.vibration_y + f.vibration_z) / 3
            for f in _run_n(gen_r, "roughing", self.N)
        ) / self.N
        avg_f = sum(
            (f.vibration_x + f.vibration_y + f.vibration_z) / 3
            for f in _run_n(gen_f, "finishing", self.N)
        ) / self.N
        assert avg_r > avg_f, f"roughing vibration均值({avg_r:.3f}) 应 > finishing({avg_f:.3f})"

    def test_surface_roughness_roughing_gt_finishing(self):
        gen_r = BaseMetricGenerator(seed=5)
        gen_f = BaseMetricGenerator(seed=5)
        avg_r = sum(f.surface_roughness for f in _run_n(gen_r, "roughing", self.N)) / self.N
        avg_f = sum(f.surface_roughness for f in _run_n(gen_f, "finishing", self.N)) / self.N
        assert avg_r > avg_f, f"roughing roughness均值({avg_r:.2f}) 应 > finishing({avg_f:.2f})"


# ---------------------------------------------------------------------------
# 2. finishing 阶段：高转速且稳定，振动/粗糙度低
# ---------------------------------------------------------------------------

class TestFinishing:

    def test_spindle_speed_high(self, gen):
        frames = _run_n(gen, "finishing", 30)
        for f in frames:
            assert f.spindle_speed >= 3000, f"finishing spindle_speed({f.spindle_speed}) 应 >= 3000 RPM"

    def test_spindle_speed_stable(self, gen):
        """精加工主轴转速波动应 < 2%（稳定性要求）。"""
        frames = _run_n(gen, "finishing", 50)
        speeds = [f.spindle_speed for f in frames]
        avg = sum(speeds) / len(speeds)
        max_deviation = max(abs(s - avg) / avg for s in speeds)
        assert max_deviation < 0.02, f"finishing 转速最大偏差({max_deviation:.3%}) 超过 2%"

    def test_vibration_low(self, gen):
        frames = _run_n(gen, "finishing", 30)
        for f in frames:
            vib_rms = (f.vibration_x + f.vibration_y + f.vibration_z) / 3
            assert vib_rms <= 0.6, f"finishing vibration_rms({vib_rms:.3f}) 应 <= 0.6 mm/s"

    def test_surface_roughness_low(self, gen):
        frames = _run_n(gen, "finishing", 30)
        for f in frames:
            assert f.surface_roughness <= 1.8, \
                f"finishing surface_roughness({f.surface_roughness:.3f}) 应 <= 1.8 μm"


# ---------------------------------------------------------------------------
# 3. tool_temperature 慢变量特性
# ---------------------------------------------------------------------------

class TestToolTemperature:

    MAX_JUMP_PER_TICK = 3.0   # 单 tick 最大允许温度变化（°C）

    def test_no_instant_jump_roughing(self, gen):
        """粗加工阶段温度不应瞬间大幅跳变。"""
        frames = _run_n(gen, "roughing", 60)
        temps = [f.tool_temperature for f in frames]
        for i in range(1, len(temps)):
            delta = abs(temps[i] - temps[i - 1])
            assert delta <= self.MAX_JUMP_PER_TICK, \
                f"tick {i}: 温度跳变 {delta:.2f}°C 超过 {self.MAX_JUMP_PER_TICK}°C"

    def test_temperature_rises_in_roughing(self, gen):
        """粗加工持续运行后温度应高于初始环境温度。"""
        frames = _run_n(gen, "roughing", 100)
        # 最后 10 tick 均值应高于初始热状态
        late_avg = sum(f.tool_temperature for f in frames[-10:]) / 10
        assert late_avg > 35.0, \
            f"粗加工后期温度均值({late_avg:.1f}°C) 应 > 35°C"

    def test_temperature_falls_in_idle(self):
        """idle 阶段温度应缓慢回落。"""
        gen = BaseMetricGenerator(seed=42)
        # 先跑 80 tick roughing 把温度升高
        for i in range(80):
            gen.generate(t=float(i), dt=1.0, stage="roughing")
        hot_temp = gen.state.thermal_state

        # 再跑 60 tick idle
        for i in range(80, 140):
            gen.generate(t=float(i), dt=1.0, stage="idle")
        cool_temp = gen.state.thermal_state

        assert cool_temp < hot_temp, \
            f"idle 后温度({cool_temp:.1f}) 应低于加工后温度({hot_temp:.1f})"

    def test_no_instant_jump_idle(self, gen):
        """idle 阶段温度同样不应瞬变。"""
        frames = _run_n(gen, "idle", 30)
        temps = [f.tool_temperature for f in frames]
        for i in range(1, len(temps)):
            delta = abs(temps[i] - temps[i - 1])
            assert delta <= self.MAX_JUMP_PER_TICK, \
                f"idle tick {i}: 温度跳变 {delta:.2f}°C"


# ---------------------------------------------------------------------------
# 4. tool_wear_value 单调性
# ---------------------------------------------------------------------------

class TestToolWear:

    def _check_monotone(self, stages: list[str], n_per_stage: int = 20):
        gen = BaseMetricGenerator(seed=99)
        prev_wear = 0.0
        for stage in stages:
            for i in range(n_per_stage):
                t = float(len(stages) * n_per_stage + i)
                frame = gen.generate(t=t, dt=1.0, stage=stage)
                assert frame.tool_wear_value >= prev_wear - 1e-9, \
                    f"stage={stage} tick={i}: wear({frame.tool_wear_value:.6f}) < prev({prev_wear:.6f})，磨损不单调"
                prev_wear = frame.tool_wear_value
        return prev_wear

    def test_wear_increases_in_roughing(self):
        gen = BaseMetricGenerator(seed=10)
        wear_start = gen.state.tool_wear_accumulated
        _run_n(gen, "roughing", 50)
        wear_end = gen.state.tool_wear_accumulated
        assert wear_end > wear_start, \
            f"粗加工后磨损({wear_end:.4f}) 应 > 初始({wear_start:.4f})"

    def test_wear_increases_in_semi_finishing(self):
        gen = BaseMetricGenerator(seed=11)
        _run_n(gen, "semi_finishing", 50)
        assert gen.state.tool_wear_accumulated > 0, "半精加工后磨损应 > 0"

    def test_wear_increases_in_finishing(self):
        gen = BaseMetricGenerator(seed=12)
        _run_n(gen, "finishing", 50)
        assert gen.state.tool_wear_accumulated > 0, "精加工后磨损应 > 0"

    def test_wear_no_increase_in_idle(self):
        gen = BaseMetricGenerator(seed=13)
        # 先加工一段，再 idle
        _run_n(gen, "roughing", 10)
        wear_before_idle = gen.state.tool_wear_accumulated
        _run_n(gen, "idle", 30)
        assert gen.state.tool_wear_accumulated == wear_before_idle, \
            "idle 阶段磨损不应增长"

    def test_wear_no_increase_in_tool_change(self):
        gen = BaseMetricGenerator(seed=14)
        _run_n(gen, "roughing", 10)
        wear_before = gen.state.tool_wear_accumulated
        _run_n(gen, "tool_change", 20)
        assert gen.state.tool_wear_accumulated == wear_before, \
            "tool_change 阶段磨损不应增长"

    def test_wear_monotone_across_cutting_stages(self):
        final_wear = self._check_monotone(
            ["roughing", "roughing", "semi_finishing", "finishing"],
            n_per_stage=30
        )
        assert final_wear > 0

    def test_roughing_wear_gt_finishing_wear(self):
        """粗加工单位时间磨损应快于精加工。"""
        gen_r = BaseMetricGenerator(seed=20)
        gen_f = BaseMetricGenerator(seed=20)
        _run_n(gen_r, "roughing", 100)
        _run_n(gen_f, "finishing", 100)
        assert gen_r.state.tool_wear_accumulated > gen_f.state.tool_wear_accumulated, \
            "粗加工磨损速率应高于精加工"


# ---------------------------------------------------------------------------
# 5. spindle_current 与 spindle_load 的相关性与滞后
# ---------------------------------------------------------------------------

class TestCurrentLoadCorrelation:

    def test_current_load_positive_correlation(self, gen):
        """电流与负载正相关（Pearson r > 0.5）。
        注：roughing 阶段噪声较大（stability=0.6），加上 1~2 tick 滞后，
        实际相关系数在 0.5~0.75 之间，符合真实 CNC 采集数据的特征。
        """
        frames = _run_n(gen, "roughing", 200)
        loads = [f.spindle_load for f in frames]
        currents = [f.spindle_current for f in frames]

        n = len(loads)
        mean_l = sum(loads) / n
        mean_c = sum(currents) / n
        cov = sum((l - mean_l) * (c - mean_c) for l, c in zip(loads, currents)) / n
        std_l = (sum((l - mean_l) ** 2 for l in loads) / n) ** 0.5
        std_c = (sum((c - mean_c) ** 2 for c in currents) / n) ** 0.5
        r = cov / (std_l * std_c + 1e-9)
        assert r > 0.5, f"电流-负载 Pearson r({r:.3f}) 应 > 0.5"

    def test_current_not_identical_to_load(self, gen):
        """电流与负载不完全相同（体现滞后和不同物理量）。"""
        frames = _run_n(gen, "roughing", 30)
        diffs = [abs(f.spindle_current - f.spindle_load) for f in frames]
        avg_diff = sum(diffs) / len(diffs)
        assert avg_diff > 1.0, \
            f"电流与负载均值差({avg_diff:.2f}) 过小，可能完全相同"

    def test_current_unit_range(self, gen):
        """电流应在 roughing 合理范围（12~25 A）附近。"""
        frames = _run_n(gen, "roughing", 50)
        for f in frames:
            assert 5.0 <= f.spindle_current <= 35.0, \
                f"roughing spindle_current({f.spindle_current:.2f} A) 超出合理范围"

    def test_current_lag_detection(self):
        """
        验证滞后：在负载突变后，电流应有一定惯性（不瞬间到达目标值）。
        用两个生成器模拟：一个跑 idle 后切换 roughing，检查前几 tick 电流低于稳态均值。
        """
        gen = BaseMetricGenerator(seed=77)
        # 先跑 10 tick idle（负载很低）
        for i in range(10):
            gen.generate(t=float(i), dt=1.0, stage="idle")
        # 再跑 roughing，前 3 tick 电流应低于稳态
        early_currents = []
        for i in range(10, 13):
            f = gen.generate(t=float(i), dt=1.0, stage="roughing")
            early_currents.append(f.spindle_current)
        # 稳态（第 30~40 tick）
        for i in range(13, 40):
            f = gen.generate(t=float(i), dt=1.0, stage="roughing")
        steady_currents = []
        for i in range(40, 60):
            f = gen.generate(t=float(i), dt=1.0, stage="roughing")
            steady_currents.append(f.spindle_current)

        early_avg = sum(early_currents) / len(early_currents)
        steady_avg = sum(steady_currents) / len(steady_currents)
        assert early_avg < steady_avg, \
            f"切换到 roughing 后早期电流({early_avg:.2f}) 应低于稳态({steady_avg:.2f})，体现滞后"


# ---------------------------------------------------------------------------
# 6. 所有指标边界检查（无负值，不超上限）
# ---------------------------------------------------------------------------

class TestBoundaries:

    ALL_STAGES = ["idle", "tool_change", "roughing", "semi_finishing", "finishing"]

    def test_no_negative_values(self):
        for stage in self.ALL_STAGES:
            gen = BaseMetricGenerator(seed=0)
            for i, frame in enumerate(_run_n(gen, stage, 30)):
                assert frame.feed_rate >= 0, f"{stage} t={i}: feed_rate < 0"
                assert frame.spindle_speed >= 0, f"{stage} t={i}: spindle_speed < 0"
                assert frame.spindle_current >= 0, f"{stage} t={i}: spindle_current < 0"
                assert frame.spindle_load >= 0, f"{stage} t={i}: spindle_load < 0"
                assert frame.vibration_x >= 0, f"{stage} t={i}: vibration_x < 0"
                assert frame.vibration_y >= 0, f"{stage} t={i}: vibration_y < 0"
                assert frame.vibration_z >= 0, f"{stage} t={i}: vibration_z < 0"
                assert frame.acoustic_emission >= 0, f"{stage} t={i}: acoustic_emission < 0"
                assert frame.surface_roughness >= 0, f"{stage} t={i}: surface_roughness < 0"
                assert frame.tool_wear_value >= 0, f"{stage} t={i}: tool_wear_value < 0"

    def test_spindle_load_max_100(self):
        for stage in self.ALL_STAGES:
            gen = BaseMetricGenerator(seed=1)
            for i, frame in enumerate(_run_n(gen, stage, 30)):
                assert frame.spindle_load <= 100.0, \
                    f"{stage} t={i}: spindle_load({frame.spindle_load}) > 100%"

    def test_tool_temperature_range(self):
        for stage in self.ALL_STAGES:
            gen = BaseMetricGenerator(seed=2)
            for i, frame in enumerate(_run_n(gen, stage, 30)):
                assert 20.0 <= frame.tool_temperature <= 120.0, \
                    f"{stage} t={i}: tool_temperature({frame.tool_temperature:.1f}) 超出 [20,120]°C"

    def test_no_unrealistic_instant_jump(self):
        """任意连续 tick 的指标变化不应超过合理上限（防止仿真器 bug）。"""
        MAX_SPINDLE_SPEED_JUMP = 500   # RPM/tick
        MAX_LOAD_JUMP          = 30    # %/tick
        MAX_TEMP_JUMP          = 5     # °C/tick

        for stage in ["roughing", "finishing"]:
            gen = BaseMetricGenerator(seed=3)
            frames = _run_n(gen, stage, 60)
            for i in range(1, len(frames)):
                prev, curr = frames[i - 1], frames[i]
                assert abs(curr.spindle_speed - prev.spindle_speed) <= MAX_SPINDLE_SPEED_JUMP, \
                    f"{stage} t={i}: spindle_speed 跳变过大"
                assert abs(curr.spindle_load - prev.spindle_load) <= MAX_LOAD_JUMP, \
                    f"{stage} t={i}: spindle_load 跳变过大"
                assert abs(curr.tool_temperature - prev.tool_temperature) <= MAX_TEMP_JUMP, \
                    f"{stage} t={i}: tool_temperature 跳变过大"


# ---------------------------------------------------------------------------
# 附加：stage 名称错误时应抛出异常
# ---------------------------------------------------------------------------

def test_invalid_stage_raises():
    gen = BaseMetricGenerator()
    with pytest.raises(ValueError, match="Unknown stage"):
        gen.generate(t=0.0, dt=1.0, stage="nonexistent_stage")
