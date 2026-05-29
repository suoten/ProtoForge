# 故障注入使用文档

本文档描述 ProtoForge 故障注入模块的设计、使用方式及内置故障类型。

---

## 概述

故障注入模块允许你在运行中的模拟设备上注入真实工业场景的异常，用于：

- 验证监控系统的异常检测能力
- 训练工业 AI 异常检测模型（提供异常样本）
- 测试报警规则和联动逻辑

支持四种异常场景：

| 场景 | 说明 |
|------|------|
| 异常注入 | 立即将指定测点推入异常区间 |
| 自动恢复 | 故障持续指定时间后自动恢复正常 |
| 多指标联动 | 一次注入同时影响多个相关测点 |
| 渐进式劣化 | 指标随时间线性恶化，模拟真实磨损过程 |

---

## 架构设计

```
FaultInjector（独立模块）
    │
    ├── inject(device, request)   注入故障
    ├── apply(device)             每次 tick 后覆盖测点值（通过钩子机制）
    ├── clear(device_id)          手动清除
    └── 自动到期恢复

DeviceInstance.tick()
    └── 执行正常生成器
    └── 执行 post_tick_hooks（FaultInjector.apply 挂载于此）
```

故障模块通过 `register_post_tick_hook` 挂载到设备，不修改设备本身的生成逻辑，完全解耦。

---

## API 接口

### 查询故障类型

```
GET /api/v1/faults/types
```

返回所有内置故障类型列表。

```
GET /api/v1/faults/types/{fault_type_id}
```

返回指定故障类型的详细定义，包含影响的测点和行为参数。

### 查询活跃故障

```
GET /api/v1/faults/active
```

返回当前所有设备上正在运行的故障实例。

### 注入故障

```
POST /api/v1/devices/{device_id}/fault
```

请求体：

```json
{
    "fault_type_id": "tool_wear",
    "duration": 300,
    "intensity": 0.8
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `fault_type_id` | string | 是 | 故障类型 ID，见下方故障类型列表 |
| `duration` | float | 否 | 持续时间（秒），不填则使用类型默认值 |
| `intensity` | float | 否 | 故障强度 0.0~1.0，默认 1.0，影响劣化幅度 |

响应示例：

```json
{
    "fault_id": "a3f2c1d4e5b6",
    "device_id": "fanuc-cnc-01",
    "fault_type_id": "tool_wear",
    "fault_type_name": "刀具磨损",
    "status": "active",
    "intensity": 0.8,
    "duration": 300.0,
    "elapsed": 0.0,
    "progress": 0.0,
    "affected_points": ["spindle_current", "vibration_x", "vibration_y", "vibration_z", "feed_rate"],
    "started_at": 1716192000.0
}
```

### 查询设备当前故障

```
GET /api/v1/devices/{device_id}/fault
```

无故障时返回 `{"status": "none"}`，有故障时返回故障详情（含实时 `elapsed` 和 `progress`）。

### 手动清除故障

```
DELETE /api/v1/devices/{device_id}/fault
```

立即清除故障，测点值由生成器在下一个 tick 自然恢复正常。

---

## 内置故障类型

### tool_wear — 刀具磨损

- **分类**：mechanical
- **模式**：渐进式
- **默认持续时间**：300 秒
- **真实场景**：刀具切削刃逐渐磨损，切削阻力增大，系统自动压低进给速率

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `spindle_current` | 升高 | ×2.2 |
| `vibration_x` | 升高 | ×3.0 |
| `vibration_y` | 升高 | ×3.0 |
| `vibration_z` | 升高 | ×3.5 |
| `feed_rate` | 降低 | ×0.45 |

---

### tool_breakage — 刀具崩刃

- **分类**：mechanical
- **模式**：瞬间注入
- **默认持续时间**：15 秒
- **真实场景**：刀具突发性崩刃，机床通常会触发报警并停机

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `spindle_current` | 急升 | ×4.5 |
| `vibration_x` | 急升 | ×8.0 |
| `vibration_y` | 急升 | ×8.0 |
| `vibration_z` | 急升 | ×10.0 |
| `feed_rate` | 停止 | →0 |

---

### spindle_overheat_rough — 主轴过热（粗铣）

- **分类**：thermal
- **模式**：渐进式（绝对目标值）
- **默认持续时间**：240 秒
- **真实场景**：粗铣主轴长时间高负荷或冷却不足，负载/电流持续高位，热保护渐进降速

| 测点 | 变化方向 | 目标值 |
|------|---------|--------|
| `spindle_load` | 持续升高 | →85% |
| `spindle_current` | 持续升高 | →34A |
| `spindle_speed` | 渐进降低 | →1400 RPM |

---

### spindle_overheat_semi — 主轴过热（半精铣）

- **分类**：thermal
- **模式**：渐进式（绝对目标值）
- **默认持续时间**：240 秒
- **真实场景**：半精铣主轴长时间高负荷或冷却不足，负载/电流持续高位，热保护渐进降速

| 测点 | 变化方向 | 目标值 |
|------|---------|--------|
| `spindle_load` | 持续升高 | →72% |
| `spindle_current` | 持续升高 | →24A |
| `spindle_speed` | 渐进降低 | →2600 RPM |

---

### spindle_overheat_finish — 主轴过热（精铣）

- **分类**：thermal
- **模式**：渐进式（绝对目标值）
- **默认持续时间**：240 秒
- **真实场景**：精铣主轴长时间高负荷或冷却不足，负载/电流持续高位，热保护渐进降速

| 测点 | 变化方向 | 目标值 |
|------|---------|--------|
| `spindle_load` | 持续升高 | →48% |
| `spindle_current` | 持续升高 | →15A |
| `spindle_speed` | 渐进降低 | →3800 RPM |

---

### spindle_bearing_fault — 主轴轴承故障

- **分类**：mechanical
- **模式**：渐进式
- **默认持续时间**：360 秒
- **真实场景**：轴承磨损或润滑不足，振动持续升高

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `vibration_x` | 升高 | ×4.0 |
| `vibration_y` | 升高 | ×4.0 |
| `vibration_z` | 升高 | ×5.0 |
| `spindle_current` | 轻微升高 | ×1.3 |

---

### feed_stall — 进给堵转

- **分类**：process
- **模式**：瞬间注入
- **默认持续时间**：20 秒
- **真实场景**：工件夹紧松动或切削量过大导致进给轴卡死

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `feed_rate` | 停止 | →0 |
| `spindle_current` | 急升 | ×3.8 |
| `vibration_z` | 急升 | ×5.0 |

---

### vibration_spike — 振动异常

- **分类**：mechanical
- **模式**：瞬间注入
- **默认持续时间**：60 秒
- **真实场景**：工件装夹松动或切削共振

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `vibration_x` | 急升 | ×6.0 |
| `vibration_y` | 急升 | ×6.0 |
| `vibration_z` | 急升 | ×7.0 |

---

### coolant_failure — 切削液不足

- **分类**：process
- **模式**：渐进式
- **默认持续时间**：480 秒
- **真实场景**：切削液供给不足，热量积累，劣化速度较慢

| 测点 | 变化方向 | 峰值倍率 |
|------|---------|---------|
| `spindle_current` | 升高 | ×1.6 |
| `vibration_x` | 升高 | ×2.0 |
| `vibration_y` | 升高 | ×2.0 |
| `vibration_z` | 升高 | ×2.5 |
| `feed_rate` | 降低 | ×0.75 |

---

### power_fluctuation — 电源波动

- **分类**：electrical
- **模式**：瞬间注入（持续期间持续抖动）
- **默认持续时间**：90 秒
- **真实场景**：供电电压不稳定，各指标出现随机波动

| 测点 | 变化方向 | 说明 |
|------|---------|------|
| `spindle_speed` | 随机抖动 | ±300 RPM 噪声 |
| `spindle_current` | 随机抖动 | ±5 A 噪声 |
| `feed_rate` | 随机抖动 | ±150 mm/min 噪声 |

---

## 使用示例

### 模拟刀具磨损过程

```bash
# 注入刀具磨损，持续 5 分钟，强度 100%
curl -X POST http://localhost:8000/api/v1/devices/fanuc-cnc-01/fault \
  -H "Content-Type: application/json" \
  -d '{"fault_type_id": "tool_wear", "duration": 300, "intensity": 1.0}'

# 每隔 30 秒查看故障进度
curl http://localhost:8000/api/v1/devices/fanuc-cnc-01/fault

# 查看 Prometheus 指标变化
curl http://localhost:8000/api/v1/metrics | grep -E "spindle_current|vibration|feed_rate"
```

### 模拟突发崩刃后手动恢复

```bash
# 注入崩刃故障
curl -X POST http://localhost:8000/api/v1/devices/fanuc-cnc-01/fault \
  -H "Content-Type: application/json" \
  -d '{"fault_type_id": "tool_breakage", "duration": 60}'

# 手动提前清除
curl -X DELETE http://localhost:8000/api/v1/devices/fanuc-cnc-01/fault
```

### 低强度渐进劣化（用于 AI 模型训练）

```bash
# 用 50% 强度注入轴承故障，持续 10 分钟，产生轻微异常样本
curl -X POST http://localhost:8000/api/v1/devices/fanuc-cnc-01/fault \
  -H "Content-Type: application/json" \
  -d '{"fault_type_id": "spindle_bearing_fault", "duration": 600, "intensity": 0.5}'
```

---

## 与 Prometheus 集成

故障注入后，测点值的变化会实时反映在 `/api/v1/metrics` 接口中。可以用 Grafana 观察故障期间各指标的时序变化：

```
# 主轴电流（故障期间会升高）
fanuc_cnc_spindle_current

# 三轴振动
fanuc_cnc_vibration_x
fanuc_cnc_vibration_y
fanuc_cnc_vibration_z

# 进给速率（刀具磨损/堵转时会降低）
fanuc_cnc_feed_rate
```

---

## 注意事项

- 同一设备同时只能有一个活跃故障，新注入会覆盖旧故障
- 故障到期后测点值由生成器在下一个 tick 自然恢复，不会瞬间跳回
- 设备必须处于 `online` 状态才能注入故障
- 删除设备时会自动清除其故障
