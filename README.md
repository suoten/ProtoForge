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
- **全链路仿真** — 不只是模拟数据，完整模拟协议交互过程（如 GB28181：SIP注册→目录查询→INVITE→RTP视频推流→BYE）
- **49 设备模板** — PLC、传感器、CNC、摄像头、HVAC，选模板→起名字→一键创建
- **实时调试日志** — WebSocket 实时推送协议交互报文，按协议/方向/关键词筛选，点击查看详情，快速定位开发问题
- **可视化场景编排** — 拖拽式设备联动规则编辑器
- **一键仿真测试** — 自动生成测试用例，智能诊断问题
- **数据转发** — InfluxDB / HTTP Webhook / 文件，一键对接
- **协议录制回放** — 记录通信报文，按需回放验证
- **Prometheus 指标** — 内置监控端点，对接 Grafana
- **JWT 认证 + RBAC** — 多用户角色权限管理，bcrypt 安全密码存储
- **API 限流保护** — 内置速率限制，防止暴力破解和滥用
- **双数据库支持** — SQLite 开箱即用，PostgreSQL 生产级支持
- **可视化系统设置** — 前端直接修改端口和配置，无需改代码

***

### 📥 安装

#### 环境要求

- Python 3.10 或更高版本
- Node.js 18+（仅前端开发时需要）
- PostgreSQL 14+（可选，生产环境推荐）

#### 方式一：从源码安装（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. 安装 ProtoForge（会自动安装 FastAPI、Pydantic 等依赖）
pip install -e .

# 3. 构建前端（如果 web/dist/ 已存在可跳过）
cd web
npm install
npm run build
cd ..

# 4. 启动！
protoforge demo
```

打开浏览器访问 \*\*<http://localhost:8000**，用> `admin` / `admin` 登录即可。

> `protoforge demo` 会自动创建 4 个演示设备和 1 个仿真场景，方便你快速体验。
> 如果不想带演示数据，用 `protoforge run` 启动空白环境。
> 端口冲突？修改 `.env` 中的 `PROTOFORGE_PORT` 即可，无需改代码。

#### 方式二：宝塔面板部署

1. **安装 Python 项目**
   - 宝塔 → 网站 → Python项目 → 添加Python项目
   - 项目路径：选择 ProtoForge 目录
   - 启动命令：`protoforge run`
   - 端口：在 `.env` 中配置 `PROTOFORGE_PORT`（默认 8000）
2. **建站点 + Nginx 配置**
   - 宝塔 → 网站 → 添加站点 → 填域名/IP
   - 网站目录指向 `ProtoForge/web/dist`
   - Nginx 配置改为（**关键：Nginx 直接托管前端静态文件，只代理 API 到后端**）：
   ```nginx
   # API 请求 → 代理到 Python 后端
   location /api/ {
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }

   # WebSocket → 代理到 Python 后端（需升级协议）
   location /api/v1/ws/ {
       proxy_pass http://127.0.0.1:8000;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
   }

   # 前端静态文件 → Nginx 直接返回（高效）
   location / {
       try_files $uri $uri/ /index.html;
   }
   ```
   > 把 `8000` 换成你 `.env` 中配置的端口，把 `/www/wwwroot/your-site` 换成你的实际路径。
3. **修改端口**
   - 直接编辑 `.env` 文件中的 `PROTOFORGE_PORT`
   - 或登录后台 → 系统设置 → 修改 Web 端口 → 保存
   - 前端 API 地址无需修改（使用相对路径，自动适配）

#### 方式三：Docker 一键部署

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

### 🔗 全链路仿真

ProtoForge 不只是模拟数据值，而是**完整模拟协议交互过程**，让你在开发时就能发现通信链路中的问题。

#### GB28181 视频监控全链路

```
1. SIP REGISTER ──→ 上级平台（自动注册，支持 Digest 认证）
2. ←── MESSAGE Catalog（自动响应设备目录查询）
3. ←── INVITE（收到实时视频请求）
4. ──→ 200 OK + SDP（媒体协商应答）
5. ←── ACK
6. ══════════════► RTP/PS 视频流（25fps，352×288 CIF）
7. ←── BYE（停止视频，自动停止推流）
```

#### 其他协议全链路

| 协议         | 仿真链路                      | 使用方式                |
| ---------- | ------------------------- | ------------------- |
| Modbus TCP | 客户端连接→读寄存器→写寄存器→断开        | 你的程序作为 Modbus 客户端连接 |
| MQTT       | Broker启动→客户端订阅→数据发布→客户端收到 | 你的程序作为 MQTT 客户端连接   |
| OPC-UA     | 客户端连接→浏览节点→读写值→断开         | 你的程序作为 OPC-UA 客户端连接 |
| S7         | 客户端连接→读DB块→写DB块→断开        | 你的程序作为 S7 客户端连接     |
| HTTP       | GET/POST请求→JSON响应         | 直接请求 API            |

***

### 🐛 开发调试

ProtoForge 内置**实时协议调试日志**，帮你快速定位开发中的通信问题：

1. 打开左侧菜单「调试日志」
2. 实时查看所有协议的收发消息（WebSocket 推送，零延迟）
3. 按协议筛选（只看 GB28181 / Modbus / MQTT...）
4. 按方向筛选（← 收 / → 发 / 系统）
5. 关键词搜索（搜索 "error"、"register"、"invite"...）
6. 点击任意日志 → 查看完整 detail 信息
7. 暂停日志流 → 仔细分析某条消息
8. 导出为 JSON → 离线分析或分享

***

### ⚙️ 配置说明

所有配置项均可在 `.env` 文件中修改，也可登录后台在「系统设置」页面直接修改（修改后自动保存到 `.env`）。

```bash
# .env 文件示例
PROTOFORGE_HOST=0.0.0.0          # Web 服务监听地址
PROTOFORGE_PORT=8000             # Web 服务端口
PROTOFORGE_DB_PATH=data/protoforge.db  # 数据库路径（SQLite 或 PostgreSQL）
PROTOFORGE_JWT_SECRET=           # JWT 密钥（留空自动生成，生产环境建议设置）
PROTOFORGE_DEMO_MODE=false       # 演示模式
PROTOFORGE_LOG_LEVEL=info        # 日志级别

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

#### 数据库配置

**SQLite（默认，适合开发和单机部署）：**

```bash
PROTOFORGE_DB_PATH=data/protoforge.db
```

**PostgreSQL（生产环境推荐）：**

```bash
# 安装 PostgreSQL 支持
pip install -e ".[postgres]"

# 配置连接字符串
PROTOFORGE_DB_PATH=postgresql://user:password@localhost:5432/protoforge
```

> 使用 PostgreSQL 时，系统会自动创建连接池以支持高并发访问。

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

# 运行测试并生成覆盖率报告
python -m pytest tests/ -v --cov=protoforge --cov-report=html
```

***

### 📐 项目结构

```
ProtoForge/
├── protoforge/                # Python 后端包
│   ├── api/v1/               # REST API 端点
│   │   ├── common.py         # 统一响应格式和异常处理
│   │   └── rate_limit.py     # API 限流中间件
│   ├── core/                 # 核心引擎
│   │   ├── engine.py         # 仿真引擎（设备/场景调度）
│   │   ├── auth.py           # JWT 认证与 bcrypt 密码哈希
│   │   ├── device.py         # 设备实例
│   │   ├── scenario.py       # 场景规则引擎
│   │   ├── testing.py        # 测试框架
│   │   ├── forward.py        # 数据转发
│   │   ├── recorder.py       # 协议录制回放
│   │   └── ...
│   ├── config.py             # 配置管理
│   ├── db/                   # 数据库层（SQLite + PostgreSQL）
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
├── migrations/                # Alembic 数据库迁移
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

| 模块      | 端点前缀                 | 说明                |
| ------- | -------------------- | ----------------- |
| 认证      | `/api/v1/auth/`      | 登录、注册、角色管理（含限流保护） |
| 设备      | `/api/v1/devices/`   | 设备增删改查、测点读写       |
| 协议      | `/api/v1/protocols/` | 启停协议服务            |
| 场景      | `/api/v1/scenarios/` | 仿真场景管理            |
| 测试      | `/api/v1/tests/`     | 用例管理、一键测试         |
| 转发      | `/api/v1/forward/`   | 数据转发到 InfluxDB 等  |
| 录制      | `/api/v1/recorder/`  | 协议录制回放            |
| Webhook | `/api/v1/webhooks/`  | 事件通知              |
| 指标      | `/api/v1/metrics`    | Prometheus 格式指标   |
| 设置      | `/api/v1/settings`   | 系统配置读写            |

***

### 🔒 安全说明

ProtoForge 内置多层安全机制：

- **密码安全**：使用 bcrypt 算法存储密码，自动加盐，抵抗彩虹表攻击
- **JWT 认证**：访问令牌有效期 30 分钟，支持刷新令牌续期
- **登录保护**：连续 5 次登录失败自动锁定账户 5 分钟，防止暴力破解
- **API 限流**：普通接口 100 次/分钟，认证接口 10 次/分钟
- **密钥管理**：JWT 密钥支持环境变量配置，未配置时自动生成随机密钥

生产环境部署前，请务必阅读 [SECURITY.md](SECURITY.md) 完成安全加固。

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
- **Full-Chain Simulation** — Not just data, complete protocol interaction (e.g. GB28181: SIP Register → Catalog Query → INVITE → RTP Video Stream → BYE)
- **49 Device Templates** — PLC, sensors, CNC, cameras, HVAC — pick a template, name it, done
- **Real-time Debug Logs** — WebSocket live protocol interaction logs, filter by protocol/direction/keyword, click for details, quickly locate issues
- **Visual Scenario Editor** — Drag-and-drop device orchestration with rule engine
- **One-Click Testing** — Auto-generate test cases with intelligent diagnostics
- **Data Forwarding** — InfluxDB / HTTP Webhook / File, one-click integration
- **Protocol Recording & Replay** — Record communication packets, replay on demand
- **Prometheus Metrics** — Built-in monitoring endpoint for Grafana
- **JWT Auth + RBAC** — Multi-user role-based access control with bcrypt password hashing
- **API Rate Limiting** — Built-in rate limiting to prevent brute-force and abuse
- **Dual Database Support** — SQLite out-of-the-box, PostgreSQL for production
- **Visual System Settings** — Modify ports and config from the web UI, no code changes needed

***

### 📥 Installation

#### Prerequisites

- Python 3.10+
- Node.js 18+ (only needed for frontend development)
- PostgreSQL 14+ (optional, recommended for production)

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
> Port conflict? Just change `PROTOFORGE_PORT` in `.env` — no code changes needed.

**Note**: If the `web/dist/` directory does not exist (frontend not built), you need to build it first:

```bash
cd web
npm install
npm run build
cd ..
protoforge demo
```

#### Option 2: Server Deployment (Nginx)

1. **Run the backend** — `protoforge run` (listens on the port configured in `.env`)
2. **Set up Nginx** — Point site root to `web/dist`, proxy only API requests to backend:
   ```nginx
   # API requests → proxy to Python backend
   location /api/ {
       proxy_pass http://127.0.0.1:8100;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }

   # WebSocket → proxy with protocol upgrade
   location /api/v1/ws/ {
       proxy_pass http://127.0.0.1:8100;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
   }

   # Frontend static files → served directly by Nginx (fast)
   location / {
       try_files $uri $uri/ /index.html;
   }
   ```
3. **Frontend API address** — No changes needed (uses relative paths, auto-adapts)

#### Option 3: Docker

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

### 🔗 Full-Chain Simulation

ProtoForge doesn't just simulate data values — it **simulates the complete protocol interaction process**, so you can catch communication issues during development.

#### GB28181 Video Surveillance Full Chain

```
1. SIP REGISTER ──→ Upper platform (auto-register, supports Digest auth)
2. ←── MESSAGE Catalog (auto-responds to device catalog queries)
3. ←── INVITE (receives live video request)
4. ──→ 200 OK + SDP (media negotiation answer)
5. ←── ACK
6. ══════════════► RTP/PS video stream (25fps, 352×288 CIF)
7. ←── BYE (stop video, auto-stops streaming)
```

#### Other Protocol Full Chains

| Protocol   | Simulation Chain                                                 | How to Use                         |
| ---------- | ---------------------------------------------------------------- | ---------------------------------- |
| Modbus TCP | Client connect → Read registers → Write registers → Disconnect   | Your app connects as Modbus client |
| MQTT       | Broker start → Client subscribe → Data publish → Client receives | Your app connects as MQTT client   |
| OPC-UA     | Client connect → Browse nodes → Read/Write → Disconnect          | Your app connects as OPC-UA client |
| S7         | Client connect → Read DB blocks → Write DB blocks → Disconnect   | Your app connects as S7 client     |
| HTTP       | GET/POST request → JSON response                                 | Direct API request                 |

***

### 🐛 Development Debugging

ProtoForge includes **real-time protocol debug logs** to help you quickly locate communication issues:

1. Open "Debug Logs" from the sidebar menu
2. View all protocol messages in real-time (WebSocket push, zero latency)
3. Filter by protocol (GB28181 / Modbus / MQTT...)
4. Filter by direction (← Recv / → Send / System)
5. Keyword search ("error", "register", "invite"...)
6. Click any log → View full detail info
7. Pause log stream → Analyze a specific message
8. Export to JSON → Offline analysis or sharing

***

### ⚙️ Configuration

All settings can be modified in the `.env` file, or directly from the web UI in "System Settings" (changes are auto-saved to `.env`).

```bash
# .env file example
PROTOFORGE_HOST=0.0.0.0          # Web server listen address
PROTOFORGE_PORT=8000             # Web server port
PROTOFORGE_DB_PATH=data/protoforge.db  # Database path (SQLite or PostgreSQL)
PROTOFORGE_JWT_SECRET=           # JWT secret (auto-generated if empty, recommended for production)
PROTOFORGE_DEMO_MODE=false       # Demo mode
PROTOFORGE_LOG_LEVEL=info        # Log level

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

#### Database Configuration

**SQLite (default, suitable for development and single-node deployment):**

```bash
PROTOFORGE_DB_PATH=data/protoforge.db
```

**PostgreSQL (recommended for production):**

```bash
# Install PostgreSQL support
pip install -e ".[postgres]"

# Configure connection string
PROTOFORGE_DB_PATH=postgresql://user:password@localhost:5432/protoforge
```

> When using PostgreSQL, the system automatically creates a connection pool for high-concurrency access.

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
# Run all unit tests
python -m pytest tests/ -v

# Run tests with coverage report
python -m pytest tests/ -v --cov=protoforge --cov-report=html
```

***

### 📐 Project Structure

```
ProtoForge/
├── protoforge/                # Python backend package
│   ├── api/v1/               # REST API endpoints
│   │   ├── common.py         # Unified response format and exception handling
│   │   └── rate_limit.py     # API rate limiting middleware
│   ├── core/                 # Core engine
│   │   ├── engine.py         # Simulation engine (device/scenario scheduling)
│   │   ├── auth.py           # JWT auth with bcrypt password hashing
│   │   ├── device.py         # Device instances
│   │   ├── scenario.py       # Scenario rule engine
│   │   ├── testing.py        # Testing framework
│   │   ├── forward.py        # Data forwarding
│   │   ├── recorder.py       # Protocol recording & replay
│   │   └── ...
│   ├── config.py             # Configuration management
│   ├── db/                   # Database layer (SQLite + PostgreSQL)
│   ├── models/               # Data models
│   ├── protocols/            # 15 protocol server implementations
│   ├── sdk/                  # Python SDK
│   └── templates/            # 49 device templates (JSON)
├── web/                       # Vue3 frontend
│   └── src/
│       ├── views/            # Page components
│       ├── App.vue           # Main layout
│       ├── api.js            # API calls
│       └── main.js           # Entry point
├── tests/                     # Test cases
├── migrations/                # Alembic database migrations
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml             # Project config and dependencies
```

***

### 📡 API Documentation

After starting the server, visit:

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

***

### 🔒 Security

ProtoForge includes multiple security layers:

- **Password Security**: bcrypt hashing with automatic salting, resistant to rainbow table attacks
- **JWT Authentication**: 30-minute access tokens with refresh token support
- **Login Protection**: 5 failed login attempts trigger 5-minute account lockout
- **API Rate Limiting**: 100 requests/minute for general APIs, 10/minute for auth endpoints
- **Key Management**: JWT secret configurable via environment variable, auto-generated random key if not set

Before deploying to production, please read [SECURITY.md](SECURITY.md) for security hardening.

***

### 🤝 Contributing

Issues and Pull Requests are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

### 📄 License

[MIT License](LICENSE)
