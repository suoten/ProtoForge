"""
车床状态机仿真器

仿真 CNC 车床通过 MTConnect 协议能真实输出的信号。

工作周期（任务级）：
  IDLE → SPINUP → [切削大循环] → SPINDOWN → TOOL_CHANGE → IDLE

切削大循环（周期级，主轴保持转速）：
  AIR_CUT → CUTTING → DECEL_CYCLE → AIR_CUT → ...（循环 N 次后退出）
                ↓ (偶发，两种故障路径)
        TOOL_BREAK / CHIP_WRAP → TOOL_CHANGE → IDLE

关键设计：
  - AIR_CUT 状态：主轴已启动，快速定位中，主轴转速保持目标值
  - CUTTING 和 AIR_CUT 都属于 task_state="process_running"，主轴不停
  - 只有 IDLE / TOOL_CHANGE / 故障恢复 时 task_state="idle"，主轴才降到 0
  - 每完成 cycles_per_task 个切削周期后才真正回到 IDLE（换刀或停机）

每个 tick 的处理流程：
  1. 状态机推进（确定当前 stage）
  2. BaseMetricGenerator.generate() 生成健康 MetricFrame
     （联动建模 + 噪声 + clamp，正常加工算法与故障逻辑解耦）
  3. 把 MetricFrame 写入 device._point_values
  4. 通过 MetricsCollector 上报 Prometheus

崩刀（TOOL_BREAK）的 CNC 可观测特征：
  - spindle_load 突增（驱动器过载保护触发）
  - spindle_speed 急降至 0（CNC 紧急制动）
  - execution → STOPPED，e_stop → TRIGGERED
  - system_condition → FAULT，condition_native_code = ALM-401

刀缠屑（CHIP_WRAP）的 CNC 可观测特征：
  - spindle_load 缓慢持续爬升（缠绕阻力增大）
  - spindle_speed 因负载升高略微下降（恒功率特性）
  - feed_rate 出现不规律波动（缠屑阻力脉冲）
  - 超过负载阈值后 CNC 报警停机
  - system_condition → FAULT，condition_native_code = ALM-305
"""

import math
import random
import time
from enum import Enum
from typing import Any

from protoforge.core.cnc_metric_generator import BaseMetricGenerator
from protoforge.core.fault import fault_injector


class _State(Enum):
    IDLE = "idle"
    SPINUP = "spinup"
    AIR_CUT = "air_cut"        # 主轴运转，快速定位，不切削
    CUTTING = "cutting"
    DECEL_CYCLE = "decel_cycle"  # 周期级减速（主轴保持转速，只减进给）
    DECEL = "decel"              # 任务级降速（主轴降到 0）
    TOOL_CHANGE = "tool_change"
    TOOL_BREAK = "tool_break"
    CHIP_WRAP = "chip_wrap"


# 状态机阶段 → MetricGenerator 加工阶段的映射
_STATE_TO_STAGE: dict[_State, str] = {
    _State.IDLE:        "idle",
    _State.SPINUP:      "idle",
    _State.AIR_CUT:     "idle",        # air_cut 阶段负载模型用 idle，但主轴不停
    _State.CUTTING:     "roughing",    # 默认粗加工，子阶段由 _cutting_stage 动态切换
    _State.DECEL_CYCLE: "idle",        # 周期间减速，主轴不停
    _State.DECEL:       "idle",        # 任务级降速
    _State.TOOL_CHANGE: "tool_change",
    _State.TOOL_BREAK:  "idle",
    _State.CHIP_WRAP:   "roughing",
}

# task_state 映射：process_running = 主轴保持，idle = 主轴可以停
_STATE_TO_TASK: dict[_State, str] = {
    _State.IDLE:        "idle",
    _State.SPINUP:      "process_running",
    _State.AIR_CUT:     "process_running",
    _State.CUTTING:     "process_running",
    _State.DECEL_CYCLE: "process_running",
    _State.DECEL:       "idle",
    _State.TOOL_CHANGE: "idle",
    _State.TOOL_BREAK:  "idle",
    _State.CHIP_WRAP:   "process_running",
}

# 刀塔配置（刀位号, 刀具ID）
_TOOL_TABLE = [
    (1, "T01"),   # 外圆粗车刀
    (2, "T02"),   # 外圆精车刀
    (3, "T03"),   # 切槽刀
    (4, "T04"),   # 螺纹刀
]

_NC_BLOCKS = [
    "N0010 G00 X200.0 Z50.0",
    "N0020 G96 S180 M03",
    "N0030 G00 X52.0 Z2.0",
    "N0040 G01 Z-80.0 F0.25",
    "N0050 G01 X56.0",
    "N0060 G00 Z2.0",
    "N0070 G01 X48.0",
    "N0080 G01 Z-60.0 F0.20",
    "N0090 G01 X52.0",
    "N0100 G00 X200.0 Z50.0",
    "N0110 M05",
    "N0120 M30",
]

# 每个零件的加工子阶段序列（本轮正常工况固定为 rough）
# (阶段名, 开始进度, 结束进度)
_CUT_SUBSTAGES = [
    ("roughing", 0.00, 1.00),
]


class LatheSimulator:
    """注册为 DeviceInstance 的 post_tick_hook，每次 tick 更新所有测点。"""

    def __init__(self):
        self._state = _State.IDLE
        self._state_elapsed = 0.0
        self._state_duration = 0.0

        # 主轴（状态机内部用于 CNC 信号联动）
        self._spindle_target = 0.0
        self._spindle_actual = 0.0

        # 进给（状态机内部值）
        self._feed_actual = 0.0

        # 轴位置
        self._x_pos = 150.0
        self._z_pos = 50.0

        # 刀具（只跟踪刀位）
        self._tool_idx = 0

        # 生产统计
        self._part_count = 0

        # 程序执行
        self._program_line = 0
        self._block_idx = 0

        # 故障状态
        self._condition_native_code = ""
        self._break_load_spike = 0.0
        self._wrap_load_increment = 0.0
        self._fault_cooldown = 0

        # 当前切削子阶段（roughing/semi_finishing/finishing）
        self._cutting_stage = "roughing"

        # 当前任务内已完成的切削周期数（达到上限后才真正停机）
        self._cycles_in_task = 0
        # 每个任务包含多少个切削周期（随机 3~6），到达后进入真正 IDLE
        self._cycles_per_task = random.randint(3, 6)

        # tick 计数，用于传入 BaseMetricGenerator 的 t
        self._tick_count = 0

        # 正常加工指标生成器
        self._metric_gen = BaseMetricGenerator(
            ambient_temperature=28.0,
            seed=None,   # None = 随机种子，每次实例化不同
        )

    # ------------------------------------------------------------------
    # post_tick_hook 入口
    # ------------------------------------------------------------------

    def __call__(self, device_instance: Any) -> None:
        self._tick_count += 1
        t = float(self._tick_count)   # 用 tick 序号作为时间 t（dt=1s）

        # 1. 状态机推进
        self._step_state_machine()

        # 2. 确定当前 MetricGenerator 阶段
        stage = self._get_metric_stage()

        # 3. 把状态机信息同步给 MetricGenerator
        if self._state == _State.CUTTING:
            self._metric_gen.state.cutting_total = self._state_duration

        # spindle_state 用于转速 EMA alpha 控制
        _sm_to_spindle = {
            _State.IDLE:        "idle",
            _State.SPINUP:      "spinup",
            _State.AIR_CUT:     "cutting",   # air_cut 保持转速（cutting alpha）
            _State.CUTTING:     "cutting",
            _State.DECEL_CYCLE: "cutting",   # 周期间不降速
            _State.DECEL:       "decel",
            _State.TOOL_CHANGE: "tool_change",
            _State.TOOL_BREAK:  "idle",
            _State.CHIP_WRAP:   "cutting",
        }
        self._metric_gen.state.spindle_state = _sm_to_spindle.get(self._state, "idle")

        # task_state：process_running = 主轴保持目标转速；idle = 主轴可以停
        task_state = _STATE_TO_TASK.get(self._state, "idle")
        self._metric_gen.state.task_state = task_state

        # 4. 生成正常加工 MetricFrame（含联动 + 噪声 + clamp）
        frame = self._metric_gen.generate(t=t, dt=1.0, stage=stage)

        # 5. 把 MetricFrame 写入 device._point_values（MTConnect 标准测点）
        vals = device_instance._point_values
        self._update_cnc_points(vals, frame)

        # 6. 复用铣床故障注入机制：在 baseline 写入后覆盖故障测点值
        #    fault_injector.apply() 只覆盖 _point_values，不修改状态机
        #    只有 process_running 切削阶段的故障才有意义；
        #    但 apply() 本身会检查 fault.duration，状态机不需要感知
        fault_injector.apply(device_instance)

        # ── 断刀二阶段后处理（不修改 FaultInjector 框架，符合铣床风格）───────
        _active_fault = fault_injector.get_fault(device_instance.id)
        if _active_fault is not None:
            _fault_id = _active_fault.fault_type_id
            _elapsed  = _active_fault.elapsed

            # 断刀急停：冲击窗口前 2s → 之后 load/current/speed 降到停机水平
            if _fault_id == "tool_break_emergency_stop_rough" and _elapsed > 2.0:
                vals["spindle_load"]    = round(random.uniform(0.0, 2.0), 1)
                vals["spindle_current"] = round(random.uniform(0.0, 1.0), 2)
                vals["spindle_speed"]   = 0.0

            # 断刀异常切削：冲击窗口前 2s 输出冲击峰值，之后由 FaultInjector 维持低负载
            elif _fault_id == "tool_break_broken_cutting_rough" and _elapsed <= 2.0:
                vals["spindle_load"]    = round(random.uniform(85.0, 100.0) + random.gauss(0, 3.0), 1)
                vals["spindle_current"] = round(random.uniform(18.0, 25.0) + random.gauss(0, 1.5), 2)
                # 转速在冲击瞬间保持（FaultInjector 已设置 nominal_baseline=2000，此处不覆盖）

        # 7. 上报 Prometheus（使用 fault-applied 后的 _point_values，而非注入前的 frame）
        self._emit_prometheus(device_instance, vals)

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------

    def _step_state_machine(self) -> None:
        self._state_elapsed += 1
        if self._fault_cooldown > 0:
            self._fault_cooldown -= 1

        dispatch = {
            _State.IDLE:        self._on_idle,
            _State.SPINUP:      self._on_spinup,
            _State.AIR_CUT:     self._on_air_cut,
            _State.CUTTING:     self._on_cutting,
            _State.DECEL_CYCLE: self._on_decel_cycle,
            _State.DECEL:       self._on_decel,
            _State.TOOL_CHANGE: self._on_tool_change,
            _State.TOOL_BREAK:  self._on_tool_break,
            _State.CHIP_WRAP:   self._on_chip_wrap,
        }
        dispatch[self._state]()

    def _transition(self, new_state: _State, duration: float) -> None:
        self._state = new_state
        self._state_elapsed = 0
        self._state_duration = duration

    def _get_metric_stage(self) -> str:
        """将状态机状态映射到 MetricGenerator 阶段。"""
        if self._state == _State.CUTTING:
            return "roughing"
        if self._state == _State.CHIP_WRAP:
            return "roughing"
        return _STATE_TO_STAGE.get(self._state, "idle")

    def _update_cutting_substage(self, progress: float) -> None:
        """本轮正常工况只模拟 rough，不在小周期内切换 semi/finish。"""
        self._cutting_stage = "roughing"

    def _on_idle(self) -> None:
        self._spindle_target = 0.0
        self._spindle_actual = self._smooth(self._spindle_actual, 0.0, 0.15)
        self._feed_actual = 0.0
        self._condition_native_code = ""
        self._wrap_load_increment = 0.0
        if self._state_elapsed >= self._state_duration:
            # 开始新任务：主轴升速目标转速（粗加工 2000 RPM）
            self._spindle_target = 2000.0
            self._program_line = 1
            self._block_idx = 0
            self._cutting_stage = "roughing"
            self._cycles_in_task = 0
            self._cycles_per_task = random.randint(3, 6)
            self._transition(_State.SPINUP, random.uniform(4, 8))

    def _on_spinup(self) -> None:
        self._spindle_actual = self._smooth(
            self._spindle_actual, self._spindle_target, 0.25
        )
        if self._state_elapsed >= self._state_duration:
            self._transition(_State.AIR_CUT, random.uniform(6, 12))

    def _on_air_cut(self) -> None:
        """主轴运转，快速定位，不切削。主轴转速保持目标值。"""
        noise = random.gauss(0, self._spindle_target * 0.01)
        self._spindle_actual = max(
            self._spindle_target * 0.95,
            min(self._spindle_target * 1.05, self._spindle_actual + noise),
        )
        self._feed_actual = 0.0
        # 快速移动回到起刀点
        self._x_pos = self._smooth(self._x_pos, 50.0, 0.30)
        self._z_pos = self._smooth(self._z_pos, 2.0, 0.30)
        if self._state_elapsed >= self._state_duration:
            self._transition(_State.CUTTING, random.uniform(45, 90))

    def _on_cutting(self) -> None:
        noise = random.gauss(0, self._spindle_target * 0.02)
        self._spindle_actual = max(
            self._spindle_target * 0.85,
            min(self._spindle_target * 1.05, self._spindle_actual + noise),
        )
        self._feed_actual = self._spindle_target * random.uniform(0.08, 0.15)

        progress = self._state_elapsed / max(self._state_duration, 1)
        self._z_pos = 50.0 - 350.0 * (progress % 1.0)
        self._x_pos = random.uniform(20, 60) + math.sin(progress * math.pi * 4) * 5
        self._block_idx = int(progress * len(_NC_BLOCKS)) % len(_NC_BLOCKS)
        self._program_line = (self._block_idx + 1) * 10

        # 动态切换粗/半精/精加工子阶段
        self._update_cutting_substage(progress)

        if self._fault_cooldown == 0 and progress > 0.2:
            r = random.random()
            if r < 0.004:
                self._condition_native_code = "ALM-401"
                self._break_load_spike = random.uniform(1.8, 3.0)
                self._transition(_State.TOOL_BREAK, random.uniform(3, 6))
                return
            elif r < 0.008:
                self._condition_native_code = "ALM-305"
                self._wrap_load_increment = 0.0
                self._transition(_State.CHIP_WRAP, random.uniform(15, 25))
                return

        if self._state_elapsed >= self._state_duration:
            # 周期结束：进入 DECEL_CYCLE（主轴保持转速，只停进给）
            self._transition(_State.DECEL_CYCLE, random.uniform(3, 6))

    def _on_decel_cycle(self) -> None:
        """
        周期级减速：只停进给，主轴转速保持。
        结束后：若任务周期未满，回到 AIR_CUT；若满了，进入任务级 DECEL。
        """
        self._feed_actual = self._smooth(self._feed_actual, 0.0, 0.40)
        # 主轴保持转速（微小噪声）
        noise = random.gauss(0, self._spindle_target * 0.01)
        self._spindle_actual = max(
            self._spindle_target * 0.95,
            min(self._spindle_target * 1.05, self._spindle_actual + noise),
        )
        if self._state_elapsed >= self._state_duration:
            self._cycles_in_task += 1
            self._part_count += 1
            if self._cycles_in_task >= self._cycles_per_task:
                # 任务周期完成：进行真正的降速停机
                if self._part_count % 5 == 0:
                    self._metric_gen.reset_wear()
                self._transition(_State.DECEL, random.uniform(3, 5))
            else:
                # 继续下一个切削周期：回到 AIR_CUT
                self._transition(_State.AIR_CUT, random.uniform(6, 12))

    def _on_decel(self) -> None:
        """任务级降速：主轴降到 0，准备换刀或停机。"""
        self._spindle_actual = self._smooth(self._spindle_actual, 0.0, 0.20)
        self._feed_actual = self._smooth(self._feed_actual, 0.0, 0.30)
        self._x_pos = self._smooth(self._x_pos, 150.0, 0.20)
        self._z_pos = self._smooth(self._z_pos, 50.0, 0.20)
        if self._state_elapsed >= self._state_duration:
            self._transition(_State.TOOL_CHANGE, random.uniform(4, 8))

    def _on_tool_change(self) -> None:
        self._spindle_actual = 0.0
        self._feed_actual = 0.0
        if self._state_elapsed >= self._state_duration:
            self._tool_idx = (self._tool_idx + 1) % len(_TOOL_TABLE)
            self._condition_native_code = ""
            self._transition(_State.IDLE, random.uniform(2, 4))

    def _on_tool_break(self) -> None:
        phase = self._state_elapsed / max(self._state_duration, 1)
        if phase < 0.35:
            self._spindle_actual *= (1.0 - phase * 0.2)
        else:
            self._spindle_actual = self._smooth(self._spindle_actual, 0.0, 0.45)
        self._feed_actual = 0.0
        if self._state_elapsed >= self._state_duration:
            self._fault_cooldown = 40
            self._transition(_State.TOOL_CHANGE, random.uniform(6, 10))

    def _on_chip_wrap(self) -> None:
        self._wrap_load_increment += random.uniform(2.5, 4.5)
        drag = min(self._wrap_load_increment / 200.0, 0.25)
        self._spindle_actual = max(
            0.0,
            self._spindle_target * (1.0 - drag) + random.gauss(0, 20),
        )
        feed_base = self._spindle_target * 0.10
        self._feed_actual = feed_base * (1.0 + random.uniform(-0.3, 0.1))
        effective_load = 30 + self._wrap_load_increment
        if effective_load >= 90.0 or self._state_elapsed >= self._state_duration:
            self._fault_cooldown = 30
            self._spindle_actual = self._smooth(self._spindle_actual, 0.0, 0.5)
            self._transition(_State.TOOL_CHANGE, random.uniform(5, 9))

    # ------------------------------------------------------------------
    # 写入 MTConnect 测点 + MetricFrame 测点
    # ------------------------------------------------------------------

    def _update_cnc_points(self, vals: dict[str, Any], frame) -> None:
        """
        将 MetricFrame（正常加工基础指标）与状态机（CNC 信号）合并写入测点。
        状态机负责：execution/controller_mode/e_stop/system_condition/position/tool/part_count
        MetricFrame 负责：spindle_speed/spindle_load/feed_rate/vibration/acoustic/temperature/roughness/wear
        """
        state = self._state
        is_cutting = state == _State.CUTTING
        is_air_cut = state == _State.AIR_CUT
        is_tool_break = state == _State.TOOL_BREAK
        is_chip_wrap = state == _State.CHIP_WRAP
        is_fault = is_tool_break or is_chip_wrap
        is_tool_change = state == _State.TOOL_CHANGE
        is_decel_cycle = state == _State.DECEL_CYCLE

        cur_tool_no, cur_tool_id = _TOOL_TABLE[self._tool_idx]

        # ── CNC 状态信号（来自状态机）────────────────────────────────────────
        vals["availability"] = "AVAILABLE"
        vals["e_stop"] = "TRIGGERED" if is_fault else "ARMED"
        vals["system_condition"] = "FAULT" if is_fault else "NORMAL"
        vals["condition_native_code"] = self._condition_native_code

        if is_fault:
            vals["execution"] = "STOPPED"
            vals["controller_mode"] = "MANUAL"
        elif is_tool_change:
            vals["execution"] = "WAIT"
            vals["controller_mode"] = "AUTOMATIC"
        elif state == _State.IDLE:
            vals["execution"] = "READY"
            vals["controller_mode"] = "AUTOMATIC"
        elif is_air_cut or is_decel_cycle:
            vals["execution"] = "ACTIVE"
            vals["controller_mode"] = "AUTOMATIC"
        else:
            vals["execution"] = "ACTIVE"
            vals["controller_mode"] = "AUTOMATIC"

        vals["program"] = "O0001" if not is_fault else "O0000"
        vals["block"] = _NC_BLOCKS[self._block_idx] if is_cutting else ""
        vals["line"] = self._program_line
        vals["x_position"] = round(self._x_pos, 3)
        vals["z_position"] = round(self._z_pos, 3)
        vals["tool_id"] = cur_tool_id
        vals["tool_number"] = cur_tool_no
        vals["part_count"] = self._part_count

        # ── 主轴方向（由状态机内部转速决定）────────────────────────────────
        vals["spindle_direction"] = "STOPPED" if self._spindle_actual < 10 else "CW"
        vals["spindle_override"] = 100.0
        vals["feed_override"] = 100.0
        vals["rapid_override"] = 100.0

        # ── MetricFrame 基础指标 ─────────────────────────────────────────────
        vals["spindle_speed"]      = round(frame.spindle_speed, 1)
        vals["spindle_load"]       = round(frame.spindle_load, 1)
        vals["spindle_current"]    = round(frame.spindle_current, 2)
        vals["feed_rate"]          = round(frame.feed_rate, 1)
        vals["vibration_x"]        = round(frame.vibration_x, 4)
        vals["vibration_y"]        = round(frame.vibration_y, 4)
        vals["vibration_z"]        = round(frame.vibration_z, 4)
        vals["acoustic_emission"]  = round(frame.acoustic_emission, 4)
        vals["tool_temperature"]   = round(frame.tool_temperature, 2)
        vals["surface_roughness"]  = round(frame.surface_roughness, 3)
        vals["tool_wear_value"]    = round(frame.tool_wear_value, 4)
        # 存入 stage 供 _emit_prometheus 使用（不作为 MTConnect 测点上报）
        vals["_stage"]             = frame.stage

        # 故障覆盖：崩刀时 spindle_load 突增并覆盖 MetricFrame 的值
        if is_tool_break:
            phase = self._state_elapsed / max(self._state_duration, 1)
            spike = self._break_load_spike if phase < 0.35 else 1.0
            overload = min(100.0, frame.spindle_load * spike)
            vals["spindle_load"] = round(overload, 1)

        # 缠屑覆盖：负载爬升覆盖 MetricFrame 的值
        if is_chip_wrap:
            wrap_load = min(100.0, 30.0 + self._wrap_load_increment + random.gauss(0, 2))
            vals["spindle_load"] = round(wrap_load, 1)

    def _emit_prometheus(self, device_instance: Any, vals: dict) -> None:
        """
        通过 MetricsCollector 上报 Prometheus 指标。
        使用 fault-applied 后的 device._point_values，确保故障覆盖值能正确上报。
        复用项目已有的 set_gauge 接口，不重复注册。
        """
        try:
            from protoforge.core.metrics import metrics
        except ImportError:
            return

        device_id = getattr(device_instance.config, "id", "unknown")
        device_name = getattr(device_instance.config, "name", "unknown")
        # stage 仍从 frame 获取（故障不改变 stage 标签）
        stage = vals.get("_stage", "roughing")
        labels = {
            "device_id":   device_id,
            "device_name": device_name,
            "protocol":    "mtconnect",
            "stage":       stage,
        }

        metrics.set_gauge("cnc_feed_rate",          vals.get("feed_rate", 0.0),         {**labels, "unit": "mm/min"})
        metrics.set_gauge("cnc_spindle_speed",       vals.get("spindle_speed", 0.0),     {**labels, "unit": "RPM"})
        metrics.set_gauge("cnc_spindle_current",     vals.get("spindle_current", 0.0),   {**labels, "unit": "A"})
        metrics.set_gauge("cnc_spindle_load",        vals.get("spindle_load", 0.0),      {**labels, "unit": "%"})
        metrics.set_gauge("cnc_vibration_x",         vals.get("vibration_x", 0.0),       {**labels, "unit": "mm/s"})
        metrics.set_gauge("cnc_vibration_y",         vals.get("vibration_y", 0.0),       {**labels, "unit": "mm/s"})
        metrics.set_gauge("cnc_vibration_z",         vals.get("vibration_z", 0.0),       {**labels, "unit": "mm/s"})
        metrics.set_gauge("cnc_acoustic_emission",   vals.get("acoustic_emission", 0.0), {**labels, "unit": "V"})
        metrics.set_gauge("cnc_tool_temperature",    vals.get("tool_temperature", 0.0),  {**labels, "unit": "C"})
        metrics.set_gauge("cnc_surface_roughness",   vals.get("surface_roughness", 0.0), {**labels, "unit": "um"})
        metrics.set_gauge("cnc_tool_wear_value",     vals.get("tool_wear_value", 0.0),   {**labels, "unit": "um"})

    # ------------------------------------------------------------------

    @staticmethod
    def _smooth(current: float, target: float, rate: float) -> float:
        return current + (target - current) * rate
