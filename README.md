<div align="center">

# ProtoForge

**物联网协议仿真与测试平台**

[!\[Python\](https://img.shields.io/badge/Python-3.10+-blue.svg null)](https://python.org)
[!\[FastAPI\](https://img.shields.io/badge/FastAPI-0.115+-green.svg null)](https://fastapi.tiangolo.com)
[!\[Vue3\](https://img.shields.io/badge/Vue-3.x-brightgreen.svg null)](https://vuejs.org)
[!\[Naive UI\](https://img.shields.io/badge/Naive_UI-2.x-#5f25d4.svg null)](https://naiveui.com)
[!\[License\](https://img.shields.io/badge/License-MIT-yellow.svg null)](LICENSE)

[English](#english) | [中文](#中文)

</div>

***

## 中文

### ProtoForge 是什么？

ProtoForge 是一个开箱即用的物联网协议仿真与测试平台。你不需要买任何硬件，在电脑上就能模拟 PLC、传感器、摄像头等工业设备，测试你的上位机、网关、数据采集系统是否能正确通信。

**简单来说：装上就能用，点几下就能模拟出真实设备的数据。**

### ✨ 核心特性

- **17 种工业协议** — Modbus TCP/RTU、OPC-UA、MQTT、HTTP、GB28181、BACnet、Siemens S7、Mitsubishi MC、Omron FINS、Rockwell AB、OPC-DA、FANUC FOCAS、MTConnect、Mettler-Toledo、PROFINET IO、EtherCAT
- **全链路仿真** — 不只是模拟数据，完整模拟协议交互过程（如 GB28181：SIP注册→目录查询→INVITE→RTP视频推流→BYE）
- **53 设备模板** — PLC、传感器、CNC、摄像头、HVAC、伺服驱动器，选模板→起名字→一键创建
- **实时调试日志** — WebSocket 实时推送协议交互报文，按协议/方向/关键词筛选，点击查看详情，快速定位开发问题
- **可视化场景编排** — 拖拽式设备联动规则编辑器
- **一键仿真测试** — 自动生成测试用例，智能诊断问题
- **数据转发** — InfluxDB / HTTP Webhook / 文件，一键对接
- **协议录制回放** — 记录通信报文，按需回放验证
- **Prometheus 指标** — 内置监控端点，对接 Grafana
- **JWT 认证 + RBAC** — 4 种角色（admin/operator/user/viewer），100% API 端点权限覆盖，bcrypt 安全密码存储
- **API 限流保护** — 内置速率限制，防止暴力破解和滥用
- **双数据库支持** — SQLite 开箱即用，PostgreSQL 生产级支持
- **EdgeLite 网关对接** — 设备配置中填写网关地址，自动注册到 EdgeLite
- **可视化系统设置** — 前端直接修改端口和配置，无需改代码

***

### 📥 安装

#### 环境要求

- Python 3.10 或更高版本
- Node.js 18+（仅前端开发时需要）
- PostgreSQL 14+（可选，生产环境推荐）

#### 方式一：本地快速体验（推荐）

适合本地开发、测试或单机使用，直接通过 `localhost` 访问。

**Step 1 — 部署后端**

```bash
# 1. 克隆仓库
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. 安装后端依赖（FastAPI、Pydantic 等）
pip install -e .

# 3. 启动后端（默认端口 8000）
protoforge demo
```

> `protoforge demo` 会自动创建 4 个演示设备和 1 个仿真场景。
> 如果不想带演示数据，用 `protoforge run` 启动空白环境。
> 端口冲突？修改 `.env` 中的 `PROTOFORGE_PORT` 即可。

**Step 2 — 部署前端**

另开一个终端窗口：

```bash
cd ProtoForge/web

# 1. 安装前端依赖
npm install

# 2. 启动前端开发服务器（热更新，默认端口 5173）
npm run dev
```

**Step 3 — 访问系统**

打开浏览器访问 \*\*<http://localhost:5173**，用> `admin` / `admin` 登录。

> 前端开发服务器（`npm run dev`）会自动代理 API 请求到后端的 8000 端口，无需额外配置。

#### 方式二：服务器部署（Nginx + 域名）

适合生产环境，通过域名访问，Nginx 托管前端静态文件，API 代理到后端。

**部署架构：**

```
用户 → 域名 (http://your-domain.com)
    → Nginx
        → 前端静态文件 (web/dist/) 直接返回
        → /api/* 代理到后端 (127.0.0.1:8200)
        → /api/v1/ws/* WebSocket 代理到后端
```

**Step 1 — 克隆仓库**

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
```

**Step 2 — 构建前端（⚠️ 必须执行）**

> 仓库已包含前端构建产物 `web/dist/`，但建议你重新构建以确保与最新代码一致：

```bash
cd web

# 1. 安装前端依赖（需要 Node.js 18+）
npm install

# 2. 构建生产包（输出到 web/dist/）
npm run build

cd ..
```

> 如果 `web/dist/` 目录不存在，后端将无法提供前端页面，浏览器会显示空白页。

**Step 3 — 部署后端**

```bash
# 1. 安装后端依赖
pip install -e ".[all]"

# 2. 配置后端端口（避免与 Nginx 冲突）
# 编辑 .env，设置：
# PROTOFORGE_PORT=8200

# 3. 启动后端
protoforge run
```

**Step 4 — 配置 Nginx**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # API 请求 → 代理到 Python 后端
    location /api/ {
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket → 代理到 Python 后端（需升级协议）
    location /api/v1/ws/ {
        proxy_pass http://127.0.0.1:8200;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 前端静态文件 → Nginx 直接返回（高效）
    location / {
        root /path/to/ProtoForge/web/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

> 把 `8200` 换成你 `.env` 中配置的端口，把 `/path/to/ProtoForge` 换成你的实际路径。

**Step 5 — 访问系统**

打开浏览器访问 **<http://your-domain.com**，用> `admin` / `admin` 登录。

> 如果页面空白，请检查 `web/dist/` 目录是否存在。若不存在，重新执行 Step 2 构建前端。

#### 方式三：Docker 一键部署

Docker 方式已包含前后端完整构建，无需手动安装 Node.js 或构建前端。

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 启动（后台运行，自动构建前后端）
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

| 协议             | 需要额外安装？    | 默认端口  | 说明               |
| -------------- | ---------- | ----- | ---------------- |
| Modbus TCP     | 不需要        | 5020  | 工业标准通信协议         |
| HTTP           | 不需要        | 8080  | RESTful API 仿真   |
| Modbus RTU     | 不需要        | 串口    | 串口通信协议           |
| GB28181        | 不需要        | 5060  | 视频监控国标协议         |
| Mitsubishi MC  | 不需要        | 5000  | 三菱 PLC SLMP 协议   |
| Omron FINS     | 不需要        | 9600  | 欧姆龙 PLC FINS 协议  |
| Rockwell AB    | 不需要        | 44818 | 罗克韦尔 EtherNet/IP |
| OPC-DA         | 不需要        | 51340 | OPC 经典数据访问       |
| FANUC FOCAS    | 不需要        | 8193  | FANUC CNC 数据采集   |
| MTConnect      | 不需要        | 7878  | 机床数据互联标准         |
| Mettler-Toledo | 不需要        | 1701  | 称重仪表协议           |
| PROFINET IO    | 不需要        | 34964 | PI组织实时工业以太网协议    |
| EtherCAT       | 不需要        | 34980 | 倍福实时工业以太网协议      |
| OPC-UA         | `[opcua]`  | 4840  | 统一架构协议           |
| MQTT           | `[mqtt]`   | 1883  | 物联网消息协议          |
| BACnet         | `[bacnet]` | 47808 | 楼宇自动化协议          |
| Siemens S7     | `[s7]`     | 102   | 西门子 PLC 协议       |

***

### 🚀 5 分钟上手

按上述「方式一：本地快速体验」完成前后端部署后，按以下步骤操作：

1. **登录** — 浏览器打开前端地址（开发模式 `http://localhost:5173`，生产模式 `http://your-domain.com`），输入 admin / admin
2. **启动协议** — 左侧菜单「协议服务」→ 点击「一键启动」
3. **创建设备** — 左侧菜单「模板市场」→ 选择一个模板 → 填写名称 → 一键创建
4. **查看数据** — 设备列表 → 点击「测点」→ 看到实时变化的仿真数据
5. **运行测试** — 左侧菜单「仿真测试」→ 点击「一键测试全部」

***

### 🔗 EdgeLite 网关对接

ProtoForge 支持将模拟设备自动注册到 [EdgeLite](https://github.com/suoten/EdgeLiteGateway) 物联网网关，和 GB28181 填「上级SIP服务器地址」一样的体验：

```
GB28181：设备 protocol_config 填 sip_server_addr → 自动注册到国标平台
EdgeLite：设备 protocol_config 填 edgelite_url → 自动注册到 EdgeLite 网关
```

**使用方式**：创建设备时，在协议配置中填写 EdgeLite 网关地址即可：

| 字段                  | 说明            | 示例                          |
| ------------------- | ------------- | --------------------------- |
| `edgelite_url`      | EdgeLite 网关地址 | `http://192.168.1.200:8100` |
| `edgelite_username` | 用户名           | `admin`                     |
| `edgelite_password` | 密码            | `admin123`                  |

> 不填就不推送，不影响 ProtoForge 正常使用。详见 [INTEGRATION.md](INTEGRATION.md)。

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

所有配置项均可在 `.env` 文件中修改，也可登录后台在「系统设置」页面直接修改。

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
```

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

***

### 🔔 Webhook 通知和告警规则

ProtoForge 内置 Webhook 通知和告警反应规则系统，支持事件驱动的自动化。

**Webhook 通知系统**：

```bash
# 创建 Webhook
POST /api/v1/webhooks
{
  "name": "告警通知",
  "url": "https://your-server.com/webhook",
  "events": ["rule_triggered", "device_error"],
  "secret": "your-hmac-secret"   # 可选，启用 HMAC-SHA256 签名
}

# 验证签名（接收端）
# 请求头 X-ProtoForge-Signature = HMAC-SHA256(secret, body)
```

| 特性 | 说明 |
|------|------|
| 事件订阅 | 按事件类型过滤，支持通配符 `*` |
| HMAC 签名 | `X-ProtoForge-Signature` 头，防止伪造 |
| 异步队列 | 5000 条消息缓冲，批量发送 |
| 测试端点 | `POST /webhooks/{id}/test` 发送测试消息 |

**告警反应规则**：

```bash
# 创建告警规则
POST /api/v1/integration/alarm-rules
{
  "source_device_id": "device-001",
  "severity": "critical",
  "action": "stop_device"       # stop_device / inject_fault / adjust_generator
}
```

| 动作 | 说明 |
|------|------|
| `stop_device` | 自动停止触发告警的设备 |
| `inject_fault` | 向设备注入故障 |
| `adjust_generator` | 调整数据生成器参数 |

***

### 🧪 仿真测试框架

ProtoForge 内置完整的仿真测试框架，支持 14 种断言类型和 HTML 报告。

**断言类型**：

| 类型 | 说明 | 示例 |
|------|------|------|
| `equals` | 等于 | `{"expected": 100}` |
| `not_equals` | 不等于 | `{"expected": 0}` |
| `contains` | 包含 | `{"expected": "online"}` |
| `not_contains` | 不包含 | `{"expected": "error"}` |
| `greater_than` | 大于 | `{"expected": 0}` |
| `less_than` | 小于 | `{"expected": 100}` |
| `regex_match` | 正则匹配 | `{"expected": "^device-"}` |
| `json_path` | JSON 路径提取 | `{"json_path": "$.status", "expected": "ok"}` |
| `not_null` | 非空 | — |
| `type_check` | 类型检查 | `{"expected": "number"}` |
| `status_code` | HTTP 状态码 | `{"expected": 200}` |
| `length_equals` | 长度等于 | `{"expected": 10}` |
| `length_greater` | 长度大于 | `{"expected": 0}` |
| `length_less` | 长度小于 | `{"expected": 100}` |

**变量提取和钩子**：

```json
{
  "steps": [
    {
      "name": "创建设备",
      "action": "create_device",
      "extract": {"device_id": "$.id"},
      "post_hook": "log('设备创建成功')"
    },
    {
      "name": "读取测点",
      "action": "read_points",
      "params": {"device_id": "${device_id}"}
    }
  ]
}
```

**测试报告**：

- `GET /tests/reports/{id}/html` — 完整 HTML 报告（含步骤详情、断言结果、耗时统计）
- `GET /tests/reports/trend` — 历史测试趋势数据
- `POST /tests/quick-test` — 一键自动生成并运行测试
- `GET /tests/suggestions` — 根据当前状态推荐测试

***

### 🎬 场景规则引擎

4 种规则类型 × 4 种动作，支持冷却机制和 Webhook 联动。

**规则类型**：

| 类型 | 说明 | 配置示例 |
|------|------|---------|
| `threshold` | 阈值规则（支持 AND/OR 多条件） | `{"conditions": [{"operator": ">", "value": 80}], "logic": "and"}` |
| `value_change` | 值变化规则（支持 delta 阈值） | `{"delta": 10}` |
| `timer` | 定时规则 | `{"interval": 60}` |
| `script` | 脚本规则（安全沙箱） | `{"expression": "value > 80 and value < 120"}` |

**规则动作**：

| 动作 | 说明 |
|------|------|
| `set` | 设定目标测点值 |
| `toggle` | 切换布尔值 |
| `increment` | 递增 |
| `decrement` | 递减 |

**冷却机制**：在 `condition` 中设置 `cooldown`（秒），防止规则频繁触发：

```json
{"cooldown": 30, "conditions": [...]}
```

***

### 🛠 CLI 命令

| 命令 | 说明 |
|------|------|
| `protoforge run` | 启动服务（`--host` / `--port` / `--reload` / `--log-level`） |
| `protoforge demo` | 演示模式（自动创建示例设备和场景） |
| `protoforge init` | 初始化数据目录和默认配置（创建 `data/` 目录，从 `.env.example` 复制 `.env`） |
| `protoforge migrate` | 运行数据库迁移（`--revision head`） |
| `protoforge version` | 查看版本号 |

***

### 📊 性能基准参考

| 场景 | 预估参考值 | 说明 |
|------|-----------|------|
| Modbus TCP 并发连接 | ~200 连接 | 受限于文件描述符和内存 |
| MQTT 并发客户端 | ~500 连接 | aMQTT 性能有限，生产建议用 Mosquitto |
| OPC-UA 并发会话 | ~50 连接 | asyncua 资源消耗较大 |
| GB28181 RTP 推流 | ~10 路 | 受 CPU 和带宽限制 |
| 内存占用（空载） | ~150MB | Python + FastAPI 基础开销 |
| 内存占用（100 设备） | ~500MB | 含协议栈和仿真数据 |
| CPU 占用（空载） | <5% | 等待连接状态 |
| CPU 占用（100 设备活跃） | 30-60% | 取决于数据更新频率 |

> ⚠️ 以上为估算值，实际性能取决于硬件配置、协议类型和数据更新频率。建议在目标环境进行基准测试。

***

### 🔄 升级指南

**升级步骤**：

```bash
# 1. 备份数据
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/backup -o backup.json

# 2. 拉取最新代码
git pull origin main

# 3. 更新依赖
pip install -e ".[all]"

# 4. 运行数据库迁移
protoforge migrate

# 5. 重新构建前端（如有更新）
cd web && npm install && npm run build && cd ..

# 6. 重启服务
protoforge run
```

**回滚**：

```bash
# 回滚数据库到上一个版本
alembic downgrade -1

# 恢复数据备份
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @backup.json \
  http://localhost:8000/api/v1/backup/restore
```

***

### 🖥 前端开发

```bash
cd web
npm install
npm run dev     # 开发服务器（热更新）
npm run build   # 生产构建 → web/dist/
```

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
│   │   ├── rate_limit.py     # API 限流中间件
│   │   └── router.py         # API 路由
│   ├── core/                 # 核心引擎
│   │   ├── engine.py         # 仿真引擎（设备/场景调度）
│   │   ├── auth.py           # JWT 认证与 bcrypt 密码哈希
│   │   ├── edgelite.py       # EdgeLite 网关对接
│   │   ├── device.py         # 设备实例
│   │   ├── scenario.py       # 场景规则引擎
│   │   ├── testing.py        # 测试框架
│   │   ├── forward.py        # 数据转发
│   │   └── recorder.py       # 协议录制回放
│   ├── config.py             # 配置管理
│   ├── db/                   # 数据库层（SQLite + PostgreSQL）
│   ├── models/               # 数据模型
│   ├── protocols/            # 17 种协议服务端实现
│   ├── sdk/                  # Python SDK
│   └── templates/            # 53 设备模板（JSON）
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

后端启动后，访问以下地址查看交互式 API 文档（直接访问后端端口）：

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

> 这是后端 API 文档，不是前端页面。前端页面请访问前端地址（如 `http://localhost:5173`）。

***

### 📦 Python SDK

ProtoForge 提供同步和异步两种 Python SDK 客户端，覆盖全部 API 功能。

**安装**：

```bash
pip install protoforge
```

**快速上手**：

```python
from protoforge.sdk import ProtoForgeClient

# 创建客户端
with ProtoForgeClient("http://localhost:8000") as client:
    # 登录
    client.login("admin", "admin")

    # 列出所有协议
    protocols = client.list_protocols()

    # 启动 Modbus TCP 协议
    client.start_protocol("modbus_tcp")

    # 从模板快速创建设备
    device = client.quick_create("modbus-plc-controller", "测试PLC")

    # 读取设备测点
    points = client.read_points(device["id"])
    print(points)

    # 运行一键测试
    report = client.quick_test()
    print(report)
```

**异步客户端**：

```python
from protoforge.sdk import AsyncProtoForgeClient

async with AsyncProtoForgeClient("http://localhost:8000") as client:
    await client.login("admin", "admin")
    devices = await client.list_devices()
    print(devices)
```

**SDK 方法一览**（70+ 方法）：

| 类别 | 方法 | 说明 |
|------|------|------|
| 认证 | `login`, `refresh_token`, `change_password` | JWT 认证管理 |
| 协议 | `list_protocols`, `start_protocol`, `stop_protocol`, `get_protocol_config` | 协议启停和配置 |
| 设备 | `create_device`, `quick_create`, `read_points`, `write_point`, `update_device`, `delete_device` | 设备 CRUD + 测点读写 |
| 批量 | `batch_create_devices`, `batch_start_devices`, `batch_stop_devices`, `batch_delete_devices` | 批量操作 |
| 模板 | `list_templates`, `search_templates`, `instantiate_template`, `create_template` | 模板搜索和实例化 |
| 场景 | `create_scenario`, `start_scenario`, `stop_scenario`, `export_scenario`, `import_scenario` | 场景编排 |
| 测试 | `quick_test`, `create_test_case`, `run_tests`, `get_test_report` | 仿真测试 |
| 转发 | `add_forward_target`, `start_forward`, `stop_forward`, `get_forward_stats` | 数据转发 |
| 录制 | `start_recording`, `stop_recording`, `replay_recording`, `export_recording` | 协议录制回放 |
| 集成 | `import_edgelite`, `import_pygbsentry`, `list_webhooks`, `add_webhook` | 第三方集成 |
| 系统 | `get_settings`, `update_settings`, `setup_demo`, `get_setup_status` | 系统管理 |

***

### 📊 监控端点

| 端点 | 格式 | 说明 |
|------|------|------|
| `GET /health` | JSON | 健康检查（数据库状态、活跃设备数、协议状态） |
| `GET /metrics` | Prometheus | 标准指标格式（uptime、设备数、转发/录制计数） |
| `GET /api/v1/forward/stats` | JSON | 数据转发统计 |
| `GET /api/v1/recorder/stats` | JSON | 录制统计 |

***

### 🔒 安全说明

ProtoForge 内置多层安全机制：

- **密码安全**：使用 bcrypt 算法存储密码，自动加盐，抵抗彩虹表攻击
- **JWT 认证**：访问令牌有效期 30 分钟，支持刷新令牌续期
- **登录保护**：连续 5 次登录失败自动锁定账户 5 分钟，防止暴力破解
- **API 限流**：普通接口 100 次/分钟，认证接口 10 次/分钟
- **密钥管理**：JWT 密钥支持环境变量配置，未配置时自动生成随机密钥

生产环境部署前，请务必阅读 [SECURITY.md](SECURITY.md) 完成安全加固。

#### RBAC 角色权限

| 角色 | 权限说明 | 可访问端点 |
|------|---------|-----------|
| `admin` | 系统管理员，拥有全部权限 | 所有端点 + 用户管理 + 系统设置 |
| `operator` | 运维人员，可管理设备和协议 | 设备/协议/场景/转发/录制的增删改 |
| `user` | 普通用户，可运行测试 | 读操作 + 测试用例/套件的增删改 |
| `viewer` | 只读用户，仅可查看数据 | 所有 GET 端点 |

#### 协议安全说明

| 协议 | 认证支持 | 加密支持 | 说明 |
|------|---------|---------|------|
| HTTP | ✅ JWT + RBAC | ✅ HTTPS | API 端点受完整认证保护 |
| Modbus TCP | ❌ 无 | ❌ 无 | 协议本身无认证机制，建议网络隔离 |
| OPC-UA | ⚠️ 可配置 | ⚠️ 可配置 | 支持 Sign/SignAndEncrypt 模式，模板默认未启用 |
| MQTT | ⚠️ 可配置 | ⚠️ 可配置 | 支持用户名/密码认证，模板默认未启用 |
| GB28181 | ⚠️ Digest | ❌ 无 SRTP | SIP 支持 Digest 认证，RTP 流未加密 |
| S7/MC/FINS/AB | ❌ 无 | ❌ 无 | 工业协议通常在 PLC 端做访问控制 |
| BACnet | ❌ 无 | ❌ 无 | BACnet/IP 协议本身无内置认证 |

> ⚠️ 仿真环境下的协议安全限制与真实设备一致。生产部署时建议通过防火墙、VPN 或网络隔离保护协议端口。

***

### 🤝 友情链接

- [EdgeLite Gateway](https://github.com/suoten/EdgeLiteGateway) — 轻量级边缘计算物联网网关，支持 Modbus/OPC-UA/MQTT/S7 等多协议接入、规则引擎、告警系统、时序数据存储和北向平台对接。[Gitee 镜像](https://gitee.com/suoten/EdgeLiteGateway)

***

### 📄 许可证

[MIT License](LICENSE)

***

## English

### What is ProtoForge?

ProtoForge is an out-of-the-box IoT protocol simulation and testing platform. No hardware needed — simulate PLCs, sensors, cameras, and other industrial devices on your computer to test if your SCADA, gateway, or data acquisition system communicates correctly.

**In short: install it, click a few times, and you've got realistic device data flowing.**

### ✨ Key Features

- **17 Industrial Protocols** — Modbus TCP/RTU, OPC-UA, MQTT, HTTP, GB28181, BACnet, Siemens S7, Mitsubishi MC, Omron FINS, Rockwell AB, OPC-DA, FANUC FOCAS, MTConnect, Mettler-Toledo, PROFINET IO, EtherCAT
- **Full-Chain Simulation** — Not just data, complete protocol interaction (e.g. GB28181: SIP Register → Catalog Query → INVITE → RTP Video Stream → BYE)
- **53 Device Templates** — PLC, sensors, CNC, cameras, HVAC, servo drives — pick a template, name it, done
- **Real-time Debug Logs** — WebSocket live protocol interaction logs, filter by protocol/direction/keyword, click for details, quickly locate issues
- **Visual Scenario Editor** — Drag-and-drop device orchestration with rule engine
- **One-Click Testing** — Auto-generate test cases with intelligent diagnostics
- **Data Forwarding** — InfluxDB / HTTP Webhook / File, one-click integration
- **Protocol Recording & Replay** — Record communication packets, replay on demand
- **Prometheus Metrics** — Built-in monitoring endpoint for Grafana
- **JWT Auth + RBAC** — 4 roles (admin/operator/user/viewer), 100% API endpoint coverage, bcrypt secure password hashing
- **API Rate Limiting** — Built-in rate limiting to prevent brute-force and abuse
- **Dual Database Support** — SQLite out-of-the-box, PostgreSQL for production
- **EdgeLite Integration** — Auto-register devices to EdgeLite gateway via protocol config
- **Visual System Settings** — Modify ports and config from the web UI, no code changes needed

***

### 📥 Installation

#### Prerequisites

- Python 3.10+
- Node.js 18+ (only needed for frontend development)
- PostgreSQL 14+ (optional, recommended for production)

#### Option 1: Local Quick Start (Recommended)

For local development, testing, or single-machine use. Access directly via `localhost`.

**Step 1 — Deploy Backend**

```bash
# 1. Clone the repo
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. Install backend dependencies (FastAPI, Pydantic, etc.)
pip install -e .

# 3. Start backend (default port 8000)
protoforge demo
```

> `protoforge demo` creates 4 demo devices and 1 scenario automatically.
> For a clean start, use `protoforge run` instead.
> Port conflict? Just change `PROTOFORGE_PORT` in `.env`.

**Step 2 — Deploy Frontend**

Open another terminal:

```bash
cd ProtoForge/web

# 1. Install frontend dependencies
npm install

# 2. Start frontend dev server (hot reload, default port 5173)
npm run dev
```

**Step 3 — Access the System**

Open your browser at **<http://localhost:5173>** and log in with `admin` / `admin`.

> The frontend dev server (`npm run dev`) automatically proxies API requests to the backend at port 8000, no extra configuration needed.

#### Option 2: Server Deployment (Nginx + Domain)

For production environments. Access via domain name, with Nginx serving frontend static files and proxying API requests to the backend.

**Deployment Architecture:**

```
User → Domain (http://your-domain.com)
    → Nginx
        → Frontend static files (web/dist/) served directly
        → /api/* proxied to backend (127.0.0.1:8200)
        → /api/v1/ws/* WebSocket proxied to backend
```

**Step 1 — Deploy Backend**

```bash
# 1. Clone repo
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# 2. Install backend dependencies
pip install -e ".[all]"

# 3. Configure backend port (avoid conflict with Nginx)
# Edit .env and set:
# PROTOFORGE_PORT=8200

# 4. Start backend
protoforge run
```

**Step 2 — Build Frontend**

> The repo includes pre-built frontend assets in `web/dist/`, but it's recommended to rebuild to ensure consistency with the latest code:

```bash
cd ProtoForge/web

# 1. Install frontend dependencies (requires Node.js 18+)
npm install

# 2. Build for production (outputs to web/dist/)
npm run build

cd ..
```

> If the `web/dist/` directory doesn't exist, the backend won't be able to serve the frontend page and the browser will show a blank page.

**Step 3 — Configure Nginx**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # API requests → proxy to Python backend
    location /api/ {
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket → proxy to Python backend (protocol upgrade required)
    location /api/v1/ws/ {
        proxy_pass http://127.0.0.1:8200;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Frontend static files → served directly by Nginx (fast)
    location / {
        root /path/to/ProtoForge/web/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

> Replace `8200` with the port configured in your `.env`, and `/path/to/ProtoForge` with your actual path.

**Step 4 — Access the System**

Open your browser at **<http://your-domain.com>** and log in with `admin` / `admin`.

> If you see a blank page, check that the `web/dist/` directory exists. If not, re-run Step 2 to build the frontend.

#### Option 3: Docker

Docker deployment includes both frontend and backend builds — no need to manually install Node.js or build the frontend.

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge

# Start (runs in background, auto-builds frontend and backend)
docker-compose up -d

# Open http://localhost:8000 in your browser
# Default credentials: admin / admin

# Stop
docker-compose down
```

#### Optional: Install More Protocols

Modbus TCP and HTTP work out of the box. Other protocols require additional dependencies:

```bash
# Install all protocol dependencies
pip install -e ".[all]"

# Or install only what you need
pip install -e ".[opcua]"     # OPC-UA protocol
pip install -e ".[mqtt]"      # MQTT protocol
pip install -e ".[bacnet]"    # BACnet protocol
pip install -e ".[s7]"        # Siemens S7 protocol
```

| Protocol | Extra Install? | Default Port | Description |
|----------|---------------|-------------|-------------|
| Modbus TCP | No | 5020 | Industrial standard communication protocol |
| HTTP | No | 8080 | RESTful API simulation |
| Modbus RTU | No | Serial | Serial communication protocol |
| GB28181 | No | 5060 | Video surveillance national standard |
| Mitsubishi MC | No | 5000 | Mitsubishi PLC SLMP protocol |
| Omron FINS | No | 9600 | Omron PLC FINS protocol |
| Rockwell AB | No | 44818 | Rockwell EtherNet/IP |
| OPC-DA | No | 51340 | OPC Classic Data Access |
| FANUC FOCAS | No | 8193 | FANUC CNC data collection |
| MTConnect | No | 7878 | Machine tool data interop standard |
| Mettler-Toledo | No | 1701 | Weighing instrument protocol |
| PROFINET IO | No | 34964 | PI org real-time industrial Ethernet |
| EtherCAT | No | 34980 | Beckhoff real-time industrial Ethernet |
| OPC-UA | `[opcua]` | 4840 | Unified Architecture protocol |
| MQTT | `[mqtt]` | 1883 | IoT messaging protocol |
| BACnet | `[bacnet]` | 47808 | Building automation protocol |
| Siemens S7 | `[s7]` | 102 | Siemens PLC protocol |

***

### 🚀 5-Minute Quick Start

After deploying the frontend and backend using "Option 1: Local Quick Start" above, follow these steps:

1. **Login** — Open the frontend URL in your browser (dev mode `http://localhost:5173`, production `http://your-domain.com`), enter admin / admin
2. **Start Protocol** — Left menu "Protocol Services" → Click "Start All"
3. **Create Device** — Left menu "Template Market" → Pick a template → Fill in a name → One-click create
4. **View Data** — Device list → Click "Points" → See real-time simulation data
5. **Run Tests** — Left menu "Simulation Test" → Click "Quick Test All"

***

### 🔗 EdgeLite Gateway Integration

ProtoForge supports auto-registering simulated devices to [EdgeLite](https://github.com/suoten/EdgeLiteGateway) IoT gateway, just like filling in the SIP server address for GB28181:

```
GB28181: Fill sip_server_addr in protocol_config → Auto-register to national standard platform
EdgeLite: Fill edgelite_url in protocol_config → Auto-register to EdgeLite gateway
```

**Usage**: When creating a device, fill in the EdgeLite gateway address in protocol config:

| Field               | Description          | Example                     |
| ------------------- | -------------------- | --------------------------- |
| `edgelite_url`      | EdgeLite gateway URL | `http://192.168.1.200:8100` |
| `edgelite_username` | Username             | `admin`                     |
| `edgelite_password` | Password             | `admin123`                  |

> Leave empty to skip — ProtoForge works normally without it. See [INTEGRATION.md](INTEGRATION.md) for details.

***

### 🔗 Full-Chain Simulation

ProtoForge doesn't just simulate data values — it **simulates the complete protocol interaction process**.

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

### 🐛 Debug Logging

ProtoForge includes **real-time protocol debug logs** to help you quickly locate communication issues during development:

1. Open the left menu "Debug Logs"
2. View all protocol send/receive messages in real-time (WebSocket push, zero latency)
3. Filter by protocol (GB28181 / Modbus / MQTT only...)
4. Filter by direction (← Receive / → Send / System)
5. Keyword search (search "error", "register", "invite"...)
6. Click any log entry → View complete detail information
7. Pause log stream → Carefully analyze a specific message
8. Export as JSON → Offline analysis or sharing

***

### ⚙️ Configuration

All settings can be modified in the `.env` file, or directly from the web UI in "System Settings".

```bash
# .env file example
PROTOFORGE_HOST=0.0.0.0          # Web service listen address
PROTOFORGE_PORT=8000             # Web service port
PROTOFORGE_DB_PATH=data/protoforge.db  # Database path (SQLite or PostgreSQL)
PROTOFORGE_JWT_SECRET=           # JWT secret (auto-generated if empty, recommended to set in production)
PROTOFORGE_DEMO_MODE=false       # Demo mode
PROTOFORGE_LOG_LEVEL=info        # Log level

# Protocol ports (restart the corresponding protocol to take effect)
PROTOFORGE_MODBUS_TCP_PORT=5020
PROTOFORGE_OPCUA_PORT=4840
PROTOFORGE_MQTT_PORT=1883
PROTOFORGE_HTTP_PORT=8080
PROTOFORGE_GB28181_PORT=5060
```

#### Database Configuration

**SQLite (default):**

```bash
PROTOFORGE_DB_PATH=data/protoforge.db
```

**PostgreSQL (recommended for production):**

```bash
pip install -e ".[postgres]"
PROTOFORGE_DB_PATH=postgresql://user:password@localhost:5432/protoforge
```

***

### 🖥 Frontend Development

```bash
cd web
npm install
npm run dev     # Dev server with hot reload
npm run build   # Production build → web/dist/
```

***

### 🧪 Testing

```bash
python -m pytest tests/ -v
python -m pytest tests/ -v --cov=protoforge --cov-report=html
```

***

### 📐 Project Structure

```
ProtoForge/
├── protoforge/                # Python backend package
│   ├── api/v1/               # REST API endpoints
│   │   ├── common.py         # Unified response format and exception handling
│   │   ├── rate_limit.py     # API rate limiting middleware
│   │   └── router.py         # API routes
│   ├── core/                 # Core engine
│   │   ├── engine.py         # Simulation engine
│   │   ├── auth.py           # JWT auth with bcrypt password hashing
│   │   ├── edgelite.py       # EdgeLite gateway integration
│   │   ├── device.py         # Device instances
│   │   ├── scenario.py       # Scenario rule engine
│   │   ├── testing.py        # Testing framework
│   │   ├── forward.py        # Data forwarding
│   │   └── recorder.py       # Protocol recording & replay
│   ├── config.py             # Configuration management
│   ├── db/                   # Database layer (SQLite + PostgreSQL)
│   ├── models/               # Data models
│   ├── protocols/            # 17 protocol server implementations (16 dirs, Modbus TCP+RTU)
│   ├── sdk/                  # Python SDK
│   └── templates/            # 53 device templates (JSON)
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

### 🔒 Security

ProtoForge includes multiple layers of security:

- **Password Security**: bcrypt hashing with automatic salting, resistant to rainbow table attacks
- **JWT Authentication**: 30-minute access tokens with refresh token support
- **Login Protection**: 5 failed attempts trigger 5-minute account lockout, preventing brute-force attacks
- **API Rate Limiting**: 100 requests/minute for general APIs, 10/minute for auth endpoints
- **Key Management**: JWT secret configurable via environment variable, auto-generated random key if not configured

See [SECURITY.md](SECURITY.md) for production hardening.

#### RBAC Role Permissions

| Role | Description | Accessible Endpoints |
|------|------------|---------------------|
| `admin` | System administrator, full permissions | All endpoints + User management + System settings |
| `operator` | Operations staff, manage devices and protocols | CRUD for devices/protocols/scenarios/forwarding/recording |
| `user` | Regular user, can run tests | Read operations + CRUD for test cases/suites |
| `viewer` | Read-only user, view data only | All GET endpoints |

#### Protocol Security

| Protocol | Authentication | Encryption | Notes |
|----------|---------------|------------|-------|
| HTTP | ✅ JWT + RBAC | ✅ HTTPS | API endpoints fully protected by authentication |
| Modbus TCP | ❌ None | ❌ None | Protocol itself has no auth mechanism, recommend network isolation |
| OPC-UA | ⚠️ Configurable | ⚠️ Configurable | Supports Sign/SignAndEncrypt modes, template default is None |
| MQTT | ⚠️ Configurable | ⚠️ Configurable | Supports username/password auth, template default is disabled |
| GB28181 | ⚠️ Digest | ❌ No SRTP | SIP supports Digest auth, RTP stream unencrypted |
| S7/MC/FINS/AB | ❌ None | ❌ None | Industrial protocols typically rely on PLC-side access control |
| BACnet | ❌ None | ❌ None | BACnet/IP protocol has no built-in authentication |

> ⚠️ Protocol security limitations in simulation are consistent with real devices. For production deployment, protect protocol ports via firewall, VPN, or network isolation.

***

### 📡 API Documentation

After starting the backend, visit the following URLs for interactive API documentation (access the backend port directly):

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

> This is the backend API documentation, not the frontend page. For the frontend, visit the frontend URL (e.g. `http://localhost:5173`).

***

### 📦 Python SDK

ProtoForge provides both synchronous and asynchronous Python SDK clients, covering all API functionality.

**Installation**:

```bash
pip install protoforge
```

**Quick Start**:

```python
from protoforge.sdk import ProtoForgeClient

# Create client
with ProtoForgeClient("http://localhost:8000") as client:
    # Login
    client.login("admin", "admin")

    # List all protocols
    protocols = client.list_protocols()

    # Start Modbus TCP protocol
    client.start_protocol("modbus_tcp")

    # Quick create device from template
    device = client.quick_create("modbus-plc-controller", "Test PLC")

    # Read device points
    points = client.read_points(device["id"])
    print(points)

    # Run quick test
    report = client.quick_test()
    print(report)
```

**Async Client**:

```python
from protoforge.sdk import AsyncProtoForgeClient

async with AsyncProtoForgeClient("http://localhost:8000") as client:
    await client.login("admin", "admin")
    devices = await client.list_devices()
    print(devices)
```

**SDK Methods** (70+ methods):

| Category | Methods | Description |
|----------|---------|-------------|
| Auth | `login`, `refresh_token`, `change_password` | JWT authentication management |
| Protocols | `list_protocols`, `start_protocol`, `stop_protocol`, `get_protocol_config` | Protocol start/stop and config |
| Devices | `create_device`, `quick_create`, `read_points`, `write_point`, `update_device`, `delete_device` | Device CRUD + point read/write |
| Batch | `batch_create_devices`, `batch_start_devices`, `batch_stop_devices`, `batch_delete_devices` | Batch operations |
| Templates | `list_templates`, `search_templates`, `instantiate_template`, `create_template` | Template search and instantiation |
| Scenarios | `create_scenario`, `start_scenario`, `stop_scenario`, `export_scenario`, `import_scenario` | Scenario orchestration |
| Testing | `quick_test`, `create_test_case`, `run_tests`, `get_test_report` | Simulation testing |
| Forwarding | `add_forward_target`, `start_forward`, `stop_forward`, `get_forward_stats` | Data forwarding |
| Recording | `start_recording`, `stop_recording`, `replay_recording`, `export_recording` | Protocol recording & replay |
| Integration | `import_edgelite`, `import_pygbsentry`, `list_webhooks`, `add_webhook` | Third-party integration |
| System | `get_settings`, `update_settings`, `setup_demo`, `get_setup_status` | System management |

***

### 📊 Monitoring Endpoints

| Endpoint | Format | Description |
|----------|--------|-------------|
| `GET /health` | JSON | Health check (database status, active device count, protocol status) |
| `GET /metrics` | Prometheus | Standard metrics format (uptime, device count, forwarding/recording counts) |
| `GET /api/v1/forward/stats` | JSON | Data forwarding statistics |
| `GET /api/v1/recorder/stats` | JSON | Recording statistics |

***

### 🤝 Friends

- [EdgeLite Gateway](https://github.com/suoten/EdgeLiteGateway) — Lightweight edge computing IoT gateway with multi-protocol support, rule engine, alarm system, time-series storage and northbound platform integration. [Gitee Mirror](https://gitee.com/suoten/EdgeLiteGateway)

***

### 📄 License

[MIT License](LICENSE)
