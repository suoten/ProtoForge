# ProtoForge v2.0 — IoT/工业设备测试平台详细规划

> **版本**：v1.0 ｜ **日期**：2026-09-12  
> **定位**：从"仿真工具"升级为"测试平台"——让工业物联网团队把它当成**基础设施**，而不仅仅是临时工具。  
> **核心原则**：每个功能都要能回答"谁会为此付钱"。

---

## 一、现状盘点：我们手里有什么

### 1.1 已有的产品能力（V1.1.1）

| 能力域 | 具体实现 | 成熟度 | 测试平台价值 |
|--------|---------|--------|-------------|
| **协议仿真** | 21种工业协议服务器（Modbus/S7/FINS/MC/OPC-UA/IEC104/IEC61850/CoAP/DDS/GB28181/BACnet/AB/OPC-DA/FANUC/MTConnect/Toledo/PROFINET/EtherCAT/MQTT/HTTP/ModbusRTU） | ★★★★★ | **核心资产**，覆盖90%工业场景 |
| **设备模板** | 122个即用型模板（PLC/传感器/CNC/摄像头/HVAC/伺服/继电器/IED/微电网等） | ★★★★★ | 降低用户上手成本 |
| **故障注入** | 9种故障类型（传感器卡死/漂移/噪声/失效、间歇断连/延迟/丢包、设备故障/执行器卡死），4种触发模式 | ★★★★☆ | **测试平台的核心差异化** |
| **自动化测试** | 13种断言、变量提取、测试套件、HTML报告、SDK调用 | ★★★★☆ | 测试平台的基础引擎 |
| **协议录制回放** | 报文录制→按速回放→Gzip压缩存储→AES加密 | ★★★★☆ | 场景复现能力 |
| **时序回放** | CSV/JSON历史数据驱动仿真，支持加速/循环 | ★★★★☆ | 真实数据驱动测试 |
| **实时调试日志** | WebSocket实时推送协议报文，按协议/方向/关键词筛选 | ★★★★★ | 调试效率工具 |
| **场景编排** | 可视化设备联动规则，阈值/值变化/定时/脚本四种规则 | ★★★★☆ | 复杂场景模拟 |
| **数据转发** | InfluxDB/HTTP Webhook/文件，批量异步发送 | ★★★★☆ | 对接外部系统 |
| **EdgeLite集成** | 设备自动注册到网关，采集→转发闭环 | ★★★★☆ | 完整数据链路验证 |
| **多语言SDK** | Python（同步/异步90+方法）/Java/Go/C# | ★★★★☆ | CI/CD集成能力 |
| **认证鉴权** | JWT + RBAC（4角色）+ 限流 + bcrypt | ★★★★☆ | 企业级基础 |
| **部署** | Docker/K8s/Helm/一键脚本/PyPI | ★★★★★ | 私有化部署就绪 |

### 1.2 缺失的能力（成为"平台"的差距）

| 缺失能力 | 为什么需要 | 付费意愿来源 |
|---------|-----------|-------------|
| **测试计划管理** | 当前测试是"点一下跑一下"，没有版本化、可追溯的测试计划 | QA团队需要可审计的测试流程 |
| **CI/CD集成** | 无法在Jenkins/GitLab CI中自动跑测试 | DevOps团队的标准需求 |
| **测试报告导出** | 只有HTML报告，没有PDF/JUnit/Allure格式 | 企业合规需要标准化报告 |
| **多用户协作** | 测试用例/套件无法共享、分配、协同 | 团队使用场景 |
| **协议合规性检测** | 只能"能通信"，不能判断"通信是否符合规范" | 协议认证需求 |
| **性能基准** | 没有"每秒处理多少报文"的量化指标 | 性能测试场景 |
| **测试数据管理** | 测试数据没有版本化、无法对比 | 回归测试需要数据基线 |

---

## 二、v2.0 产品定位与目标

### 2.1 一句话定位

> **ProtoForge v2.0 = 工业协议仿真引擎 + 自动化测试框架 + CI/CD集成 + 合规性检测**  
> 让工业物联网团队从"手动联调"升级为"自动化测试流水线"。

### 2.2 目标用户

| 用户角色 | 核心诉求 | 付费意愿 |
|---------|---------|---------|
| **上位机开发团队** | 改完代码自动跑协议测试，不用手动建设备 | ★★★★☆ |
| **物联网网关厂商** | 发版前自动验证21种协议采集正确性 | ★★★★★ |
| **系统集成商** | 给客户交付前自动验证全套系统 | ★★★★☆ |
| **QA团队** | 可追溯、可审计的测试计划+报告 | ★★★★☆ |
| **协议设备厂商** | 协议合规性自检，替代昂贵的认证机构测试 | ★★★★★ |

### 2.3 v2.0 核心目标

| 目标 | 量化指标 | 验收标准 |
|------|---------|---------|
| 测试自动化 | 支持CI/CD流水线集成 | Jenkins/GitLab CI一行命令跑全套测试 |
| 测试可追溯 | 测试计划版本化+报告归档 | 每次测试有唯一ID，可追溯设备配置/故障注入/结果 |
| 协议合规 | 5种核心协议合规性检测 | Modbus/S7/OPC-UA/IEC104/MQTT合规报告 |
| 性能量化 | 性能基准测试+趋势图 | 报文吞吐量/延迟/并发连接数指标 |
| 团队协作 | 测试资产共享+角色权限 | 测试套件可分配给不同测试人员 |

---

## 三、功能规划（按优先级排序）

### 3.1 P0 — 测试计划管理（第1-3周）

**目标**：从"点一下跑一下"升级为"可版本化、可追溯的测试计划"。

#### 3.1.1 数据模型

```
TestPlan
├── id: str                    # 唯一ID
├── name: str                  # 计划名称
├── version: str               # 版本号 (如 v1.0.0)
├── description: str           # 计划描述
├── test_suite_ids: list[str]  # 包含的测试套件
├── device_configs: list       # 需要的设备配置快照
├── protocol_configs: list     # 需要的协议配置
├── fault_scenarios: list      # 故障注入场景
├── schedule: dict             # 定时执行配置 (cron)
├── created_by: str            # 创建者
├── created_at: timestamp
├── updated_at: timestamp
└── status: enum               # draft / active / archived

TestRun (测试计划的一次执行)
├── id: str
├── plan_id: str               # 关联的测试计划
├── plan_version: str          # 计划版本快照
├── triggered_by: str          # 触发者 (user / ci / schedule)
├── trigger_source: str        # 触发来源 (manual / jenkins / gitlab / cron)
├── start_time: timestamp
├── end_time: timestamp
├── status: enum               # running / passed / failed / error / aborted
├── environment: dict          # 环境信息 (ProtoForge版本/OS/Python版本)
├── results_summary: dict      # {total, passed, failed, error, skipped}
└── report_url: str            # 报告链接
```

#### 3.1.2 API设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/test-plans` | 创建测试计划 |
| GET | `/api/v1/test-plans` | 列出所有计划 |
| GET | `/api/v1/test-plans/{plan_id}` | 获取计划详情 |
| PUT | `/api/v1/test-plans/{plan_id}` | 更新计划 |
| DELETE | `/api/v1/test-plans/{plan_id}` | 删除计划 |
| POST | `/api/v1/test-plans/{plan_id}/clone` | 克隆计划 |
| POST | `/api/v1/test-plans/{plan_id}/run` | 执行计划 |
| GET | `/api/v1/test-plans/{plan_id}/runs` | 列出执行历史 |
| GET | `/api/v1/test-runs/{run_id}` | 获取执行详情 |
| GET | `/api/v1/test-runs/{run_id}/report` | 获取执行报告 |
| POST | `/api/v1/test-runs/{run_id}/abort` | 中止执行 |
| GET | `/api/v1/test-runs/{run_id}/report/pdf` | 导出PDF报告 |

#### 3.1.3 前端页面

**测试计划页面**（新增 `TestPlans.vue`）：
- 计划列表（卡片视图）：名称/版本/最近执行状态/通过率趋势图
- 创建/编辑计划：选择测试套件 → 配置设备 → 配置故障场景 → 设置定时
- 执行历史：时间线视图，每次执行的环境/结果/报告
- 对比视图：两次执行的diff（哪些用例从通过变为失败）

---

### 3.2 P0 — CI/CD 集成（第3-5周）

**目标**：让ProtoForge测试能在Jenkins/GitLab CI/GitHub Actions中一行命令运行。

#### 3.2.1 CLI工具

```bash
# 安装
pip install protoforge

# 基本用法
protoforge test run --plan my-plan --server http://protoforge:8000

# 指定认证
protoforge test run --plan my-plan --token $PROTOFORGE_TOKEN

# 输出 JUnit XML（CI标准格式）
protoforge test run --plan my-plan --format junit --output test-results.xml

# 输出 JSON
protoforge test run --plan my-plan --format json --output results.json

# 只跑特定套件
protoforge test run --plan my-plan --suite "Modbus回归测试"

# 超时控制
protoforge test run --plan my-plan --timeout 300
```

#### 3.2.2 CI/CD 模板

**Jenkinsfile**:
```groovy
pipeline {
    agent any
    stages {
        stage('Protocol Test') {
            steps {
                sh '''
                    pip install protoforge
                    protoforge test run \
                        --plan modbus-regression \
                        --server http://protoforge:8000 \
                        --token $PROTOFORGE_TOKEN \
                        --format junit \
                        --output test-results.xml
                '''
            }
            post {
                always {
                    junit 'test-results.xml'
                }
            }
        }
    }
}
```

**GitLab CI**:
```yaml
protocol_test:
  stage: test
  image: python:3.12
  script:
    - pip install protoforge
    - protoforge test run --plan modbus-regression --server $PROTOFORGE_URL --token $PROTOFORGE_TOKEN --format junit --output test-results.xml
  artifacts:
    when: always
    reports:
      junit: test-results.xml
```

**GitHub Actions**:
```yaml
- name: Run Protocol Tests
  run: |
    pip install protoforge
    protoforge test run --plan modbus-regression --server ${{ secrets.PROTOFORGE_URL }} --token ${{ secrets.PROTOFORGE_TOKEN }} --format junit --output test-results.xml
- uses: dorny/test-reporter@v1
  with:
    name: Protocol Test Results
    path: test-results.xml
    reporter: java-junit
```

#### 3.2.3 API设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/test-plans/{plan_id}/run` | 触发执行（支持`?async=true`异步执行） |
| GET | `/api/v1/test-runs/{run_id}/status` | 轮询执行状态 |
| GET | `/api/v1/test-runs/{run_id}/report?format=junit` | JUnit XML格式报告 |
| GET | `/api/v1/test-runs/{run_id}/report?format=json` | JSON格式报告 |
| GET | `/api/v1/test-runs/{run_id}/report?format=html` | HTML格式报告 |
| GET | `/api/v1/test-runs/{run_id}/report?format=pdf` | PDF格式报告 |
| POST | `/api/v1/test-runs/{run_id}/abort` | 中止执行 |
| GET | `/api/v1/test-plans/{plan_id}/runs?limit=20` | 执行历史 |

---

### 3.3 P1 — 协议合规性检测（第5-8周）

**目标**：不只验证"能通信"，更验证"通信是否符合协议规范"。

#### 3.3.1 合规性检测规则

**Modbus TCP 合规检测**：
| 规则ID | 检测内容 | 严重级别 |
|--------|---------|---------|
| MB-001 | 功能码合法性（1-6, 15-16, 23, 246-255保留） | ERROR |
| MB-002 | 寄存器地址范围校验 | ERROR |
| MB-003 | 数据量不超过253字节（Modbus TCP帧限制） | ERROR |
| MB-004 | 事务ID一致性（请求与响应匹配） | WARNING |
| MB-005 | Unit ID正确性 | WARNING |
| MB-006 | 异常码合规性（1-4合法，其他非法） | ERROR |
| MB-007 | 响应时间<2s | WARNING |

**S7 协议合规检测**：
| 规则ID | 检测内容 | 严重级别 |
|--------|---------|---------|
| S7-001 | TPKT版本号=0x03 | ERROR |
| S7-002 | COTP类型=0xD0 (Connect) / 0xF0 (Data) | ERROR |
| S7-003 | Protocol ID = 0x32 | ERROR |
| S7-004 | ROSCTR合法性（1=Job, 2=Ack, 3=Ack-Data, 7=Userdata） | ERROR |
| S7-005 | TSAP格式合规 | WARNING |
| S7-006 | 读/写区域长度限制 | WARNING |

**OPC-UA 合规检测**：
| 规则ID | 检测内容 | 严重级别 |
|--------|---------|---------|
| OU-001 | Hello/Acknowledge握手完整 | ERROR |
| OU-002 | OpenSecureChannel顺序正确 | ERROR |
| OU-003 | CreateSession → ActivateSession顺序 | ERROR |
| OU-004 | 订阅创建后MonitoredItem必须关联 | WARNING |
| OU-005 | 证书签名验证 | ERROR |
| OU-006 | NodeId格式合规 | WARNING |

**IEC 104 合规检测**：
| 规则ID | 检测内容 | 严重级别 |
|--------|---------|---------|
| IEC-001 | 启动帧（STARTDT act）必须先于数据传输 | ERROR |
| IEC-002 | ASDU类型标识符合规范（1-127） | ERROR |
| IEC-003 | 公共地址长度=2字节 | WARNING |
| IEC-004 | 信息体地址连续性 | WARNING |
| IEC-005 | 总召唤响应顺序正确 | ERROR |

#### 3.3.2 实现方案

```python
# protoforge/testing/compliance/modbus.py

class ModbusComplianceChecker:
    """Modbus TCP协议合规性检测器。"""

    RULES = [
        ComplianceRule(id="MB-001", name="功能码合法性", severity="error",
                       check=_check_function_code),
        ComplianceRule(id="MB-002", name="寄存器地址范围", severity="error",
                       check=_check_register_range),
        ComplianceRule(id="MB-003", name="数据量限制", severity="error",
                       check=_check_data_length),
        # ...
    ]

    async def check(self, recording_id: str) -> ComplianceReport:
        """对录制的通信报文执行合规性检测。"""
        messages = await self._load_recording(recording_id)
        violations = []
        for msg in messages:
            for rule in self.RULES:
                violation = rule.check(msg)
                if violation:
                    violations.append(violation)
        return ComplianceReport(
            protocol="modbus_tcp",
            total_messages=len(messages),
            total_rules=len(self.RULES),
            violations=violations,
            compliance_score=self._calc_score(violations),
            passed=len(violations) == 0,
        )
```

#### 3.3.3 API设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/compliance/check` | 执行合规检测（指定协议+录制ID） |
| GET | `/api/v1/compliance/rules/{protocol}` | 获取协议的检测规则列表 |
| GET | `/api/v1/compliance/reports/{report_id}` | 获取合规报告 |
| GET | `/api/v1/compliance/reports/{report_id}/pdf` | 导出PDF合规报告 |

---

### 3.4 P1 — 性能基准测试（第8-10周）

**目标**：提供量化的性能指标和趋势分析。

#### 3.4.1 性能指标

| 指标 | 说明 | 单位 |
|------|------|------|
| **报文吞吐量** | 每秒处理的协议报文数 | msg/s |
| **读响应延迟** | 从请求到响应的平均/P50/P95/P99延迟 | ms |
| **并发连接数** | 同时连接的客户端数量 | count |
| **设备支持数** | 单实例可同时仿真的最大设备数 | count |
| **CPU占用** | 测试期间CPU使用率 | % |
| **内存占用** | 测试期间内存使用量 | MB |
| **丢包率** | 故障注入下通信丢包比例 | % |

#### 3.4.2 性能测试场景

```python
# 预置性能测试场景
PERFORMANCE_SCENARIOS = [
    {
        "name": "Modbus高并发读取",
        "protocol": "modbus_tcp",
        "config": {
            "devices": 100,          # 100台设备
            "points_per_device": 50, # 每台50个点位
            "read_interval_ms": 100, # 100ms读取间隔
            "duration_s": 60,        # 持续60秒
        },
        "metrics": ["throughput", "latency_p95", "cpu", "memory"],
        "threshold": {
            "throughput_min": 500,     # 至少500 msg/s
            "latency_p95_max": 50,    # P95延迟<50ms
        }
    },
    {
        "name": "OPC-UA大规模订阅",
        "protocol": "opcua",
        "config": {
            "devices": 50,
            "points_per_device": 200,
            "publish_interval_ms": 500,
            "duration_s": 120,
        },
        "metrics": ["throughput", "latency_p95", "subscription_loss"],
        "threshold": {
            "throughput_min": 200,
            "latency_p95_max": 100,
        }
    },
    # ... 每种协议一个基准场景
]
```

#### 3.4.3 趋势分析

- 每次性能测试结果入库
- 前端展示性能趋势图（折线图：时间为X轴，指标为Y轴）
- 支持对比两次测试结果（diff视图）
- 性能回退告警：当本次结果比上次差10%以上时标记WARNING

---

### 3.5 P2 — 多用户协作（第10-12周）

**目标**：让团队可以共享测试资产、分配任务、协同工作。

#### 3.5.1 协作能力

| 功能 | 说明 |
|------|------|
| **测试资产共享** | 测试套件/计划可设为"团队共享"或"私有" |
| **任务分配** | 测试计划可assign给特定用户 |
| **评论系统** | 在测试结果上可添加评论（如"已修复，见commit xxx"） |
| **通知系统** | 测试完成/失败时通知相关人员 |
| **操作审计** | 记录谁在什么时候创建/修改/执行了什么 |

#### 3.5.2 权限模型增强

| 角色 | 当前权限 | v2.0新增权限 |
|------|---------|-------------|
| admin | 全部 | 管理测试计划模板、分配任务 |
| operator | 操作设备/协议 | 创建/执行/删除测试计划 |
| tester（新增） | — | 执行测试、查看报告、添加评论 |
| viewer | 只读 | 查看测试结果和报告 |

---

### 3.6 P2 — 测试数据管理（第12-14周）

**目标**：测试数据版本化，支持回归对比。

#### 3.6.1 数据基线

```
TestBaseline (测试数据基线)
├── id: str
├── name: str               # "Modbus设备正常读数基线"
├── device_configs: list    # 设备配置快照
├── expected_values: dict   # 期望值 {device_id.point: value}
├── tolerance: dict         # 容差 {device_id.point: max_delta}
├── version: str
└── created_at: timestamp
```

#### 3.6.2 回归对比

- 选择基线 → 运行测试 → 自动对比结果
- 差异报告：哪些点位值偏离基线超过容差
- 趋势图：同一基线在多次回归中的值变化

---

## 四、技术架构

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端 (Vue3 + Naive UI)                    │
│  Dashboard │ Devices │ TestPlans │ Compliance │ Performance  │
└─────────────────────┬───────────────────────────────────────┘
                      │ REST API + WebSocket
┌─────────────────────┴───────────────────────────────────────┐
│                    FastAPI 后端                               │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ 测试计划  │ │ CI/CD    │ │ 合规检测    │ │ 性能基准     │ │
│  │ 管理器    │ │ 集成层   │ │ 引擎       │ │ 测试引擎     │ │
│  └──────────┘ └──────────┘ └────────────┘ └──────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ 自动化    │ │ 故障注入 │ │ 录制回放   │ │ 数据转发     │ │
│  │ 测试引擎  │ │ 引擎     │ │ 引擎       │ │ 引擎         │ │
│  └──────────┘ └──────────┘ └────────────┘ └──────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              协议仿真引擎 (21种协议)                      │ │
│  │  Modbus │ S7 │ FINS │ MC │ OPC-UA │ IEC104 │ IEC61850  │ │
│  │  CoAP │ DDS │ MQTT │ GB28181 │ BACnet │ AB │ ...        │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ 认证鉴权  │ │ 审计日志 │ │ 模板管理   │ │ EdgeLite集成 │ │
│  └──────────┘ └──────────┘ └────────────┘ └──────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────────┐
│              数据层 (SQLite / PostgreSQL)                     │
│  devices │ test_plans │ test_runs │ compliance_reports │ ... │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 新增模块结构

```
protoforge/
├── testing/                    # 新增：测试平台核心
│   ├── __init__.py
│   ├── plan.py                 # 测试计划管理
│   ├── runner.py               # 测试计划执行器
│   ├── ci.py                   # CI/CD集成接口
│   ├── report.py               # 报告生成（HTML/PDF/JUnit/JSON）
│   ├── compliance/             # 合规性检测
│   │   ├── __init__.py
│   │   ├── base.py             # 合规检测基类
│   │   ├── modbus.py           # Modbus合规检测
│   │   ├── s7.py               # S7合规检测
│   │   ├── opcua.py            # OPC-UA合规检测
│   │   ├── iec104.py           # IEC104合规检测
│   │   └── mqtt.py             # MQTT合规检测
│   ├── performance/            # 性能基准测试
│   │   ├── __init__.py
│   │   ├── benchmark.py        # 基准测试引擎
│   │   ├── metrics.py          # 指标采集
│   │   └── scenarios.py        # 预置性能场景
│   └── baseline.py             # 测试数据基线管理
├── api/v1/
│   ├── test_plan_routes.py     # 测试计划API
│   ├── compliance_routes.py    # 合规检测API
│   └── performance_routes.py   # 性能测试API
└── cli/
    └── test.py                 # CLI测试命令

web/src/views/
├── TestPlans.vue               # 测试计划页面
├── Compliance.vue              # 合规检测页面
└── Performance.vue             # 性能基准页面
```

### 4.3 数据库新增表

```sql
-- 测试计划
CREATE TABLE test_plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT,
    config JSON NOT NULL,        -- 完整配置（套件/设备/故障/定时）
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'draft'  -- draft/active/archived
);

-- 测试执行记录
CREATE TABLE test_runs (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    trigger_source TEXT DEFAULT 'manual',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    status TEXT DEFAULT 'running',
    environment JSON,
    results_summary JSON,
    report_path TEXT,
    FOREIGN KEY (plan_id) REFERENCES test_plans(id)
);

-- 合规检测报告
CREATE TABLE compliance_reports (
    id TEXT PRIMARY KEY,
    protocol TEXT NOT NULL,
    recording_id TEXT,
    total_messages INTEGER,
    total_rules INTEGER,
    violations JSON,
    compliance_score REAL,
    passed BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 性能测试结果
CREATE TABLE performance_results (
    id TEXT PRIMARY KEY,
    scenario_name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    metrics JSON NOT NULL,       -- {throughput, latency_p50, latency_p95, ...}
    threshold_passed BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 测试数据基线
CREATE TABLE test_baselines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    device_configs JSON,
    expected_values JSON,
    tolerance JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 五、开源版 vs 企业版 功能边界

| 功能 | 开源版（MIT） | 企业版（BUSL） |
|------|-------------|---------------|
| 21种协议仿真 | ✅ 完整 | ✅ 完整 |
| 122个设备模板 | ✅ 完整 | ✅ 完整 |
| 故障注入（9种） | ✅ 完整 | ✅ 完整 |
| 自动化测试（13种断言） | ✅ 完整 | ✅ 完整 |
| 协议录制回放 | ✅ 完整 | ✅ 完整 |
| 实时调试日志 | ✅ 完整 | ✅ 完整 |
| 场景编排 | ✅ 完整 | ✅ 完整 |
| EdgeLite集成 | ✅ 完整 | ✅ 完整 |
| 多语言SDK | ✅ 完整 | ✅ 完整 |
| **测试计划管理** | ⚠️ 最多3个计划 | ✅ 无限制 |
| **CI/CD集成** | ⚠️ 基础CLI | ✅ 高级（Webhook触发/状态回调） |
| **协议合规检测** | ❌ 不含 | ✅ 全部协议 |
| **性能基准测试** | ⚠️ 基础指标 | ✅ 全部+趋势分析 |
| **测试数据基线** | ❌ 不含 | ✅ 完整 |
| **多用户协作** | ⚠️ 最多3用户 | ✅ 无限制+SSO/LDAP |
| **PDF报告导出** | ❌ 不含 | ✅ 完整 |
| **操作审计** | ⚠️ 基础日志 | ✅ 完整审计链 |
| **SLA支持** | ❌ 社区支持 | ✅ 工作日4小时响应 |

**License切割方案**：
- v1.x 所有代码保持MIT不变
- v2.0 新增的企业功能文件头加 `// License: BUSL-1.1` 
- 在 `pyproject.toml` 中用 `tool.setuptools.package-data` 区分
- 前端企业版组件放在 `web/src/views/enterprise/` 目录

---

## 六、开发计划与里程碑

### Phase 1：测试计划 + CI/CD（第1-5周）

| 周 | 任务 | 交付物 | 验收标准 |
|----|------|--------|---------|
| W1 | 测试计划数据模型+API | `test_plan_routes.py` + 数据库迁移 | CRUD API可用，Postman验证通过 |
| W2 | 测试计划执行器 | `runner.py` | 能按计划创建设备→启动协议→跑测试套件→生成报告 |
| W3 | 前端测试计划页面 | `TestPlans.vue` | 可创建/编辑/执行/查看历史 |
| W4 | CLI工具 | `protoforge test run` | 命令行可触发执行，输出JUnit XML |
| W5 | CI/CD模板+文档 | Jenkinsfile/GitLab CI/GitHub Actions模板 | 在至少1个CI环境中跑通 |

### Phase 2：合规检测 + 性能基准（第6-10周）

| 周 | 任务 | 交付物 | 验收标准 |
|----|------|--------|---------|
| W6 | Modbus合规检测 | `compliance/modbus.py` | 对录制报文执行7条规则检测 |
| W7 | S7/OPC-UA/IEC104合规检测 | `compliance/s7.py`等 | 5种协议合规检测全部可用 |
| W8 | 合规检测前端+报告 | `Compliance.vue` + PDF导出 | 可选协议→选录制→执行→查看报告 |
| W9 | 性能基准引擎 | `performance/benchmark.py` | 可按场景运行性能测试，采集指标 |
| W10 | 性能趋势分析 | `Performance.vue` | 前端展示性能趋势图+对比视图 |

### Phase 3：协作 + 数据基线（第11-14周）

| 周 | 任务 | 交付物 | 验收标准 |
|----|------|--------|---------|
| W11 | 多用户协作+tester角色 | 权限增强+任务分配 | 可分配测试计划给特定用户 |
| W12 | 评论+通知系统 | 评论API+通知 | 可在测试结果上添加评论 |
| W13 | 测试数据基线 | `baseline.py` + API | 可创建基线、回归对比 |
| W14 | 集成测试+文档+发布 | v2.0 Release | 全部功能验证通过，文档更新 |

### Phase 4：企业版切割+发布（第15-16周）

| 周 | 任务 | 交付物 | 验收标准 |
|----|------|--------|---------|
| W15 | License切割 | BUSL文件标记 | 开源版/企业版可独立构建 |
| W16 | v2.0发布 | Release Notes + 传播物料 | Product Hunt / V2EX / 开源中国 同步发布 |

---

## 七、商业化配套

### 7.1 定价策略

| 版本 | 价格 | 目标用户 | 限制 |
|------|------|---------|------|
| **社区版** | 免费（MIT） | 个人开发者/学习者 | 3测试计划/3用户/基础CLI |
| **企业版** | ¥2-5万/年/实例 | 企业研发团队 | 无限制+合规检测+性能基准+SSO |
| **旗舰版** | ¥8-15万/年 | 大型组织 | 企业版+私有化部署+培训+SLA |
| **SaaS版** | ¥299-999/月 | 小团队 | 按设备数/测试执行次数计费 |

### 7.2 服务包

| 服务 | 价格 | 内容 |
|------|------|------|
| **协议联调服务** | ¥3万/协议 | 专家2-3天现场/远程，含合规检测报告 |
| **测试体系建设** | ¥8-15万 | 为企业定制测试计划+CI/CD流水线+培训 |
| **协议定制开发** | ¥3-10万/个 | 非标协议仿真+合规检测规则 |
| **年度技术支持** | ¥1.5万/年 | 远程排障+优先修复+版本升级指导 |
| **培训认证** | ¥3000/人 | 2天培训+认证考试+证书 |

### 7.3 获客策略

| 渠道 | 动作 | 时间 |
|------|------|------|
| **Product Hunt** | v2.0发布日打PH | W16 |
| **V2EX** | "4个月从仿真工具到测试平台"自述帖 | W16 |
| **开源中国** | 投稿"ProtoForge v2.0：工业协议测试进入CI/CD时代" | W16 |
| **知乎/CSDN** | 系列文章：协议合规检测实战 | W6-W16持续 |
| **B站** | "3分钟用ProtoForge搭建协议CI/CD流水线" | W5 |
| **QQ群** | v2.0内测邀请（优先体验企业版功能） | W12 |
| **展会BD** | 工博会/智能制造展客户定向开发 | 持续 |

---

## 八、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| 企业版功能开发周期超预期 | 高 | 中 | 严格按优先级交付，P0先出，P1/P2可延后 |
| 开源版用户不满功能切割 | 中 | 高 | 核心仿真/测试功能永远免费，只切管理/合规/性能 |
| 竞品出现 | 低 | 中 | 21种协议+EdgeLite生态是壁垒，短期难复制 |
| CI/CD集成兼容性问题 | 中 | 中 | 优先支持JUnit XML标准格式，覆盖90% CI系统 |
| 性能测试精度不足 | 中 | 中 | 使用psutil+自定义采集，明确指标定义和测量方法 |

---

## 九、成功指标

| 指标 | 当前值（v1.1.1） | v2.0目标 | 测量方式 |
|------|-----------------|---------|---------|
| GitHub Stars | 106 | 500+ | GitHub |
| Gitee Stars | 47 | 200+ | Gitee |
| QQ群人数 | ~50 | 300+ | QQ群 |
| 付费客户 | 0 | 3-5 | 合同 |
| 年收入 | 0 | 20-50万 | 财务 |
| 协议合规检测覆盖 | 0 | 5种 | 代码 |
| CI/CD集成模板 | 0 | 3种 | 代码 |
| 测试计划执行次数 | 0 | 1000+ | 系统统计 |

---

## 十、附录

### A. 竞品分析

| 产品 | 协议覆盖 | 测试能力 | CI/CD | 商业模式 | 差距 |
|------|---------|---------|-------|---------|------|
| **ModbusPal** | 仅Modbus | 无 | 无 | 免费 | 功能太窄 |
| **Mod_RSsimula** | Modbus+S7 | 无 | 无 | 付费$35 | 无测试框架 |
| **Kepware** | 150+驱动 | 无测试 | 无 | 付费$$$ | 是驱动不是仿真 |
| **Moka5** | 少量 | 无 | 无 | 免费 | 已不维护 |
| **OPC UA Demo Server** | 仅OPC-UA | 无 | 无 | 免费 | 单协议 |
| **ProtoForge v2.0** | **21种** | **计划+合规+性能** | **3种CI** | **开源+企业版** | — |

**结论**：市场上没有"工业协议仿真+自动化测试+CI/CD集成"三位一体的产品。ProtoForge v2.0填补的是这个空白。

### B. 技术选型说明

| 组件 | 选型 | 理由 |
|------|------|------|
| PDF报告 | WeasyPrint | Python原生，无外部依赖 |
| JUnit XML | 自定义模板 | 标准格式，CI系统原生支持 |
| 性能采集 | psutil + 自定义 | 轻量，无需额外依赖 |
| CLI框架 | Click/Typer | 与现有CLI一致 |
| 前端图表 | ECharts (已集成) | 性能趋势图直接用 |

### C. 与v1.x的兼容性

- v2.0完全兼容v1.x的API和配置
- v1.x的测试用例/套件可直接在v2.0测试计划中使用
- v1.x的设备模板/场景配置无需迁移
- 数据库自动迁移（Alembic新增表，不修改已有表结构）

---

*本文档是执行蓝图，不是幻想。每个功能都要回答"谁会为此付钱"。每周复盘，把本文档改旧。*
