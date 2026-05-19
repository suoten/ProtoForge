# ProtoForge

**物联网协议仿真与测试平台**

[![Python](https://flat.badgen.net/badge/Python/3.10+/blue)](https://python.org)
[![FastAPI](https://flat.badgen.net/badge/FastAPI/0.115+/green)](https://fastapi.tiangolo.com)
[![Vue3](https://flat.badgen.net/badge/Vue/3.x/brightgreen)](https://vuejs.org)
[![Naive UI](https://flat.badgen.net/badge/Naive_UI/2.x/5f25d4)](https://naiveui.com)
[![License](https://flat.badgen.net/badge/License/MIT/yellow)](LICENSE)

[中文](#中文) | [English](README_EN.md)

> ✅ **Windows**   ✅ **Linux**   ✅ **macOS**
>
> ProtoForge 后端基于 Python，前端基于 Vue.js，均为跨平台技术，三个平台均可部署使用。

***

## 中文

### ProtoForge 是什么？

ProtoForge 是一个开箱即用的物联网协议仿真与测试平台。你不需要买任何硬件，在电脑上就能模拟 PLC、传感器、摄像头等工业设备，测试你的上位机、网关、数据采集系统是否能正确通信。

**简单来说：装上就能用，点几下就能模拟出真实设备的数据。**

### ✨ 核心特性

- **17 种工业协议** — Modbus TCP/RTU、OPC-UA、MQTT、HTTP、GB28181、BACnet、Siemens S7、Mitsubishi MC、Omron FINS、Rockwell AB、OPC-DA、FANUC FOCAS、MTConnect、Mettler-Toledo、PROFINET IO、EtherCAT
- **全链路仿真** — 不只是模拟数据，完整模拟协议交互过程（如 GB28181：SIP注册→目录查询→INVITE→RTP视频推流→BYE）
- **90+ 设备模板** — PLC、传感器、CNC、摄像头、HVAC、伺服驱动器，选模板→起名字→一键创建
- **实时调试日志** — WebSocket 实时推送协议交互报文，按协议/方向/关键词筛选，点击查看详情，快速定位开发问题
- **可视化场景编排** — 可视化设备联动规则编辑器，支持阈值/值变化/定时/脚本四种规则类型
- **一键仿真测试** — 自动生成测试用例，智能诊断问题
- **数据转发** — InfluxDB / HTTP Webhook / 文件，一键对接
- **协议录制回放** — 记录通信报文，按需回放验证，支持加密存储
- **Prometheus 指标** — 内置监控端点，对接 Grafana
- **JWT 认证 + RBAC** — 4 种角色（admin/operator/user/viewer），100% API 端点权限覆盖，bcrypt 安全密码存储
- **API 限流保护** — 内置速率限制，防止暴力破解和滥用
- **双数据库支持** — SQLite 开箱即用，PostgreSQL 生产级支持
- **EdgeLite 网关对接** — 设备配置中填写网关地址，自动注册到 EdgeLite
- **可视化系统设置** — 前端直接修改端口和配置，无需改代码
- **多语言 SDK** — Python（同步/异步 90+ 方法，覆盖全部 API）、Java / Go / C#（核心方法：设备/场景/协议管理）
- **gRPC 远程管理** — 15 个 RPC 方法，支持跨语言远程调用
- **数据库备份恢复** — 一键导出/导入全库数据 JSON
- **协议安全增强** — OPC-UA 证书自动生成、MQTT TLS 加密、GB28181 SRTP、录制报文加密
- **K8s/Helm 部署** — 完整 Kubernetes 部署方案 + Helm Chart
- **故障切换** — 主备健康检查，自动晋升，回调通知
- **前端国际化** — 中英文双语，一键切换
- **Docker 多架构** — 支持 amd64/arm64（通过 docker buildx 构建），CI 自动推送 Docker Hub + PyPI

***

### 📥 安装

> **第一次使用？** 看这里就行，别被下面的文字吓到。最简单的方案：**【方式一】** 装个 Docker Desktop，复制粘贴一条命令，搞定。
>
> 源码部署的用户请注意：将仓库中的 `.env.example` 复制为 `.env`，里面已预置了开箱即用的默认参数，直接可用。生产环境务必修改 `JWT_SECRET` 和 `ADMIN_PASSWORD`。

***

#### 📋 前置条件速查

先搞清楚每种方式需要装什么，选一个适合你的：

| 需要安装的          | 方式一（Docker） | 方式二（一键脚本） | 方式三（手动） |
| -------------- | :---------: | :-------: | :-----: |
| Docker Desktop |     ✅ 必须    |     ❌     |    ❌    |
| Python 3.10+   |      ❌      |    ✅ 必须   |   ✅ 必须  |
| Node.js 18+    |      ❌      |   ⚠️ 可选¹  |   ✅ 必须  |
| Git            |      ❌      |   ✅ 必须²   |   ✅ 必须  |

> ¹ 没装 Node.js 的话，脚本会自动使用仓库中已构建好的前端文件\
> ² 需要从 GitHub 下载项目代码（可以 git clone，也可以网页下载 ZIP）

**各软件下载地址**：

| 软件                 | 下载链接                                                          | 安装提示                                     |
| ------------------ | ------------------------------------------------------------- | ---------------------------------------- |
| **Docker Desktop** | [docker.com](https://www.docker.com/products/docker-desktop/) | Windows 需启用 WSL2，macOS 直接装               |
| **Python**         | [python.org](https://www.python.org/downloads/)               | Windows 安装时**务必勾选 "Add Python to PATH"** |
| **Node.js**        | [nodejs.org](https://nodejs.org/)                             | 下载 LTS 版本（左边绿色按钮）                        |
| **Git**            | [git-scm.com](https://git-scm.com/downloads)                  | 一路点 Next 就行                              |

***

#### 🔰 方式一：Docker 极速部署（推荐所有人）

✅ Windows   ✅ Linux   ✅ macOS

最简单的方式。不需要安装 Python、Node.js、Git。新手首次打开会看到演示设备和协议，开箱即用。

**第 1 步：安装 Docker Desktop**

如果已有 Docker，跳过此步。没有的话从上面 ☝ 的表格下载安装。
安装后验证：

```bash
docker --version    # 应显示 20.x 或更高
```

**第 2 步：复制粘贴下面这条命令到终端**

```bash
docker run -d --name protoforge -p 8000:8000 -v protoforge-data:/app/data suoten/protoforge:latest
```

> 🔹 **什么是终端？** Windows 上就是 PowerShell（开始菜单搜 "powershell"）。macOS 上就是"终端"App。
>
> 🔹 不想用终端？也可以用 Docker Desktop 的图形界面：打开 Docker Desktop → Images → 搜索 `suoten/protoforge` → Pull → 然后 Run。

**第 3 步：打开浏览器**

访问 \*\*<http://localhost:8000**，用> `admin` / `admin` 登录。

你会看到预置好的演示设备、协议服务和测试场景，可以直接体验。

停止服务：

```bash
docker stop protoforge && docker rm protoforge
```

> 💡 使用内置 SQLite 数据库，数据保存在 Docker 卷中，重启不会丢失。高级用法见 [docker-compose.simple.yml](docker-compose.simple.yml)。

***

#### 🖥 方式二：一键脚本部署

✅ Windows   ✅ Linux   ✅ macOS

如果没有 Docker，也不想手动敲命令，用一键脚本。

**第 1 步：下载项目代码**

打开 <https://github.com/suoten/ProtoForge>，点击页面上的绿色 **"Code"** 按钮 → 点击 **"Download ZIP"** → 把下载的 ZIP 文件解压到一个文件夹（比如桌面）。

**第 2 步：运行安装脚本**

- **Windows**：进入解压出来的文件夹（通常叫 `ProtoForge-main`），双击 `install.bat`
- **Linux / macOS**：打开终端，进入解压出来的文件夹（通常叫 `ProtoForge-main`），运行：
  ```bash
  chmod +x install.sh
  ./install.sh
  ```

脚本会自动检测 Python 版本、创建虚拟环境、安装依赖、构建前端，最后告诉你如何启动。

**第 3 步：启动服务**

```bash
# Windows（在文件夹空白处 Shift+右键 → 在此处打开 PowerShell，然后运行）：
.\venv\Scripts\python.exe -m protoforge.cli demo

# Linux / macOS：
source venv/bin/activate
protoforge demo
```

浏览器打开 \*\*<http://localhost:8000**，用> `admin` / `admin` 登录。

> 💡 如果脚本安装依赖时卡住不动，通常是网络问题。可以先设置国内镜像再重试：
>
> ```bash
> # pip 镜像（二选一，cmd 或 PowerShell 里运行）
> pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
>
> # npm 镜像
> npm config set registry https://registry.npmmirror.com
> ```

***

#### 🔧 方式三：手动部署（开发者 / 高级用户）

✅ Windows   ✅ Linux   ✅ macOS

熟悉命令行的用户，或需要自定义配置。详细步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。

<details>
<summary><b>Windows — 点击展开</b></summary>

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[all]"
cd web && npm install && npm run build && cd ..
protoforge demo
# 浏览器打开 http://localhost:8000，用 admin / admin 登录
```

> ⚠️ 如果 `.\venv\Scripts\activate` 报错"在此系统上禁止运行脚本"，以管理员身份打开 PowerShell，运行：
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
>
> 然后重新执行 activate。

</details>

<details>
<summary><b>Linux / macOS — 点击展开</b></summary>

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
python3 -m venv venv
source venv/bin/activate
pip install -e ".[all]"
cd web && npm install && npm run build && cd ..
protoforge demo
# 浏览器打开 http://localhost:8000，用 admin / admin 登录
```

</details>

<details>
<summary><b>生产环境（Nginx + 域名 + PostgreSQL）— 点击展开</b></summary>

详见 [DEPLOYMENT.md](DEPLOYMENT.md)。大致流程：

1. 安装系统依赖：`python3`、`nodejs`、`nginx`、`postgresql`
2. 克隆代码 + 构建前端 + 安装后端依赖
3. 配置 `.env` 数据库连接和端口
4. 配置 Nginx 反向代理
5. 用 `systemd` 或 `supervisor` 管理进程

</details>

***

#### 📦 可选：安装更多协议

`pip install -e .` 只安装核心协议（Modbus TCP/RTU、HTTP、GB28181、MC、FINS、AB、OPC-DA、FANUC、MTConnect、Toledo、PROFINET、EtherCAT 共 13 种，开箱即用）。以下 4 种协议需要额外依赖：

```bash
pip install -e ".[all]"        # 安装全部 17 种协议
pip install -e ".[opcua]"     # OPC-UA
pip install -e ".[mqtt]"      # MQTT
pip install -e ".[bacnet]"    # BACnet
pip install -e ".[s7]"        # Siemens S7
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

> **前提**：已按上述任一方式完成部署，浏览器能打开 <http://localhost:8000。>
>
> 🌐 **不想安装？直接体验演示站点**：[https://protoforge.jjtt.net/](https://protoforge.jjtt.net/) 用户名：`admin`　密码：`Protoforge123`

1. **登录** — 输入 `admin` / `admin`
2. **启动协议** — 左侧菜单「协议服务」→ 点击「一键启动」
3. **创建设备** — 左侧菜单「模板市场」→ 选择一个模板 → 填写名称 → 一键创建
4. **查看数据** — 设备列表 → 点击「测点」→ 看到实时变化的仿真数据
5. **运行测试** — 左侧菜单「仿真测试」→ 点击「一键测试全部」

> ⚠️ **页面空白？** Docker 部署检查 `docker logs protoforge`。源码部署执行：`cd web && npm install && npm run build`，然后重启后端。

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
PROTOFORGE_ADMIN_PASSWORD=admin  # 管理员密码（默认 admin，生产环境务必修改！）
PROTOFORGE_DEMO_MODE=false       # 演示模式
PROTOFORGE_LOG_LEVEL=info        # 日志级别
PROTOFORGE_GRPC_PORT=0           # gRPC 端口（0=禁用，设为 50051 启用）

# 协议端口（修改后需重启对应协议生效）
PROTOFORGE_MODBUS_TCP_PORT=5020
PROTOFORGE_OPCUA_PORT=4840
PROTOFORGE_MQTT_PORT=1883
PROTOFORGE_HTTP_PORT=8080
PROTOFORGE_GB28181_PORT=5060
```

#### 端口说明

| 端口    | 服务             | 说明                                  |
| ----- | -------------- | ----------------------------------- |
| 8000  | Web API + 前端   | 主服务端口，浏览器访问此端口                      |
| 5020  | Modbus TCP     | 工业标准通信协议                            |
| 4840  | OPC-UA         | 统一架构协议（需 `[opcua]`）                 |
| 1883  | MQTT           | 物联网消息协议（需 `[mqtt]`）                 |
| 8080  | HTTP           | RESTful API 仿真                      |
| 5060  | GB28181        | 视频监控国标协议（TCP + UDP）                 |
| 47808 | BACnet         | 楼宇自动化协议（UDP，需 `[bacnet]`）           |
| 102   | Siemens S7     | 西门子 PLC 协议（需 `[s7]`）                |
| 5000  | Mitsubishi MC  | 三菱 PLC SLMP 协议                      |
| 9600  | Omron FINS     | 欧姆龙 PLC FINS 协议                     |
| 44818 | Rockwell AB    | 罗克韦尔 EtherNet/IP                    |
| 51340 | OPC-DA         | OPC 经典数据访问                          |
| 8193  | FANUC FOCAS    | FANUC CNC 数据采集                      |
| 7878  | MTConnect      | 机床数据互联标准                            |
| 1701  | Mettler-Toledo | 称重仪表协议                              |
| 34964 | PROFINET IO    | PI组织实时工业以太网协议                       |
| 34980 | EtherCAT       | 倍福实时工业以太网协议                         |
| 50051 | gRPC           | 远程管理接口（默认禁用，设 `GRPC_PORT=50051` 启用） |

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

| 特性      | 说明                                |
| ------- | --------------------------------- |
| 事件订阅    | 按事件类型过滤，支持通配符 `*`                 |
| HMAC 签名 | `X-ProtoForge-Signature` 头，防止伪造   |
| 异步队列    | 5000 条消息缓冲，批量发送                   |
| 测试端点    | `POST /webhooks/{id}/test` 发送测试消息 |

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

| 动作                 | 说明          |
| ------------------ | ----------- |
| `stop_device`      | 自动停止触发告警的设备 |
| `inject_fault`     | 向设备注入故障     |
| `adjust_generator` | 调整数据生成器参数   |

***

### 🧪 仿真测试框架

ProtoForge 内置完整的仿真测试框架，支持 14 种断言类型和 HTML 报告。

**断言类型**：

| 类型               | 说明        | 示例                                            |
| ---------------- | --------- | --------------------------------------------- |
| `equals`         | 等于        | `{"expected": 100}`                           |
| `not_equals`     | 不等于       | `{"expected": 0}`                             |
| `contains`       | 包含        | `{"expected": "online"}`                      |
| `not_contains`   | 不包含       | `{"expected": "error"}`                       |
| `greater_than`   | 大于        | `{"expected": 0}`                             |
| `less_than`      | 小于        | `{"expected": 100}`                           |
| `regex_match`    | 正则匹配      | `{"expected": "^device-"}`                    |
| `json_path`      | JSON 路径提取 | `{"json_path": "$.status", "expected": "ok"}` |
| `not_null`       | 非空        | —                                             |
| `type_check`     | 类型检查      | `{"expected": "number"}`                      |
| `status_code`    | HTTP 状态码  | `{"expected": 200}`                           |
| `length_equals`  | 长度等于      | `{"expected": 10}`                            |
| `length_greater` | 长度大于      | `{"expected": 0}`                             |
| `length_less`    | 长度小于      | `{"expected": 100}`                           |

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

| 类型             | 说明                  | 配置示例                                                               |
| -------------- | ------------------- | ------------------------------------------------------------------ |
| `threshold`    | 阈值规则（支持 AND/OR 多条件） | `{"conditions": [{"operator": ">", "value": 80}], "logic": "and"}` |
| `value_change` | 值变化规则（支持 delta 阈值）  | `{"delta": 10}`                                                    |
| `timer`        | 定时规则                | `{"interval": 60}`                                                 |
| `script`       | 脚本规则（安全沙箱）          | `{"expression": "value > 80 and value < 120"}`                     |

**规则动作**：

| 动作          | 说明      |
| ----------- | ------- |
| `set`       | 设定目标测点值 |
| `toggle`    | 切换布尔值   |
| `increment` | 递增      |
| `decrement` | 递减      |

**冷却机制**：在 `condition` 中设置 `cooldown`（秒），防止规则频繁触发：

```json
{"cooldown": 30, "conditions": [...]}
```

***

### 🛠 CLI 命令

| 命令                   | 说明                                                     |
| -------------------- | ------------------------------------------------------ |
| `protoforge run`     | 启动服务（`--host` / `--port` / `--reload` / `--log-level`） |
| `protoforge demo`    | 演示模式（自动创建示例设备和场景）                                      |
| `protoforge init`    | 初始化数据目录和默认配置（创建 `data/` 目录，从 `.env.example` 复制 `.env`） |
| `protoforge migrate` | 运行数据库迁移（`--revision head`）                             |
| `protoforge version` | 查看版本号                                                  |

***

### 📊 性能基准参考

| 场景               | 预估参考值    | 说明                         |
| ---------------- | -------- | -------------------------- |
| Modbus TCP 并发连接  | \~200 连接 | 受限于文件描述符和内存                |
| MQTT 并发客户端       | \~500 连接 | aMQTT 性能有限，生产建议用 Mosquitto |
| OPC-UA 并发会话      | \~50 连接  | asyncua 资源消耗较大             |
| GB28181 RTP 推流   | \~10 路   | 受 CPU 和带宽限制                |
| 内存占用（空载）         | \~150MB  | Python + FastAPI 基础开销      |
| 内存占用（100 设备）     | \~500MB  | 含协议栈和仿真数据                  |
| CPU 占用（空载）       | <5%      | 等待连接状态                     |
| CPU 占用（100 设备活跃） | 30-60%   | 取决于数据更新频率                  |

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
│   │   ├── audit.py          # 操作审计日志
│   │   ├── edgelite.py       # EdgeLite 网关对接
│   │   ├── device.py         # 设备实例
│   │   ├── scenario.py       # 场景规则引擎
│   │   ├── testing.py        # 测试框架（14种断言）
│   │   ├── forward.py        # 数据转发
│   │   ├── recorder.py       # 协议录制回放（含加密）
│   │   ├── failover.py       # 故障切换管理
│   │   ├── webhook.py        # Webhook 通知系统
│   │   └── metrics.py        # Prometheus 指标
│   ├── grpc/                 # gRPC 远程管理接口
│   │   ├── protoforge.proto  # Protobuf 定义
│   │   └── server.py         # gRPC 服务实现
│   ├── config.py             # 配置管理
│   ├── db/                   # 数据库层（SQLite + PostgreSQL）
│   ├── models/               # 数据模型
│   ├── protocols/            # 17 种协议服务端实现
│   ├── sdk/                  # Python SDK（同步/异步）
│   └── templates/            # 90+ 设备模板（JSON）
├── sdk/                       # 多语言 SDK
│   ├── java/                 # Java SDK
│   ├── go/                   # Go SDK
│   └── csharp/               # C# SDK
├── web/                       # Vue3 前端
│   └── src/
│       ├── views/            # 页面组件
│       ├── App.vue           # 主布局（含i18n）
│       ├── i18n.js           # 国际化框架（中英文）
│       ├── api.js            # API 调用
│       ├── main.js           # 入口
│       └── views/           # 页面组件
├── k8s/                       # Kubernetes 部署
│   ├── deployment.yaml       # ProtoForge + PostgreSQL
│   ├── ingress.yaml          # Ingress（WebSocket支持）
│   └── secrets.yaml          # 密钥配置
├── helm/                      # Helm Chart
│   └── protoforge/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/        # K8s 模板
├── tests/                     # 测试用例
├── migrations/                # Alembic 数据库迁移
├── grafana/                   # Grafana Dashboard 模板
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

| 类别 | 方法                                                                                              | 说明             |
| -- | ----------------------------------------------------------------------------------------------- | -------------- |
| 认证 | `login`, `refresh_token`, `change_password`                                                     | JWT 认证管理       |
| 协议 | `list_protocols`, `start_protocol`, `stop_protocol`, `get_protocol_config`                      | 协议启停和配置        |
| 设备 | `create_device`, `quick_create`, `read_points`, `write_point`, `update_device`, `delete_device` | 设备 CRUD + 测点读写 |
| 批量 | `batch_create_devices`, `batch_start_devices`, `batch_stop_devices`, `batch_delete_devices`     | 批量操作           |
| 模板 | `list_templates`, `search_templates`, `instantiate_template`, `create_template`                 | 模板搜索和实例化       |
| 场景 | `create_scenario`, `start_scenario`, `stop_scenario`, `export_scenario`, `import_scenario`      | 场景编排           |
| 测试 | `quick_test`, `create_test_case`, `run_tests`, `get_test_report`                                | 仿真测试           |
| 转发 | `add_forward_target`, `start_forward`, `stop_forward`, `get_forward_stats`                      | 数据转发           |
| 录制 | `start_recording`, `stop_recording`, `replay_recording`, `export_recording`                     | 协议录制回放         |
| 集成 | `import_edgelite`, `import_pygbsentry`, `list_webhooks`, `add_webhook`                          | 第三方集成          |
| 系统 | `get_settings`, `update_settings`, `setup_demo`, `get_setup_status`                             | 系统管理           |

**Java SDK**（`sdk/java/ProtoForgeClient.java`）：

```java
import io.github.suoten.protoforge.ProtoForgeClient;

public class Example {
    public static void main(String[] args) throws Exception {
        ProtoForgeClient client = new ProtoForgeClient("http://localhost:8000");
        client.login("admin", "admin");
        var devices = client.listDevices();
        System.out.println(devices);
    }
}
```

**Go SDK**（`sdk/go/protoforge/client.go`）：

```go
package main

import (
    "fmt"
    "protoforge"
)

func main() {
    client := protoforge.NewClient("http://localhost:8000")
    client.Login("admin", "admin")
    devices, _ := client.ListDevices()
    fmt.Println(devices)
}
```

**C# SDK**（`sdk/csharp/ProtoForgeClient.cs`）：

```csharp
using ProtoForge;

var client = new ProtoForgeClient("http://localhost:8000");
await client.LoginAsync("admin", "admin");
var devices = await client.ListDevicesAsync();
Console.WriteLine(devices);
```

***

### 📊 监控端点

| 端点                           | 格式         | 说明                         |
| ---------------------------- | ---------- | -------------------------- |
| `GET /health`                | JSON       | 健康检查（数据库状态、活跃设备数、协议状态）     |
| `GET /metrics`               | Prometheus | 标准指标格式（uptime、设备数、转发/录制计数） |
| `GET /api/v1/forward/stats`  | JSON       | 数据转发统计                     |
| `GET /api/v1/recorder/stats` | JSON       | 录制统计                       |

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

| 角色         | 权限说明          | 可访问端点              |
| ---------- | ------------- | ------------------ |
| `admin`    | 系统管理员，拥有全部权限  | 所有端点 + 用户管理 + 系统设置 |
| `operator` | 运维人员，可管理设备和协议 | 设备/协议/场景/转发/录制的增删改 |
| `user`     | 普通用户，可运行测试    | 读操作 + 测试用例/套件的增删改  |
| `viewer`   | 只读用户，仅可查看数据   | 所有 GET 端点          |

#### 协议安全说明

| 协议            | 认证支持         | 加密支持        | 说明                                |
| ------------- | ------------ | ----------- | --------------------------------- |
| HTTP          | ✅ JWT + RBAC | ✅ HTTPS     | API 端点受完整认证保护                     |
| Modbus TCP    | ❌ 无          | ❌ 无         | 协议本身无认证机制，建议网络隔离                  |
| OPC-UA        | ⚠️ 可配置       | ⚠️ 可配置      | 支持 Sign/SignAndEncrypt 模式，模板默认未启用 |
| MQTT          | ⚠️ 可配置       | ⚠️ 可配置      | 支持用户名/密码认证，模板默认未启用                |
| GB28181       | ⚠️ Digest    | ⚠️ 可配置 SRTP | SIP 支持 Digest 认证，RTP 流可启用 SRTP 加密 |
| S7/MC/FINS/AB | ❌ 无          | ❌ 无         | 工业协议通常在 PLC 端做访问控制                |
| BACnet        | ❌ 无          | ❌ 无         | BACnet/IP 协议本身无内置认证               |

> ⚠️ 仿真环境下的协议安全限制与真实设备一致。生产部署时建议通过防火墙、VPN 或网络隔离保护协议端口。

#### 协议安全增强

| 协议      | 安全特性                      | 配置方式                                                                  |
| ------- | ------------------------- | --------------------------------------------------------------------- |
| OPC-UA  | ✅ 证书自动生成（RSA-2048，10年有效期） | `security_mode=Sign` 时自动生成，也可指定 `certificate_path`/`private_key_path` |
| MQTT    | ✅ TLS 加密通道                | 配置 `tls_enabled=true` + `tls_cert_path`/`tls_key_path`                |
| GB28181 | ✅ SRTP 加密传输               | 配置 `srtp_enabled=true`                                                |
| 录制回放    | ✅ 报文加密存储                  | 调用 `recorder.set_encryption_key("your-key")` 启用                       |

***

### 💾 数据库备份与恢复

```bash
# 导出全库备份（含设备/场景/模板/测试/用户/录制/审计日志）
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/backup -o backup.json

# 恢复备份
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @backup.json \
  http://localhost:8000/api/v1/backup/restore
```

> 备份文件为标准 JSON 格式，可版本控制、差异对比、跨环境迁移。

***

### 🔌 gRPC 远程管理

设置 `PROTOFORGE_GRPC_PORT` 环境变量即可启用 gRPC 服务：

```bash
PROTOFORGE_GRPC_PORT=50051 protoforge run
```

**15 个 RPC 方法**：

| 方法                                                            | 说明   |
| ------------------------------------------------------------- | ---- |
| `GetHealth`                                                   | 健康检查 |
| `ListDevices` / `GetDevice` / `CreateDevice` / `DeleteDevice` | 设备管理 |
| `StartDevice` / `StopDevice`                                  | 设备启停 |
| `ReadPoints` / `WritePoint`                                   | 测点读写 |
| `ListScenarios` / `StartScenario` / `StopScenario`            | 场景管理 |
| `GetSettings` / `UpdateSettings`                              | 系统设置 |

**生成客户端代码**：

```bash
# Python
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. protoforge/grpc/protoforge.proto

# Go
protoc --go_out=. --go-grpc_out=. protoforge/grpc/protoforge.proto

# Java
protoc --java_out=. --grpc-java_out=. protoforge/grpc/protoforge.proto

# C#
protoc --csharp_out=. --grpc-csharp_out=. protoforge/grpc/protoforge.proto
```

***

### ☸️ Kubernetes / Helm 部署

**方式一：直接使用 K8s YAML**

```bash
# 1. 创建 Secret（修改密码！）
kubectl apply -f k8s/secrets.yaml

# 2. 部署应用 + PostgreSQL
kubectl apply -f k8s/deployment.yaml

# 3. 配置 Ingress（可选）
kubectl apply -f k8s/ingress.yaml
```

**方式二：使用 Helm Chart**

```bash
# 1. 修改配置
helm show values helm/protoforge > my-values.yaml
# 编辑 my-values.yaml：修改密码、域名、存储等

# 2. 安装
helm install protoforge helm/protoforge -f my-values.yaml

# 3. 升级
helm upgrade protoforge helm/protoforge -f my-values.yaml

# 4. 卸载
helm uninstall protoforge
```

**Helm values 主要配置**：

| 参数                        | 默认值                 | 说明            |
| ------------------------- | ------------------- | ------------- |
| `replicaCount`            | `1`                 | 副本数           |
| `image.repository`        | `suoten/protoforge` | 镜像仓库          |
| `ingress.enabled`         | `false`             | 启用 Ingress    |
| `postgresql.enabled`      | `true`              | 内置 PostgreSQL |
| `persistence.size`        | `5Gi`               | 数据持久化大小       |
| `resources.limits.memory` | `1Gi`               | 内存限制          |

***

### 🔄 故障切换

配置主备模式实现自动故障切换：

```bash
# 主节点
PROTOFORGE_FAILOVER_ROLE=primary
PROTOFORGE_FAILOVER_PRIMARY=http://primary:8000
PROTOFORGE_FAILOVER_STANDBY=http://standby:8000
PROTOFORGE_FAILOVER_INTERVAL=10  # 健康检查间隔（秒）

# 备节点
PROTOFORGE_FAILOVER_ROLE=standby
PROTOFORGE_FAILOVER_PRIMARY=http://primary:8000
PROTOFORGE_FAILOVER_STANDBY=http://standby:8000
```

**工作原理**：

1. 备节点定期检查主节点 `/health` 端点
2. 连续 3 次检查失败后，备节点自动晋升为主节点
3. 晋升时触发回调通知（可注册自定义回调）
4. 原主节点恢复后，可手动降级为备节点

***

### ❓ 常见问题排查

#### 后端相关

**Q:** **`pip install -e .`** **报** **`externally-managed-environment`？**

A: 你没有激活虚拟环境。请先在项目目录执行：

```bash
python -m venv venv
# Windows: .\venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -e .
```

**Q:** **`protoforge run`** **报** **`No module named 'protoforge'`？**

A: 依赖还没装，先执行 `pip install -e .`。

**Q: 启动后打开** **`http://localhost:8000`** **看到 Swagger 文档？**

A: 8000 是后端 API 端口，那个文档是给开发者看的。前端访问地址是：

- 开发模式：`http://localhost:5173`
- 生产模式 / Docker：`http://localhost:8000`（后端直接托管前端）

**Q: 某些协议（OPC-UA / MQTT / BACnet / S7）启动失败？**

A: 这些协议需要额外安装依赖，只用 `pip install -e .` 是不够的。请执行：

```bash
pip install -e ".[all]"    # 安装全部协议
# 或按需安装：
pip install -e ".[opcua]"  # OPC-UA
pip install -e ".[mqtt]"   # MQTT
pip install -e ".[s7]"     # Siemens S7
pip install -e ".[bacnet]" # BACnet
```

**Q: 端口被占用（`port already in use`）？**

A: 编辑项目根目录的 `.env` 文件，修改对应端口的配置。也可以运行：

```bash
# Windows 查看端口占用
netstat -ano | findstr :8000
# macOS / Linux
lsof -i :8000
```

#### 前端相关

**Q:** **`npm install`** **报错或很慢？**

A: 检查 Node.js 版本是否 ≥ 18：

```bash
node --version
```

如果版本太低，去 [nodejs.org](https://nodejs.org/) 下载 LTS 版。

如果网络慢，可设置国内镜像：

```bash
npm config set registry https://registry.npmmirror.com
```

**Q: 前端页面空白？**

A: 按你的部署方式排查：

**源码 / Nginx 部署：**

- 最常见原因：`web/dist/` 目录不存在。执行 `cd web && npm install && npm run build` 构建前端。
- Nginx 部署：检查 `nginx -t` 配置是否正确，`root` 路径是否指向了正确的 `web/dist/`。
- 开发模式：确认后端已启动（另一个终端里 `protoforge run` 在运行），且访问的是 `http://localhost:5173`（不是 8000）。

**Docker 部署：**

- 检查容器日志：`docker logs protoforge`，看是否有 "前端静态文件目录不存在" 的警告。如果有，说明 Docker 镜像构建时前端编译失败了。
- 确认访问的是 `http://localhost:8000`（Docker 模式后端直接托管前端）。

**通用排查：**

- 打开浏览器开发者工具（F12）→ Console / Network，看是否有红色报错或 404 请求。
- 检查后端是否正常：访问 `/api/v1/health` 看是否返回 JSON。

**Q: Linux 上部署失败？**

A: 按以下步骤逐项排查：

1. **检查 Python 版本** — `python3 --version`，需要 ≥ 3.10。如果版本太低，用 `apt install python3.12` 或 `dnf install python3.12`。
2. **检查 Node.js 版本** — `node --version`，需要 ≥ 18。如果 apt 装的版本太旧，用 NodeSource 安装：
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
   sudo apt install -y nodejs
   ```
3. **检查虚拟环境** — 是否激活了 venv？（终端前面应该有 `(venv)` 前缀）
4. **检查端口** — `lsof -i :8000`（或你设置的端口），确认没有被其他进程占用。
5. **检查 .env 配置** — `cat .env`，确认 `PROTOFORGE_PORT` 等配置正确。
6. **查看后端日志** — 如果用的 `nohup`，查看 `protoforge.log`；如果用的 `systemd`，查看 `journalctl -u protoforge`。
7. **从源码安装时** — 确保用了 `pip install -e "."`（带引号和点号），不是 `pip install -e .`（Unix shell 下点号会被解释成当前目录，两者效果相同但格式要正确）。

**如果是串口相关错误（Modbus RTU）：** Linux 上没有 `COM1`，默认使用 `/dev/ttyUSB0`。如果你没有物理串口，在设备的协议配置中设置 `port=0` 即可自动切换到 TCP 桥接模式。

#### Docker 相关

**Q:** **容器启动后频繁重启？**

A: 通常是内存不够。试试用简易部署模式（纯 SQLite，内存更低）：

```bash
docker compose -f docker-compose.simple.yml up -d
```

或者直接用预构建镜像：

```bash
docker run -d --name protoforge -p 8000:8000 -v protoforge-data:/app/data suoten/protoforge:latest
```

**Q:** **`docker compose`** **命令报错？**

A: 检查你的 Docker 版本。新版 Docker 用 `docker compose`（无连字符），旧版用 `docker-compose`。试试哪个能用：

```bash
docker compose version   # 或 docker-compose --version
```

**Q: Docker 构建时** **`npm run build`** **失败？**

A: 建议用 Docker Hub 上的预构建镜像 `suoten/protoforge:latest`，跳过编译步骤：

```bash
docker run -d --name protoforge -p 8000:8000 suoten/protoforge:latest
```

如果你必须从源码构建，最新 Dockerfile 已使用 NodeSource 安装 Node.js 20.x（LTS），确保版本可靠。

#### 其他

**Q: 忘记管理员密码怎么办？**

A: 删除 `data/protoforge.db` 文件（SQLite 模式）然后重启，系统会自动创建默认账号 `admin / admin`。

> ⚠️ 这会清空所有数据！如果数据重要，请先备份 `data/` 目录。

**Q: 怎么备份数据？**

A: 登录后进入「系统设置」页面，点击「导出备份」按钮即可下载 JSON 文件。也可以直接用命令：

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/v1/backup -o backup.json
```

Token 可以在浏览器开发者工具（F12）→ Application → Local Storage → token 中找到。

***

### 🔗 相关项目

| 项目                                                           | 说明                        | 仓库地址                                                                                                    |
| ------------------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------- |
| [EdgeLiteGateway](https://github.com/suoten/EdgeLiteGateway) | 轻量级边缘计算物联网网关，22 种工业协议开箱即用 | [Gitee](https://gitee.com/suoten/EdgeLiteGateway) · [GitHub](https://github.com/suoten/EdgeLiteGateway) |

***

### 💬 社区交流

[![QQ群](https://flat.badgen.net/badge/QQ%E7%BE%A4/866599071/eb1923)](https://qm.qq.com/q/ProtoForge) **进群答案：ProtoForge**

