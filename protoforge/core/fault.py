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
    # 进给堵转（粗铣）— fanuc-cnc
    # 量程：spindle_speed~2000RPM, feed_rate~800mm/min,
    #        spindle_current~21A, spindle_load~56%
    # 堵转目标：load→85~100%, current→34~42A，转速维持+轻微抖动
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="feed_stall_rough",
        name="进给堵转（粗铣）",
        description="粗铣进给轴卡死，进给速率降为零，主轴负载升至85~100%，电流升至34~42A，主轴转速维持（区别于崩刃停主轴）",
        category="process",
        default_duration=20.0,
        tags=["进给", "堵转", "突发", "粗铣"],
        point_faults=[
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=85.0, target_max=100.0, noise_scale=4.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=34.0, target_max=42.0, noise_scale=1.5),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=30.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 进给堵转（半精铣）— fanuc-cnc-semi-finish
    # 量程：spindle_speed~4000RPM, feed_rate~500mm/min,
    #        spindle_current~14.5A, spindle_load~38%
    # 堵转目标：load→62~75%, current→23~29A，转速维持+轻微抖动
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="feed_stall_semi",
        name="进给堵转（半精铣）",
        description="半精铣进给轴卡死，进给速率降为零，主轴负载升至62~75%，电流升至23~29A，主轴转速维持（区别于崩刃停主轴）",
        category="process",
        default_duration=20.0,
        tags=["进给", "堵转", "突发", "半精铣"],
        point_faults=[
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=62.0, target_max=75.0, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=23.0, target_max=29.0, noise_scale=1.2),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=50.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 进给堵转（精铣）— fanuc-cnc-finish
    # 量程：spindle_speed~6000RPM, feed_rate~300mm/min,
    #        spindle_current~8.5A, spindle_load~22%
    # 堵转目标：load→36~45%, current→13~17A，转速维持+轻微抖动
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="feed_stall_finish",
        name="进给堵转（精铣）",
        description="精铣进给轴卡死，进给速率降为零，主轴负载升至36~45%，电流升至13~17A，主轴转速维持（区别于崩刃停主轴）",
        category="process",
        default_duration=20.0,
        tags=["进给", "堵转", "突发", "精铣"],
        point_faults=[
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=36.0, target_max=45.0, noise_scale=2.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=13.0, target_max=17.0, noise_scale=0.8),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=80.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴过热（粗铣）— fanuc-cnc
    # 基线：spindle_speed~2000RPM, spindle_current~21A, spindle_load~56%
    # 过热目标范围：load 78~92%，current 30~38A，转速降至 1200~1600RPM
    # 范围模拟不同冷却状态、负荷历史、环境温度下的个体差异
    # 模式：渐进式；全部用 target_min/max，避免 multiplier 在空载基线=0 时失效
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_overheat_rough",
        name="主轴过热（粗铣）",
        description="粗铣主轴长时间高负荷或冷却不足，spindle_load渐进升至78~92%，spindle_current升至30~38A，转速因热保护渐进降至1200~1600RPM",
        category="thermal",
        default_duration=240.0,
        tags=["主轴", "过热", "渐进", "粗铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             target_min=78.0, target_max=92.0, noise_scale=3.5),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             target_min=30.0, target_max=38.0, noise_scale=1.5),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             target_min=1200, target_max=1600, noise_scale=40.0,
                             nominal_baseline=2000.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴过热（半精铣）— fanuc-cnc-semi-finish
    # 基线：spindle_speed~4000RPM, spindle_current~14.5A, spindle_load~38%
    # 过热目标范围：load 65~78%，current 21~27A，转速降至 2400~2900RPM
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_overheat_semi",
        name="主轴过热（半精铣）",
        description="半精铣主轴长时间高负荷或冷却不足，spindle_load渐进升至65~78%，spindle_current升至21~27A，转速因热保护渐进降至2400~2900RPM",
        category="thermal",
        default_duration=240.0,
        tags=["主轴", "过热", "渐进", "半精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             target_min=65.0, target_max=78.0, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             target_min=21.0, target_max=27.0, noise_scale=1.2),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             target_min=2400, target_max=2900, noise_scale=50.0,
                             nominal_baseline=4000.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 主轴过热（精铣）— fanuc-cnc-finish
    # 基线：spindle_speed~6000RPM, spindle_current~8.5A, spindle_load~22%
    # 过热目标范围：load 42~55%，current 13~17A，转速降至 3600~4200RPM
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="spindle_overheat_finish",
        name="主轴过热（精铣）",
        description="精铣主轴长时间高负荷或冷却不足，spindle_load渐进升至42~55%，spindle_current升至13~17A，转速因热保护渐进降至3600~4200RPM",
        category="thermal",
        default_duration=240.0,
        tags=["主轴", "过热", "渐进", "精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             target_min=42.0, target_max=55.0, noise_scale=2.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             target_min=13.0, target_max=17.0, noise_scale=0.8),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             target_min=3600, target_max=4200, noise_scale=60.0,
                             nominal_baseline=6000.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 电源波动（粗铣）— fanuc-cnc
    # 主轴~2000RPM，进给~800mm/min
    # 转速噪声 ±200 RPM（±10%），进给噪声 ±80 mm/min（±10%），电流噪声 ±3A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="power_fluctuation_rough",
        name="电源波动（粗铣）",
        description="粗铣工位供电电压不稳定，主轴转速出现随机波动（±200RPM），进给速率抖动（±80mm/min），电流不稳定",
        category="electrical",
        default_duration=90.0,
        tags=["电源", "波动", "突发", "粗铣"],
        point_faults=[
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=200.0, nominal_baseline=2000.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=3.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=80.0, nominal_baseline=800.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 电源波动（半精铣）— fanuc-cnc-semi-finish
    # 主轴~4000RPM，进给~300mm/min
    # 转速噪声 ±300 RPM（±7.5%），进给噪声 ±25 mm/min（±8%），电流噪声 ±2A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="power_fluctuation_semi",
        name="电源波动（半精铣）",
        description="半精铣工位供电电压不稳定，主轴转速出现随机波动（±300RPM），进给速率抖动（±25mm/min），电流不稳定",
        category="electrical",
        default_duration=90.0,
        tags=["电源", "波动", "突发", "半精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=300.0, nominal_baseline=4000.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=2.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=25.0, nominal_baseline=300.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 电源波动（精铣）— fanuc-cnc-finish
    # 主轴~6000RPM，进给~300mm/min
    # 转速噪声 ±450 RPM（±7.5%），进给噪声 ±25 mm/min（±8%），电流噪声 ±1.2A
    # 精铣对稳定性要求高，波动对加工质量影响更敏感
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="power_fluctuation_finish",
        name="电源波动（精铣）",
        description="精铣工位供电电压不稳定，主轴转速出现随机波动（±450RPM），进给速率抖动（±25mm/min），电流不稳定；精铣对稳定性要求高，波动易导致表面质量下降",
        category="electrical",
        default_duration=90.0,
        tags=["电源", "波动", "突发", "精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=450.0, nominal_baseline=6000.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=1.2),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=25.0, nominal_baseline=300.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具磨损加剧 — 主轴负载趋势漂移
    # 特征：spindle_load 基线随时间缓慢爬升（趋势漂移型），电流同步升高
    # 场景：刀具从轻度磨损到需要换刀的完整过程
    # 模式：渐进式，持续时间长
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 刀具磨损加剧（粗铣）
    # 切削段基线：spindle_load~54%, spindle_current~20A
    # 目标：load×1.8→97%, current×1.7→34A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear_progressive_rough",
        name="刀具磨损加剧（粗铣）",
        description="粗铣刀具磨损导致切削阻力持续增大，spindle_load渐进爬升至1.8倍（~97%），spindle_current升至1.7倍（~34A）",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "磨损", "负载", "趋势漂移", "粗铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_ratio=0.05, nominal_baseline=54.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.7, noise_ratio=0.05, nominal_baseline=20.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具磨损加剧（半精铣）
    # 切削段基线：spindle_load~33%, spindle_current~13.5A
    # 目标：load×1.8→59%, current×1.7→23A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear_progressive_semi",
        name="刀具磨损加剧（半精铣）",
        description="半精铣刀具磨损导致切削阻力持续增大，spindle_load渐进爬升至1.8倍（~59%），spindle_current升至1.7倍（~23A）",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "磨损", "负载", "趋势漂移", "半精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_ratio=0.05, nominal_baseline=33.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.7, noise_ratio=0.05, nominal_baseline=13.5),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具磨损加剧（精铣）
    # 切削段基线：spindle_load~22%, spindle_current~8.8A
    # 目标：load×1.8→40%, current×1.7→15A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear_progressive_finish",
        name="刀具磨损加剧（精铣）",
        description="精铣刀具磨损导致切削阻力持续增大，spindle_load渐进爬升至1.8倍（~40%），spindle_current升至1.7倍（~15A）；精铣对负载变化敏感，易影响表面质量",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "磨损", "负载", "趋势漂移", "精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             multiplier=1.8, noise_ratio=0.05, nominal_baseline=22.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             multiplier=1.7, noise_ratio=0.05, nominal_baseline=8.8),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具崩刃（粗铣）— fanuc-cnc
    # 正常切削基线：spindle_load~56%, spindle_current~21A
    # 崩刃特征：load 瞬间冲高至 160~185%（FANUC 最大输出200%），
    #            current 冲至 75~90A，转速/进给归零，触发过载报警
    # 使用绝对目标值（target_min/max），避免注入时恰好处于低电流阶段
    # 导致 multiplier × 低基线 < 正常切削峰值的问题
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_breakage_rough",
        name="刀具崩刃（粗铣）",
        description="粗铣刀具突发性崩刃，spindle_load瞬间冲高至160~185%，spindle_current冲至75~90A，进给停止，CNC触发过载报警并停主轴",
        category="tool",
        default_duration=10.0,
        tags=["刀具", "崩刃", "突发", "过载", "粗铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=160.0, target_max=185.0, noise_scale=8.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=75.0, target_max=90.0, noise_scale=3.0),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="alarm_status", mode=FaultMode.INSTANT,
                             target_value=1.0, noise_scale=0.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具崩刃（半精铣）— fanuc-cnc-semi-finish
    # 正常切削基线：spindle_load~38%, spindle_current~14.5A
    # 崩刃特征：load 瞬间冲高至 120~145%，current 冲至 52~64A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_breakage_semi",
        name="刀具崩刃（半精铣）",
        description="半精铣刀具突发性崩刃，spindle_load瞬间冲高至120~145%，spindle_current冲至52~64A，进给停止，CNC触发过载报警并停主轴",
        category="tool",
        default_duration=10.0,
        tags=["刀具", "崩刃", "突发", "过载", "半精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=120.0, target_max=145.0, noise_scale=6.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=52.0, target_max=64.0, noise_scale=2.5),
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="feed_rate", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
            PointFaultConfig(point="alarm_status", mode=FaultMode.INSTANT,
                             target_value=1.0, noise_scale=0.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具崩刃（精铣）— fanuc-cnc-finish
    # 正常切削基线：spindle_load~22%, spindle_current~8.5A
    # 崩刃特征：load 瞬间冲高至 70~90%，current 冲至 30~40A
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_breakage_finish",
        name="刀具崩刃（精铣）",
        description="精铣刀具突发性崩刃，spindle_load瞬间冲高至70~90%，spindle_current冲至30~40A，进给停止，CNC触发过载报警并停主轴",
        category="tool",
        default_duration=10.0,
        tags=["刀具", "崩刃", "突发", "过载", "精铣"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=70.0, target_max=90.0, noise_scale=4.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=30.0, target_max=40.0, noise_scale=1.5),
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
        description="刀具未接触工件，spindle_load跌至空载区间(4-12%)，spindle_current降至空转水平，转速进给保持正常",
        category="tool",
        default_duration=180.0,
        tags=["刀具", "空切", "工况切换", "负载"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=4.0, target_max=12.0, noise_scale=2.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=2.0, target_max=3.5, noise_scale=0.3),
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

    # ==================================================================
    # 车床 CNC Rough 粗车故障类型
    # 基线：spindle_speed~2000RPM, spindle_load cutting~55%, spindle_current cutting~13A
    # 仅影响 spindle_speed / spindle_load / spindle_current 三个测点
    # ==================================================================

    # ------------------------------------------------------------------
    # 缠屑（车床粗车）— chip_entanglement_rough
    # 物理含义：切屑缠绕刀具/工件，切削阻力逐步增大
    # 特征：spindle_load/current 渐进爬升，spindle_speed 基本维持（严重时轻微下降）
    # 模式：GRADUAL（渐进式），区别于崩刃的瞬间冲击
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="chip_entanglement_rough",
        name="缠屑（车床粗车）",
        description="车床粗车切屑缠绕刀具/工件，切削阻力逐步增大。spindle_load渐进从~55%爬升到70~90%，spindle_current从~13A升至16~20A，spindle_speed基本维持2000RPM（严重时轻微下降到1900RPM）。区别于缠屑：不瞬间冲击；区别于磨损：爬升更快且波动更大",
        category="process",
        default_duration=180.0,
        tags=["缠屑", "渐进", "车床", "粗车"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             target_min=70.0, target_max=90.0, noise_scale=4.5),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             target_min=16.0, target_max=20.0, noise_scale=1.2),
            # 转速只在严重时（progress > 0.6）才轻微下降，nominal_baseline 保持 2000
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             target_min=1880.0, target_max=1950.0, noise_scale=25.0,
                             nominal_baseline=2000.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 刀具磨损（车床粗车）— tool_wear_rough
    # 物理含义：刀具逐步变钝，切削阻力慢性增加
    # 特征：load/current 长时间缓慢趋势性上升，转速基本稳定
    # 模式：GRADUAL，持续时间长（600s），不应瞬间恢复
    # 使用 nominal_baseline 避免注入时恰好在空切段导致基线失真
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_wear_rough",
        name="刀具磨损（车床粗车）",
        description="车床粗车刀具逐步变钝，切削阻力慢性增加。spindle_load从~55%缓慢抬升到60~75%，spindle_current从~13A抬升到13~16A，spindle_speed基本稳定在2000RPM。区别于缠屑：爬升极慢；区别于崩刃：无冲击峰值，不停主轴",
        category="tool",
        default_duration=600.0,
        tags=["刀具", "磨损", "渐进", "车床", "粗车", "趋势漂移"],
        point_faults=[
            PointFaultConfig(point="spindle_load", mode=FaultMode.GRADUAL,
                             target_min=60.0, target_max=75.0, noise_ratio=0.04,
                             nominal_baseline=55.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.GRADUAL,
                             target_min=13.0, target_max=16.0, noise_ratio=0.04,
                             nominal_baseline=13.0),
            # 磨损对转速影响极小，仅在严重时轻微下降，nominal_baseline 保持 2000
            PointFaultConfig(point="spindle_speed", mode=FaultMode.GRADUAL,
                             target_min=1930.0, target_max=1990.0, noise_scale=20.0,
                             nominal_baseline=2000.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 断刀/崩刀 emergency_stop（车床粗车）— tool_break_emergency_stop_rough
    # 物理含义：刀具突然断裂，CNC 触发紧急停机
    # 特征：瞬间冲击后 load/current 归零，spindle_speed 急降到 0
    # 模式：INSTANT，持续时间短（仅代表报警持续窗口），之后停机
    # 断刀冲击只触发一次（注入时随机采样 resolved_target），不每 tick 重新冲击
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_break_emergency_stop_rough",
        name="断刀急停（车床粗车）",
        description="车床粗车刀具突然断裂，CNC触发紧急停机。spindle_load瞬间冲高到85~100%，spindle_current冲高到18~25A，随后（下一tick）主轴急停到0。断刀冲击只触发一次，之后进入停机等待状态，不自动恢复正常切削",
        category="tool",
        default_duration=8.0,
        tags=["断刀", "崩刀", "急停", "突发", "车床", "粗车"],
        point_faults=[
            # 瞬间冲高，noise_scale 小（冲击值已由 target_min/max 精确控制）
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=85.0, target_max=100.0, noise_scale=3.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=18.0, target_max=25.0, noise_scale=1.5),
            # 主轴急停到 0
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             target_value=0.0, noise_scale=0.0),
        ],
    ),

    # ------------------------------------------------------------------
    # 断刀/崩刀 broken_cutting（车床粗车）— tool_break_broken_cutting_rough
    # 物理含义：刀具断裂但主轴未停，在破损刀具状态下继续异常切削
    # 特征：瞬间冲击后 load/current 降到低位（破损刀具切不动），转速维持
    # 模式：INSTANT，持续时间短（8s 冲击窗口）+ 后续低负载异常阶段
    # ------------------------------------------------------------------
    FaultTypeDefinition(
        id="tool_break_broken_cutting_rough",
        name="断刀异常切削（车床粗车）",
        description="车床粗车刀具断裂但主轴未停，破损刀具继续异常切削。spindle_load瞬间冲高到85~100%后降至5~15%，spindle_current冲高到18~25A后降至3~6A，spindle_speed维持1800~2200RPM不停机。区别于急停：主轴不归零",
        category="tool",
        default_duration=8.0,
        tags=["断刀", "崩刀", "异常切削", "突发", "车床", "粗车"],
        point_faults=[
            # 冲击后维持低负载（破损刀具切不动）
            PointFaultConfig(point="spindle_load", mode=FaultMode.INSTANT,
                             target_min=5.0, target_max=15.0, noise_scale=2.0),
            PointFaultConfig(point="spindle_current", mode=FaultMode.INSTANT,
                             target_min=3.0, target_max=6.0, noise_scale=0.8),
            # 转速维持，nominal_baseline 避免注入时基线失真
            PointFaultConfig(point="spindle_speed", mode=FaultMode.INSTANT,
                             multiplier=1.0, noise_scale=30.0, nominal_baseline=2000.0),
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

        # 对有范围定义的测点，注入时随机采样一个实际目标值
        # 使每次注入的故障严重程度有所不同，模拟真实场景的个体差异
        resolved_targets: dict[str, float] = {}
        for pf in fault_type.point_faults:
            if pf.target_min is not None and pf.target_max is not None:
                resolved_targets[pf.point] = random.uniform(pf.target_min, pf.target_max)

        fault = ActiveFault(
            fault_id=uuid.uuid4().hex[:12],
            device_id=device.id,
            fault_type_id=fault_type.id,
            fault_type_name=fault_type.name,
            intensity=max(0.0, min(1.0, request.intensity)),
            duration=duration,
            started_at=time.time(),
            baseline_values=baseline,
            resolved_targets=resolved_targets,
        )
        self._active[device.id] = fault
        logger.info("Fault injected: device=%s type=%s duration=%.0fs resolved_targets=%s",
                    device.id, fault_type.id, duration, resolved_targets)
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
            # INSTANT + multiplier 模式：每 tick 取设备当前值作为动态基线。
            # 这样程序运行中电流/负载自然变化时，故障倍数始终基于实时水位，
            # 避免注入时恰好在低峰导致 multiplier × 旧低基线 < 正常高峰的问题。
            # resolved_targets（绝对值）和 target_value 模式不受影响，保持原逻辑。
            if (pf.mode == FaultMode.INSTANT
                    and pf.multiplier is not None
                    and pf.target_value is None
                    and pf.point not in fault.resolved_targets
                    and pf.nominal_baseline is None):
                live_val = device._point_values.get(pf.point)
                if live_val is not None:
                    try:
                        fault.baseline_values[pf.point] = float(live_val)
                    except (TypeError, ValueError):
                        pass
            baseline = fault.baseline_values.get(pf.point, 0.0)
            if baseline == 0.0 and pf.nominal_baseline is None:
                # 基线为0说明注入时设备处于换刀/停机状态
                # target_value / resolved_targets 模式可以直接执行
                # multiplier 模式跳过，避免在零基线上产生无意义的值
                # 例外：配置了 nominal_baseline 时使用额定值，不跳过
                if pf.target_value is None and pf.point not in fault.resolved_targets:
                    continue

            resolved_target = fault.resolved_targets.get(pf.point)
            device._point_values[pf.point] = self._compute_value(
                pf, baseline, progress, fault.intensity, resolved_target
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
        resolved_target: Optional[float] = None,
    ) -> float:
        """根据故障配置和当前进度计算覆盖值。

        目标值优先级：resolved_target（注入时随机采样）> target_value（固定值）> multiplier
        """
        # 确定本次注入的实际目标值
        effective_target: Optional[float] = resolved_target if resolved_target is not None else pf.target_value

        # 如果配置了额定基线，使用它替代注入时采样的瞬时值
        # 避免在升/降速等非稳态阶段注入时，基线偏低导致渐进目标反而高于基线（转速"上升"bug）
        effective_baseline = pf.nominal_baseline if pf.nominal_baseline is not None else baseline

        if pf.mode == FaultMode.INSTANT:
            if effective_target is not None:
                target = effective_target
            elif pf.multiplier is not None:
                target = effective_baseline * (1.0 + (pf.multiplier - 1.0) * intensity)
            else:
                target = effective_baseline
        else:
            # 渐进模式：随 progress 线性劣化
            if effective_target is not None:
                target = effective_baseline + (effective_target - effective_baseline) * progress * intensity
            elif pf.multiplier is not None:
                target = effective_baseline * (1.0 + (pf.multiplier - 1.0) * progress * intensity)
            else:
                target = effective_baseline

        # 叠加随机噪声，模拟真实信号抖动
        # noise_ratio > 0 时按 effective_baseline 比例计算噪声幅度，否则使用绝对值 noise_scale
        if pf.noise_ratio > 0:
            target += random.gauss(0, pf.noise_ratio * effective_baseline * intensity)
        elif pf.noise_scale > 0:
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
