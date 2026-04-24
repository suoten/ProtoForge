<div align="center">

# ProtoForge

**物联网协议仿真与测试平台**

[!\[Python\](https://img.shields.io/badge/Python-3.10+-blue.svg null)](https://python.org)
[!\[FastAPI\](https://img.shields.io/badge/FastAPI-0.115+-green.svg null)](https://fastapi.tiangolo.com)
[!\[Vue3\](https://img.shields.io/badge/Vue-3.x-brightgreen.svg null)](https://vuejs.org)
[!\[License\](https://img.shields.io/badge/License-MIT-yellow.svg null)](LICENSE)

[English](#english) | [中文](#中文)

</div>

***

## 中文

### ProtoForge 是什么？

ProtoForge 是一个开箱即用的物联网协议仿真与测试平台。你不需要买任何硬件，在电脑上就能模拟 PLC、传感器、摄像头等工业设备，测试你的上位机、网关、数据采集系统是否能正确通信。

**简单来说：装上就能用，点几下就能模拟出真实设备的数据。**

### ✨ 核心特性

- **15 种工业协议** — Modbus TCP/RTU、OPC-UA、MQTT、HTTP、GB28181、BACnet、Siemens S7、Mitsubishi MC、Omron FINS、Rockwell AB、OPC-DA、FANUC FOCAS、MTConnect、Mettler-Toledo
- **49 设备模板** — PLC、传感器、CNC、摄像头、HVAC，选模板→起名字→一键创建
- **可视化场景编排** — 拖拽式设备联动规则编辑器
- **一键仿真测试** — 自动生成测试用例，智能诊断问题
- **数据转发** — InfluxDB / HTTP Webhook / 文件，一键对接
- **协议录制回放** — 记录通信报文，按需回放验证
- **Prometheus 指标** — 内置监控端点，对接 Grafana
- **JWT 认证 + RBAC** — 多用户角色权限管理
- **可视化系统设置** — 前端直接修改端口和配置，无需改代码

***

### 📥 安装

#### 环境要求

- Python 3.10 或更高版本
- Node.js 18+（仅前端开发时需要）

#### 方式一：从源码安装（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. 安装 ProtoForge（会自动安装 FastAPI、Pydantic 等依赖）
pip install -e .

# 3. 启动！
protoforge demo
```

打开浏览器访问 \*\*<http://localhost:8000**，用> `admin` / `admin` 登录即可。

> `protoforge demo` 会自动创建 4 个演示设备和 1 个仿真场景，方便你快速体验。
> 如果不想带演示数据，用 `protoforge run` 启动空白环境。

#### 方式二：Docker 一键部署

```bash
# 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 启动（后台运行）
docker-compose up -d

# 打开浏览器访问 http://localhost:8000
# 默认账号: admin / admin

# 停止
docker-compose down
```

#### 可选：安装更多协议

Modbus TCP 和 HTTP 协议开箱即用。其他协议需要额外安装依赖：

```bash
# 安装全部协议依赖
pip install -e ".[all]"

# 或只装你需要的
pip install -e ".[opcua]"     # OPC-UA 协议
pip install -e ".[mqtt]"      # MQTT 协议
pip install -e ".[bacnet]"    # BACnet 协议
pip install -e ".[s7]"        # 西门子 S7 协议
```

| 协议             | 需要额外安装？      | 默认端口  | 说明               |
| -------------- | ------------ | ----- | ---------------- |
| Modbus TCP     | ❌ 不需要        | 5020  | 工业标准通信协议         |
| HTTP           | ❌ 不需要        | 8080  | RESTful API 仿真   |
| Modbus RTU     | ❌ 不需要        | 串口    | 串口通信协议           |
| GB28181        | ❌ 不需要        | 5060  | 视频监控国标协议         |
| Mitsubishi MC  | ❌ 不需要        | 5000  | 三菱 PLC SLMP 协议   |
| Omron FINS     | ❌ 不需要        | 9600  | 欧姆龙 PLC FINS 协议  |
| Rockwell AB    | ❌ 不需要        | 44818 | 罗克韦尔 EtherNet/IP |
| OPC-DA         | ❌ 不需要        | 51340 | OPC 经典数据访问       |
| FANUC FOCAS    | ❌ 不需要        | 8193  | FANUC CNC 数据采集   |
| MTConnect      | ❌ 不需要        | 7878  | 机床数据互联标准         |
| Mettler-Toledo | ❌ 不需要        | 1701  | 称重仪表协议           |
| OPC-UA         | ✅ `[opcua]`  | 4840  | 统一架构协议           |
| MQTT           | ✅ `[mqtt]`   | 1883  | 物联网消息协议          |
| BACnet         | ✅ `[bacnet]` | 47808 | 楼宇自动化协议          |
| Siemens S7     | ✅ `[s7]`     | 102   | 西门子 PLC 协议       |

***

### 🚀 5 分钟上手

启动后按以下步骤操作：

1. **登录** — 浏览器打开 <http://localhost:8000，输入> admin / admin
2. **启动协议** — 左侧菜单「协议服务」→ 点击「一键启动」
3. **创建设备** — 左侧菜单「模板市场」→ 选择一个模板 → 填写名称 → 一键创建
4. **查看数据** — 设备列表 → 点击「测点」→ 看到实时变化的仿真数据
5. **运行测试** — 左侧菜单「仿真测试」→ 点击「一键测试全部」

***

### ⚙️ 配置说明

所有配置项均可在 `.env` 文件中修改，也可登录后台在「系统设置」页面直接修改（修改后自动保存到 `.env`）。

```bash
# .env 文件示例
PROTOFORGE_HOST=0.0.0.0          # Web 服务监听地址
PROTOFORGE_PORT=8000             # Web 服务端口
PROTOFORGE_DB_PATH=data/protoforge.db  # 数据库路径

# 协议端口（修改后需重启对应协议生效）
PROTOFORGE_MODBUS_TCP_PORT=5020
PROTOFORGE_OPCUA_PORT=4840
PROTOFORGE_MQTT_PORT=1883
PROTOFORGE_HTTP_PORT=8080
PROTOFORGE_GB28181_PORT=5060
PROTOFORGE_BACNET_PORT=47808
PROTOFORGE_S7_PORT=102
PROTOFORGE_MC_PORT=5000
PROTOFORGE_FINS_PORT=9600
PROTOFORGE_AB_PORT=44818
PROTOFORGE_OPCDA_PORT=51340
PROTOFORGE_FANUC_PORT=8193
PROTOFORGE_MTCONNECT_PORT=7878
PROTOFORGE_TOLEDO_PORT=1701
```

> 💡 **提示**：如果端口冲突，直接在 `.env` 中改端口号，或在后台「系统设置」页面修改即可，无需改代码。

***

### 🖥 前端开发

如果你需要修改前端界面：

```bash
# 进入前端目录
cd web

# 安装前端依赖
npm install

# 启动开发服务器（热更新，修改代码自动刷新）
npm run dev

# 构建生产版本（输出到 web/dist/）
npm run build
```

> 前端开发时，后端需要单独启动（`protoforge run`），前端开发服务器默认代理 API 请求到后端。

***

### 🧪 测试

```bash
# 运行全部单元测试
python -m pytest tests/ -v
```

***

### 📐 项目结构

```
ProtoForge/
├── protoforge/                # Python 后端包
│   ├── api/v1/               # REST API 端点
│   ├── core/                 # 核心引擎
│   │   ├── engine.py         # 仿真引擎（设备/场景调度）
│   │   ├── device.py         # 设备实例
│   │   ├── scenario.py       # 场景规则引擎
│   │   ├── testing.py        # 测试框架
│   │   ├── forward.py        # 数据转发
│   │   ├── recorder.py       # 协议录制回放
│   │   └── ...
│   ├── config.py             # 配置管理
│   ├── db/                   # SQLite 数据库
│   ├── models/               # 数据模型
│   ├── protocols/            # 15 种协议服务端实现
│   ├── sdk/                  # Python SDK
│   └── templates/            # 49 设备模板（JSON）
├── web/                       # Vue3 前端
│   └── src/
│       ├── views/            # 页面组件
│       ├── App.vue           # 主布局
│       ├── api.js            # API 调用
│       └── main.js           # 入口
├── tests/                     # 测试用例
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml             # 项目配置和依赖
```

***

### 📡 API 文档

启动后访问以下地址查看交互式 API 文档：

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

主要 API 模块：

| 模块      | 端点前缀                 | 说明               |
| ------- | -------------------- | ---------------- |
| 认证      | `/api/v1/auth/`      | 登录、注册、角色管理       |
| 设备      | `/api/v1/devices/`   | 设备增删改查、测点读写      |
| 协议      | `/api/v1/protocols/` | 启停协议服务           |
| 场景      | `/api/v1/scenarios/` | 仿真场景管理           |
| 测试      | `/api/v1/tests/`     | 用例管理、一键测试        |
| 转发      | `/api/v1/forward/`   | 数据转发到 InfluxDB 等 |
| 录制      | `/api/v1/recorder/`  | 协议录制回放           |
| Webhook | `/api/v1/webhooks/`  | 事件通知             |
| 指标      | `/api/v1/metrics`    | Prometheus 格式指标  |
| 设置      | `/api/v1/settings`   | 系统配置读写          |

***

### 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

### 📄 许可证

[MIT License](LICENSE)

***

## English

### What is ProtoForge?

ProtoForge is an out-of-the-box IoT protocol simulation and testing platform. No hardware needed — simulate PLCs, sensors, cameras, and other industrial devices on your computer to test if your SCADA, gateway, or data acquisition system communicates correctly.

**In short: install it, click a few times, and you've got realistic device data flowing.**

### ✨ Key Features

- **15 Industrial Protocols** — Modbus TCP/RTU, OPC-UA, MQTT, HTTP, GB28181, BACnet, Siemens S7, Mitsubishi MC, Omron FINS, Rockwell AB, OPC-DA, FANUC FOCAS, MTConnect, Mettler-Toledo
- **49 Device Templates** — PLC, sensors, CNC, cameras, HVAC — pick a template, name it, done
- **Visual Scenario Editor** — Drag-and-drop device orchestration with rule engine
- **One-Click Testing** — Auto-generate test cases with intelligent diagnostics
- **Data Forwarding** — InfluxDB / HTTP Webhook / File, one-click integration
- **Protocol Recording & Replay** — Record communication packets, replay on demand
- **Prometheus Metrics** — Built-in monitoring endpoint for Grafana
- **JWT Auth + RBAC** — Multi-user role-based access control
- **Visual System Settings** — Modify ports and config from the web UI, no code changes needed

***

### 📥 Installation

#### Prerequisites

- Python 3.10+
- Node.js 18+ (only needed for frontend development)

#### Option 1: Install from Source (Recommended)

```bash
# 1. Clone the repo
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. Install ProtoForge (auto-installs FastAPI, Pydantic, etc.)
pip install -e .

# 3. Start!
protoforge demo
```

Open your browser at **<http://localhost:8000>** and log in with `admin` / `admin`.

> `protoforge demo` creates 4 demo devices and 1 scenario automatically.
> For a clean start, use `protoforge run` instead.

#### Option 2: Docker

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# Start (runs in background)
docker-compose up -d

# Open http://localhost:8000 in your browser
# Default credentials: admin / admin

# Stop
docker-compose down
```

#### Optional: Install More Protocols

Modbus TCP and HTTP work out of the box. Other protocols need extra dependencies:

```bash
# Install all protocol dependencies
pip install -e ".[all]"

# Or install only what you need
pip install -e ".[opcua]"     # OPC-UA
pip install -e ".[mqtt]"      # MQTT Broker
pip install -e ".[bacnet]"    # BACnet
pip install -e ".[s7]"        # Siemens S7
```

| Protocol       | Extra Install? | Default Port | Description                         |
| -------------- | -------------- | ------------ | ----------------------------------- |
| Modbus TCP     | ❌ No           | 5020         | Industrial standard                 |
| HTTP           | ❌ No           | 8080         | RESTful API simulation              |
| Modbus RTU     | ❌ No           | Serial       | Serial communication                |
| GB28181        | ❌ No           | 5060         | Video surveillance (China standard) |
| Mitsubishi MC  | ❌ No           | 5000         | Mitsubishi PLC SLMP                 |
| Omron FINS     | ❌ No           | 9600         | Omron PLC FINS                      |
| Rockwell AB    | ❌ No           | 44818        | EtherNet/IP CIP                     |
| OPC-DA         | ❌ No           | 51340        | OPC Classic Data Access             |
| FANUC FOCAS    | ❌ No           | 8193         | FANUC CNC data collection           |
| MTConnect      | ❌ No           | 7878         | Machine tool data standard          |
| Mettler-Toledo | ❌ No           | 1701         | Weighing instrument protocol        |
| OPC-UA         | ✅ `[opcua]`    | 4840         | Unified architecture                |
| MQTT           | ✅ `[mqtt]`     | 1883         | IoT messaging                       |
| BACnet         | ✅ `[bacnet]`   | 47808        | Building automation                 |
| Siemens S7     | ✅ `[s7]`       | 102          | Siemens PLC                         |

***

### 🚀 5-Minute Quick Start

1. **Login** — Open <http://localhost:8000>, enter admin / admin
2. **Start Protocols** — Menu → Protocols → Click "Start All"
3. **Create Device** — Menu → Marketplace → Pick a template → Name it → Create
4. **View Data** — Device list → Click "Points" → See live simulated data
5. **Run Tests** — Menu → Testing → Click "One-Click Test All"

***

### ⚙️ Configuration

All settings can be modified in the `.env` file, or directly from the web UI in "System Settings" (changes are auto-saved to `.env`).

```bash
# .env file example
PROTOFORGE_HOST=0.0.0.0          # Web server listen address
PROTOFORGE_PORT=8000             # Web server port
PROTOFORGE_DB_PATH=data/protoforge.db  # Database path

# Protocol ports (restart the protocol to apply changes)
PROTOFORGE_MODBUS_TCP_PORT=5020
PROTOFORGE_OPCUA_PORT=4840
PROTOFORGE_MQTT_PORT=1883
PROTOFORGE_HTTP_PORT=8080
PROTOFORGE_GB28181_PORT=5060
PROTOFORGE_BACNET_PORT=47808
PROTOFORGE_S7_PORT=102
PROTOFORGE_MC_PORT=5000
PROTOFORGE_FINS_PORT=9600
PROTOFORGE_AB_PORT=44818
PROTOFORGE_OPCDA_PORT=51340
PROTOFORGE_FANUC_PORT=8193
PROTOFORGE_MTCONNECT_PORT=7878
PROTOFORGE_TOLEDO_PORT=1701
```

> 💡 **Tip**: If a port conflicts with another service, just change it in `.env` or in the "System Settings" page — no code changes needed.

***

### 🖥 Frontend Development

```bash
cd web
npm install
npm run dev     # Dev server with hot reload
npm run build   # Production build → web/dist/
```

> When developing frontend, start the backend separately with `protoforge run`.

***

### 🧪 Testing

```bash
python -m pytest tests/ -v
```

***

### 📡 API Documentation

After starting the server, visit:

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

***

### 🤝 Contributing

Issues and Pull Requests are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

### 📄 License

[MIT License](LICENSE)
