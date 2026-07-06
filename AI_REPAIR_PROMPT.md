# ProtoForge 仿真平台完整化修复 — AI 执行提示语

> **用途**: 将本文件内容粘贴给 AI 编程助手，引导其分阶段完成 ProtoForge 从"协议模拟器"到"工业设备仿真平台"的全部改造。
>
> **前提**: AI 已阅读 `仿真平台深度分析报告.md`、`ANALYSIS_REPORT.md` 和 `ProtoForge_完整化修复提示语.md`。

---

## 0. 项目背景与技术栈

- **语言**: Python 3.12+ / Vue 3 + Vite
- **框架**: FastAPI (后端) / Vue 3 + Element Plus (前端)
- **包管理**: pyproject.toml (Poetry 风格)
- **现有协议**: 17 种工业协议 (Modbus TCP/RTU, S7, OPC-UA, BACnet, MQTT, GB28181, FINS, MC, AB, Profinet, EtherCAT, Fanuc, MTConnect, OPC-DA, HTTP REST, Toledo)
- **项目根目录**: `e:\硕腾网络\PyGBSentry\ProtoForge`

---

## 1. 当前已完成的模块（不要重写，只需集成）

以下模块已经实现并可用，后续任务只需要**集成**和**扩展**它们：

### 1.1 物理行为模型库 ✅

**文件**: `protoforge/core/behavior_models.py` (已实现，1103 行)

已包含 7 种物理模型，均继承 `BaseBehavior`：
- `ThermalBehavior` — 热力学模型 (dT/dt = (P - hΔT)/(mc))
- `MotorBehavior` — 电机模型 (J·dω/dt = T - bω)，含堵转检测
- `PressureBehavior` — 压力传感器 (二阶阻尼系统)
- `FlowBehavior` — 流量计 (脉动流 + 精度误差 + 累积)
- `LevelBehavior` — 液位/储罐 (质量守恒 dL/dt = (Qin-Qout)/A)
- `ValveBehavior` — 阀门 (死区 + 滞回 + 行程延迟)
- `PIDController` — PID 控制器 (抗积分饱和 + 微分先行 + 输出限幅)

工厂注册表: `BEHAVIOR_REGISTRY` 字典，`create_behavior(config)` 工厂函数。

### 1.2 设备状态机引擎 ✅

**文件**: `protoforge/core/state_machine.py` (已实现，620 行)

- 7 种状态: `STOP`, `RUN`, `ERROR`, `PROGRAM`, `MAINTENANCE`, `STARTING`, `STOPPING`
- 内置标准转换规则 (start → startup_complete → stop → fault → reset → maintenance → program)
- 条件守卫、状态进入/退出回调、转换通知回调
- 状态历史记录 (deque, 可配置最大条数)
- `get_quality_for_state()` 返回质量字符串映射
- `device_state_to_status()` 向后兼容映射到 `DeviceStatus`

### 1.3 设备实例已集成状态机 ✅

**文件**: `protoforge/core/device.py`

- `DeviceInstance` 已持有 `_state_machine: DeviceStateMachine`
- `start()` / `stop()` / `fault()` / `reset()` 方法已实现
- STOP 状态可配置归零，ERROR 状态设置安全值
- `device_state` 属性返回详细状态，`status` 属性向后兼容
- `read_point()` 已返回 `PointValue`（含 `quality: str` 字段）

### 1.4 数据模型已扩展 ✅

**文件**: `protoforge/models/device.py`

- `GeneratorType` 已新增 `PHYSICAL = "physical"`
- `PointValue` 已包含 `quality: str = "good"` 和 `timestamp: float`
- `PointConfig` 已支持 `generator_config: dict` 用于物理模型参数

---

## 2. 待完成任务清单

### Phase 1: 核心集成 — 让已有模块真正运转

#### 任务 1.1: 将物理模型集成到数据生成流水线

**问题**: `behavior_models.py` 已实现，但 `DynamicValueGenerator` (在 `protoforge/protocols/behavior.py`) 尚未调用物理模型。`GeneratorType.PHYSICAL` 枚举值已存在但 `generate()` 方法中没有对应分支。

**修改文件**: `protoforge/protocols/behavior.py`

**要求**:

1. 在 `DynamicValueGenerator` 的 `generate()` 方法中添加 `PHYSICAL` 分支：
   ```python
   elif gt == GeneratorType.PHYSICAL:
       return self._generate_physical()
   ```

2. 实现 `_generate_physical()` 方法：
   - 从 `self._point.generator_config` 中读取 `behavior` 类型 (如 "thermal", "motor") 和 `params`
   - 调用 `create_behavior(config)` 创建行为模型实例 (首次调用时缓存)
   - 从 `generator_config` 中读取 `input` (输入值) 和 `dt` (时间步长)
   - 调用 `behavior.update(input, dt)` 获取输出
   - 通过 `self._clamp()` 限制输出范围
   - 支持多变量耦合: 如果配置了 `coupling` 列表，从其他点位的最新值读取输入

3. 在 `DynamicValueGenerator.__init__()` 中初始化物理模型缓存：
   ```python
   self._behavior_model: BaseBehavior | None = None
   self._behavior_input_key: str | None = None
   ```

4. 确保物理模型在设备 `tick()` 时被调用（而非每次 `read_point()` 时重复调用），避免一个 tick 内多次推进物理模型。

**验收**: 配置一个使用 `generator_type: "physical"` 的点位，generator_config 为 `{"behavior": "thermal", "params": {"mass": 2, "specific_heat": 900, "heat_transfer_coeff": 15, "ambient_temp": 25}, "input": 500, "dt": 0.1}`，读到的值应随时间呈现热惯性上升曲线，而非固定值。

---

#### 任务 1.2: 实现故障注入引擎

**需要创建的文件**:
```
protoforge/core/fault/
├── __init__.py
├── models.py       # 故障数据模型
├── injector.py     # 故障注入器
└── propagation.py  # 故障传播链
```

**`models.py` 要求**:
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

class FaultType(str, Enum):
    SENSOR_STUCK = "sensor_stuck"           # 传感器卡死
    SENSOR_DRIFT = "sensor_drift"           # 传感器漂移
    SENSOR_NOISE = "sensor_noise"           # 噪声增大
    SENSOR_FAILURE = "sensor_failure"       # 完全失效
    COMM_INTERMITTENT = "comm_intermittent" # 间歇断连
    COMM_DELAY = "comm_delay"               # 通信延迟
    COMM_LOSS = "comm_loss"                 # 丢包
    DEVICE_FAILURE = "device_failure"       # 设备故障
    ACTUATOR_STUCK = "actuator_stuck"       # 执行器卡死

class FaultSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Fault:
    fault_id: str
    fault_type: FaultType
    target: str                          # device_id 或 point_name
    start_time: float = 0.0
    duration: float = -1.0              # -1 = 永久
    severity: FaultSeverity = FaultSeverity.MEDIUM
    parameters: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    last_value: Any = None              # 卡死故障用
    drift_accumulated: float = 0.0      # 漂移故障用
```

**`injector.py` 要求**:
```python
class FaultInjector:
    def __init__(self):
        self.active_faults: list[Fault] = []
        self.fault_history: list[Fault] = []

    def add_fault(self, fault: Fault) -> str: ...
    def remove_fault(self, fault_id: str) -> bool: ...
    def clear_faults(self, target: str | None = None) -> int: ...
    def list_faults(self, target: str | None = None) -> list[Fault]: ...

    def apply(self, point_name: str, value: Any) -> tuple[Any, str]:
        """应用故障效果，返回 (修改后的值, 质量标记)"""
        # 1. 检查该点位是否有活跃故障
        # 2. 依次应用每个故障效果:
        #    - SENSOR_STUCK: 返回 last_value，质量="uncertain"
        #    - SENSOR_DRIFT: value += drift_accumulated += rate * dt，质量="uncertain"
        #    - SENSOR_NOISE: value += gauss(0, noise_level)，质量="uncertain"
        #    - SENSOR_FAILURE: 返回超量程值或 None，质量="bad"
        # 3. 检查故障是否过期 (duration > 0 且已超时)
        # 4. 返回修改后的值和质量标记
        ...

    def check_comm_fault(self, device_id: str) -> tuple[bool, float]:
        """检查通信故障，返回 (是否断连, 延迟毫秒)"""
        ...
```

**`propagation.py` 要求**:
```python
class FaultPropagation:
    """故障传播链管理"""
    def __init__(self):
        self.propagation_rules: list[dict] = []
        # 规则格式: {"source_point": "bearing_temp", "target_point": "vibration",
        #            "condition": ">80", "delay": 30, "effect": "increase_20%"}

    def add_rule(self, source: str, target: str, condition: str,
                 delay: float, effect_type: str, effect_params: dict): ...

    def check_propagation(self, point_values: dict[str, Any]) -> list[dict]:
        """检查是否有故障需要传播，返回需要触发的故障列表"""
        ...
```

**集成到 `DeviceInstance`**:
- 在 `protoforge/core/device.py` 的 `DeviceInstance.__init__()` 中添加 `self._fault_injector = FaultInjector()`
- 修改 `read_point()` 方法：生成原始值后调用 `self._fault_injector.apply(point_name, value)`，用返回的值和质量替换
- 添加 `inject_fault()`, `remove_fault()`, `list_faults()` 公开方法
- 通信故障在协议层检查: 协议 server 在响应请求前调用 `device._fault_injector.check_comm_fault(device_id)`

---

#### 任务 1.3: 完善数据质量系统

**问题**: 当前 `PointValue.quality` 是字符串类型 ("good"/"bad"/"uncertain"/"out_of_service")，但缺乏完整的 OPC UA Quality Code 支持和质量自动计算。

**需要创建的文件**: `protoforge/core/quality.py`

**要求**:

```python
from enum import IntEnum

class QualityCode(IntEnum):
    """OPC UA 数据质量码"""
    GOOD = 0x00000000
    GOOD_LOCAL_OVERRIDE = 0x00010000
    UNCERTAIN = 0x40000000
    UNCERTAIN_LAST_USABLE = 0x40440000
    UNCERTAIN_SENSOR_NOT_ACCURATE = 0x40500000
    BAD = 0x80000000
    BAD_CONFIGURATION_ERROR = 0x80080000
    BAD_NOT_CONNECTED = 0x800C0000
    BAD_DEVICE_FAILURE = 0x80100000
    BAD_SENSOR_FAILURE = 0x80140000
    BAD_OUT_OF_SERVICE = 0x801C0000
    BAD_COMMUNICATION_ERROR = 0x80180000

class QualitySystem:
    """数据质量自动计算系统"""

    @staticmethod
    def from_string(quality_str: str) -> QualityCode:
        """将字符串质量映射为 QualityCode"""
        mapping = {
            "good": QualityCode.GOOD,
            "bad": QualityCode.BAD,
            "uncertain": QualityCode.UNCERTAIN,
            "out_of_service": QualityCode.BAD_OUT_OF_SERVICE,
        }
        return mapping.get(quality_str, QualityCode.GOOD)

    @staticmethod
    def to_string(code: QualityCode) -> str:
        """将 QualityCode 映射回字符串"""
        ...

    @staticmethod
    def compute(device_state: str, comm_status: str = "ok",
                fault_active: bool = False, sensor_stuck: bool = False) -> QualityCode:
        """根据设备状态、通信状态、故障情况自动计算质量码"""
        if device_state == "error":
            return QualityCode.BAD_DEVICE_FAILURE
        if comm_status == "timeout":
            return QualityCode.BAD_NOT_CONNECTED
        if comm_status == "error":
            return QualityCode.BAD_COMMUNICATION_ERROR
        if device_state == "maintenance":
            return QualityCode.BAD_OUT_OF_SERVICE
        if sensor_stuck:
            return QualityCode.UNCERTAIN_LAST_USABLE
        if fault_active:
            return QualityCode.UNCERTAIN_SENSOR_NOT_ACCURATE
        if device_state == "run":
            return QualityCode.GOOD
        return QualityCode.UNCERTAIN  # stop, starting, stopping, program
```

**集成要求**:
- 在 `DeviceInstance.read_point()` 中使用 `QualitySystem.compute()` 计算质量
- OPC-UA 协议 server (`protoforge/protocols/opcua/server.py`) 在返回变体节点时设置对应的 OPC UA StatusCode
- 其他协议 (Modbus, S7 等) 在 API 返回 `PointValue` 时包含质量字符串

---

#### 任务 1.4: 实现闭环控制回路框架

**问题**: `PIDController` 已存在于 `behavior_models.py`，但没有控制回路框架将其集成到设备仿真中。

**需要创建的文件**: `protoforge/core/control_loop.py`

**要求**:

```python
@dataclass
class ControlLoopConfig:
    """控制回路配置"""
    loop_id: str
    loop_type: str           # "simple" | "cascade" | "feedforward"
    setpoint_point: str      # 设定值点位名
    measurement_point: str   # 测量值点位名
    output_point: str        # 输出点位名 (写到执行器)
    pid_params: dict         # {"Kp": 1.0, "Ki": 0.1, "Kd": 0.01}
    output_limit: tuple[float, float] = (0.0, 100.0)
    # 串级控制用
    primary_loop_id: str | None = None   # 主回路ID (副回路用)
    # 前馈控制用
    disturbance_point: str | None = None # 扰动量点位名
    feedforward_gain: float = 0.0

class ControlLoop:
    """控制回路实例"""
    def __init__(self, config: ControlLoopConfig):
        self.config = config
        self._pid = PIDController(
            Kp=config.pid_params.get("Kp", 1.0),
            Ki=config.pid_params.get("Ki", 0.1),
            Kd=config.pid_params.get("Kd", 0.01),
            setpoint=0.0,
            output_limit=config.output_limit,
        )

    def execute(self, measurement: float, setpoint: float,
                dt: float, disturbance: float | None = None) -> float:
        """执行一个控制周期，返回控制输出"""
        self._pid.set_setpoint(setpoint)
        output = self._pid.update(measurement, dt)
        if disturbance is not None and self.config.feedforward_gain != 0:
            output += self.config.feedforward_gain * disturbance
        return output

class ControlLoopManager:
    """控制回路管理器 (管理设备上的多个控制回路)"""
    def __init__(self):
        self._loops: dict[str, ControlLoop] = {}

    def add_loop(self, config: ControlLoopConfig) -> str: ...
    def remove_loop(self, loop_id: str) -> bool: ...
    def tick(self, device: 'DeviceInstance', dt: float) -> dict[str, float]:
        """执行所有控制回路一个周期，返回需要写入的点位值"""
        # 1. 简单回路: 读取测量值和设定值 → PID计算 → 输出写入执行器
        # 2. 串级回路: 先执行主回路 → 主回路输出作为副回路设定值 → 副回路执行
        # 3. 前馈回路: 读取扰动量 → 叠加前馈补偿
        ...
```

**集成到 `DeviceInstance`**:
- 添加 `self._control_loops: ControlLoopManager | None = None`
- 在 `tick()` 方法中调用 `self._control_loops.tick(self, dt)` 并将输出写入对应点位
- 通过 `protocol_config` 中的 `control_loops` 列表配置

---

#### 任务 1.5: 确保所有协议支持写操作 (双向数据流)

**问题**: 部分协议 server 只实现了读操作，写操作要么缺失要么不更新内部状态。

**修改文件**: 所有协议 server 文件，重点是:
- `protoforge/protocols/modbus/server.py`
- `protoforge/protocols/s7/server.py`
- `protoforge/protocols/opcua/server.py`
- `protoforge/protocols/bacnet/server.py`
- `protoforge/protocols/mqtt/server.py`

**要求**:

1. 修改 `protoforge/protocols/base.py` 的 `ProtocolServer` 基类：
   - 添加 `async def write_point(self, device_id: str, point_name: str, value: Any) -> bool` 方法
   - 添加 `on_write: Optional[Callable[[str, str, Any], bool]]` 回调属性

2. 在每个协议 server 中实现 `write_point`:
   - 解析协议地址 (如 Modbus 的 holding register 40001)
   - 将写入值转换为协议数据格式
   - 调用 `DeviceInstance.write_point(point_name, value)` 更新内部状态
   - 如果设备有物理模型，写入值应更新物理模型的输入参数
   - 如果设备有控制回路，写入设定值点位应更新控制回路设定值
   - PROGRAM 状态下写入应被拒绝

3. `DeviceInstance.write_point()` 方法:
   ```python
   def write_point(self, point_name: str, value: Any) -> bool:
       state = self._state_machine.get_state()
       if state == DeviceState.PROGRAM:
           return False
       if point_name not in self._point_configs:
           return False
       access = self._point_configs[point_name].access
       if access not in ("w", "rw"):
           return False
       self._point_values[point_name] = value
       # 如果有物理模型，更新输入
       # 如果有控制回路设定值，更新设定值
       return True
   ```

---

#### 任务 1.6: 添加故障注入和状态控制的 API 接口

**修改文件**: `protoforge/api/v1/device_routes.py`

**需要添加的接口**:

```
POST   /api/v1/devices/{device_id}/faults           # 注入故障
DELETE /api/v1/devices/{device_id}/faults/{fault_id} # 移除故障
GET    /api/v1/devices/{device_id}/faults            # 列出故障
DELETE /api/v1/devices/{device_id}/faults            # 清除所有故障

POST   /api/v1/devices/{device_id}/state/transition  # 状态转换
GET    /api/v1/devices/{device_id}/state             # 获取当前状态
GET    /api/v1/devices/{device_id}/state/history     # 状态历史

POST   /api/v1/devices/{device_id}/control-loops     # 添加控制回路
DELETE /api/v1/devices/{device_id}/control-loops/{loop_id}  # 移除控制回路
GET    /api/v1/devices/{device_id}/control-loops     # 列出控制回路
```

**请求/响应格式示例**:

注入故障:
```json
POST /api/v1/devices/motor_01/faults
{
    "fault_type": "sensor_drift",
    "target": "temperature",
    "duration": 300,
    "severity": "high",
    "parameters": {"rate": 0.05}
}
```

状态转换:
```json
POST /api/v1/devices/motor_01/state/transition
{
    "event": "start",
    "reason": "操作员手动启动"
}
```

---

#### 任务 1.7: 前端界面适配

**修改文件**: `web/src/views/Devices.vue` 及相关组件

**需要添加的前端功能**:

1. **设备状态面板**: 显示 7 种状态 (STOP/STARTING/RUN/STOPPING/ERROR/MAINTENANCE/PROGRAM)，支持状态转换按钮 (启动/停止/故障/复位/维护)
2. **故障注入面板**: 下拉选择故障类型、目标点位、严重程度、持续时间，一键注入/清除
3. **数据质量显示**: 在数据表格中用颜色标记质量 (绿色=Good, 黄色=Uncertain, 红色=Bad)
4. **控制回路配置面板**: 添加/删除控制回路，配置 PID 参数
5. **物理模型配置**: 在设备点位配置中选择物理模型类型和参数

---

### Phase 2: 高级仿真能力

#### 任务 2.1: 实现时间序列模式

**需要创建的文件**: `protoforge/core/timeseries.py`

**要求**:

```python
class TimeSeriesPattern:
    """时间序列模式生成器"""

    def daily_pattern(self, hour: int, production_value: float, standby_value: float) -> float:
        """日变化模式 (8-18点生产，其余待机)"""

    def weekly_pattern(self, day_of_week: int, workday_value: float, weekend_value: float) -> float:
        """周变化模式"""

    def seasonal_pattern(self, month: int, base_value: float, amplitude: float = 0.2) -> float:
        """季节性变化"""

    def batch_process(self, elapsed: float, phases: list[dict]) -> tuple[float, str]:
        """批次生产模式 (升温→保温→降温→清洗)
        phases: [{"name": "heatup", "target": 100, "duration": 1800}, ...]
        返回 (当前值, 当前阶段名)
        """

    def equipment_aging(self, total_runtime: float, initial_efficiency: float = 1.0,
                        decay_rate: float = 0.0001) -> float:
        """设备老化模型 (效率随运行时间衰减)"""
```

**集成**: 在 `GeneratorType` 中新增 `TIME_SERIES` 和 `BATCH_PROCESS`，在 `DynamicValueGenerator` 中添加对应分支。

---

#### 任务 2.2: 实现多设备协同仿真

**需要创建的文件**: `protoforge/core/collaboration.py`

**要求**:

```python
class DeviceInterlock:
    """联锁保护"""
    def __init__(self):
        self.rules: list[dict] = []
        # 规则: {"condition": "pump.running and valve.position < 5",
        #         "action": "trip", "target": "pump", "reason": "阀门未打开"}

    def add_rule(self, condition: str, action: str, target: str, reason: str): ...
    def check(self, devices: dict[str, 'DeviceInstance']) -> list[dict]:
        """检查所有联锁条件，返回需要执行的动作列表"""

class MaterialBalance:
    """物料平衡计算"""
    def __init__(self, tank_id: str, inlet_devices: list[str], outlet_devices: list[str]):
        ...

    def calculate(self, devices: dict[str, 'DeviceInstance'], dt: float) -> float:
        """计算物料平衡，返回当前库存"""

class EnergyBalance:
    """能量平衡计算"""
    def calculate(self, input_power: float, output_power: float) -> dict:
        """返回 {input, output, loss, efficiency}"""
```

**集成**: 在 `Scenario.tick()` 中调用协同仿真逻辑。

---

#### 任务 2.3: 深化协议仿真

**S7 协议增强** (`protoforge/protocols/s7/server.py`):
- 添加 OB 块处理模拟 (OB1 主循环、OB35 循环中断、OB82 诊断中断、OB100 暖启动)
- 添加 FC 块调用模拟 (FC106 SCALE 标定、FC105 UNSCALE 反标定)
- 添加 CPU 负载模拟 (影响响应时间)
- 添加 S7 通信服务 (PUT/GET)

**OPC-UA 协议增强** (`protoforge/protocols/opcua/server.py`):
- 添加历史数据访问 (HistoryRead)
- 添加方法节点 (Method Nodes) 支持
- 添加告警和条件 (Alarms & Conditions)
- 在变量节点中设置正确的 StatusCode (使用 `QualityCode`)

**Modbus 协议增强** (`protoforge/protocols/modbus/server.py`):
- 添加诊断功能码 0x08 支持
- 添加异常响应模拟 (非法功能码/地址/数据值/从站故障)
- 添加可配置的响应延迟

---

#### 任务 2.4: 实现网络损伤模拟

**需要创建的文件**: `protoforge/core/network_emulation.py`

**要求**:

```python
class NetworkEmulation:
    """网络损伤模拟器"""
    def __init__(self, latency_ms: float = 0, jitter_ms: float = 0,
                 packet_loss_rate: float = 0, bandwidth_limit: int = 0):
        ...

    async def simulate(self, data: bytes) -> bytes:
        """应用网络损伤到数据传输"""
        # 1. 延迟: asyncio.sleep(gauss(latency, jitter) / 1000)
        # 2. 丢包: random() < packet_loss_rate → raise ConnectionError
        # 3. 带宽限制: 根据数据大小计算传输时间
        ...

class NetworkTopology:
    """网络拓扑管理"""
    def __init__(self):
        self.links: dict[str, NetworkEmulation] = {}  # device_id → emulation config

    def set_link_config(self, device_id: str, config: dict): ...
    def get_link_config(self, device_id: str) -> NetworkEmulation: ...
```

**集成**: 在协议 server 处理请求前调用 `network_emulation.simulate()`。

---

### Phase 3: 扩展能力

#### 任务 3.1: 配置导入

**需要创建的文件**:
```
protoforge/core/importer/
├── __init__.py
├── modbus_poll.py      # 导入 .mbs 配置
├── opcua_nodeset.py    # 导入 NodeSet2.xml
└── tia_portal.py       # 导入 TIA Portal XML
```

#### 任务 3.2: 安全仿真

**需要创建的文件**: `protoforge/core/security_sim.py`

实现: 重放攻击、中间人攻击、DoS 攻击、模糊测试模拟。

#### 任务 3.3: 前端 3D 可视化

集成 Three.js (或 Babylon.js)，支持 glTF 模型导入，设备动画与仿真数据联动。

---

## 3. 全局集成检查清单

完成所有任务后，确保以下集成点正确工作:

### 3.1 数据流完整性

```
[外部客户端] → [协议 Server] → [网络模拟层] → [DeviceInstance.read_point()]
                                                      ↓
                                        [物理模型.update()] → [故障注入.apply()]
                                                      ↓
                                        [质量系统.compute()] → [PointValue]
                                                      ↓
                                              [协议 Server] → [外部客户端]
```

### 3.2 控制流完整性

```
[外部客户端] → [协议 Server.write_point()] → [DeviceInstance.write_point()]
                                                      ↓
                                        [更新物理模型输入] / [更新控制回路设定值]
                                                      ↓
                                        [下一个 tick: 控制回路执行]
                                                      ↓
                                        [PID 计算] → [写入执行器点位]
                                                      ↓
                                        [物理模型响应执行器变化]
```

### 3.3 状态联动完整性

```
[状态机转换 RUN→ERROR]
    → [设置安全值]
    → [质量标记变为 Bad]
    → [故障注入器记录设备故障]
    → [WebSocket 广播状态变更]
    → [前端更新设备状态显示]
```

---

## 4. 代码规范要求

1. **Python**: 遵循 PEP 8，使用类型注解 (`from __future__ import annotations`)，编写完整 docstring
2. **日志**: 使用 `logging.getLogger(__name__)`，关键操作记录 INFO/WARNING
3. **线程安全**: 共享状态使用 `threading.RLock` 或 `asyncio.Lock`
4. **错误处理**: 所有外部输入需验证，异常需捕获并记录，不得裸 `except`
5. **向后兼容**: 新功能不破坏现有 API，新增字段有默认值
6. **Vue 前端**: 使用 Composition API (`<script setup>`)，Element Plus 组件，i18n 国际化

---

## 5. 测试要求

每个新模块需编写单元测试 (`tests/` 目录):
- 物理模型: 验证物理方程正确性 (如热模型升温曲线单调性)
- 状态机: 验证所有转换路径和条件守卫
- 故障注入: 验证每种故障类型的值修改和质量标记
- 控制回路: 验证 PID 输出收敛性
- 质量系统: 验证状态-质量映射
- 协议写操作: 验证写入后内部状态更新

---

## 6. 执行顺序

按以下顺序执行，每步完成后验证再进行下一步:

1. **任务 1.1** — 物理模型集成 (修改 `behavior.py`)
2. **任务 1.3** — 数据质量系统 (新建 `quality.py` + 集成)
3. **任务 1.2** — 故障注入引擎 (新建 `fault/` + 集成)
4. **任务 1.5** — 协议写操作 (修改所有协议 server)
5. **任务 1.4** — 闭环控制回路 (新建 `control_loop.py` + 集成)
6. **任务 1.6** — API 接口 (修改 `device_routes.py`)
7. **任务 1.7** — 前端界面 (修改 Vue 组件)
8. **任务 2.1~2.4** — 高级仿真 (逐个实现)
9. **任务 3.1~3.3** — 扩展能力 (逐个实现)

---

**文档版本**: v2.0
**生成日期**: 2026-07-02
**基于文件**: `ProtoForge_完整化修复提示语.md` + 代码审计结果
