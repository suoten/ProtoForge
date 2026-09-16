<div align="center">

<!-- PROJECT LOGO -->
<br />
<h1>🖥️ ProtoForge</h1>
<p><b>一台电脑 = 26 种工业设备</b></p>
<p>零成本模拟 PLC、传感器、摄像头，测试你的上位机和物联网网关</p>

[![Python](https://img.shields.io/static/v1?label=Python&message=3.10%2B&color=blue&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/static/v1?label=FastAPI&message=0.115%2B&color=green&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue](https://img.shields.io/static/v1?label=Vue&message=3.x&color=brightgreen&logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![License](https://img.shields.io/static/v1?label=License&message=MIT&color=yellow&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Docker](https://img.shields.io/static/v1?label=Docker&message=%E6%9E%81%E9%80%9F%E9%83%A8%E7%BD%B2&color=blue&logo=docker&logoColor=white)](https://hub.docker.com/r/suoten/protoforge)

[🚀 在线体验](https://protoforge.jjtt.net) · [📖 5分钟上手](#-5分钟上手) · [💬 加入QQ群](https://qm.qq.com/cgi-bin/qm/qr?k=8jGiq7UgneoOCuc5SV-FOFsb49mlmEhK&jump_from=webapi&authKey=efY0P+0PSa3KjkWLsg4Kt1M7+pQZPv7iBiwRkn6e5u8MbzK8cklSKSwvY3WGrnFa) · [English](README_EN.md)

> ✅ **Windows** · ✅ **Linux** · ✅ **macOS**
>
> 🔥 **V1.3.0 工业标杆版** · 131 设备模板 · 26 种工业协议 · 设备/场景克隆 · 北向平台预设 · DAG 规则链编排 · 测试计划+合规检测 · EdgeLite 生态对接

![仪表盘](docs/images/1.png)

</div>

---

## 🔥 为什么选 ProtoForge？

### 💢 开发者的真实痛点

| # | 你遇到的痛点 | 有多痛 | ProtoForge 怎么解决 |
|---|------------|--------|-------------------|
| 1 | **协议报文对不上，不知道哪里错了** | 客户说读不到数据，你抓包看 hex 对了半天，3天找不到原因 | WebSocket 实时调试日志，按协议/方向/关键词筛选，点击查看报文详情，秒级定位问题 |
| 2 | **模拟器太乖，上线就出事** | 测试环境永远返回正确值，上线后真实 PLC 断连/超时/返回异常码，全炸 | 内置9种故障注入：传感器卡死/漂移/噪声/失效、间歇断连/延迟/丢包、设备故障/执行器卡死，上线前测全异常场景 |
| 3 | **测试全靠手点，回归一下午** | 每次改完代码：手动建设备→启动→读数据→验证，一个回归搞一下午 | 自动化测试引擎：13种断言、变量提取、测试套件、HTML报告+趋势分析，SDK一行代码跑全部测试 |
| 4 | **客户现场出问题，没法复现** | 客户说昨天下午3点数据不对，没有录制，没法回放，只能猜 | 协议录制回放：录制通信报文→按需回放→验证修复，Gzip压缩存储 |
| 5 | **新人不懂协议，教1周才干活** | 地址偏移、功能码、字节序全搞混，手把手教还是出错 | 每个协议内置4语言代码示例(Python/C#/Java/Go)，131个模板即用型配置，照着抄就能干 |
| 6 | **多协议联调，环境搭1周** | 同时测 Modbus+S7+MQTT，找3台不同厂商设备，配3套参数 | 26种协议一台电脑全搞定，Docker 30秒启动，一键生成100台虚拟设备 |
| 7 | **协议安全不敢测** | OPC-UA证书/TLS加密/GB28181 SRTP，生产不敢动，测试又没有 | 证书自动生成、TLS加密、SRTP全支持，安全场景随便测 |

### 💰 硬件成本对比

| 场景 | 传统方式 | ProtoForge |
|------|---------|------------|
| 测 Modbus | 买 PLC（￥3000+） | 1 条命令启动虚拟设备 |
| GB28181 联调 | 买摄像头（￥500+） | 自动注册、自动推流 |
| 测 26 种协议 | 买各种厂商设备（￥50000+） | 一台电脑全部模拟 |
| 压力测试 | 部署几十台物理设备 | 一键生成 100 台虚拟设备 |
| 给客户演示 | 带一堆硬件出差 | 笔记本上完整演示 |

---

## ⚡ 30 秒启动（Docker 推荐）

```bash
docker run -d --name protoforge -p 8000:8000 -e PROTOFORGE_ADMIN_PASSWORD=admin -v protoforge-data:/app/data suoten/protoforge:latest
```

浏览器打开 **http://localhost:8000**，用 `admin` / `admin` 登录。

> 💡 第一次使用？这就是最简单的方式，不需要安装 Python、Node.js、Git。
>
> 🌐 **http://localhost:8000 就是 Web 界面**，不是只有 API。ProtoForge 的后端（FastAPI）会自动托管前端页面，不需要单独的 Nginx 或前端服务器。API 文档在 `/docs`，前端页面直接访问根路径 `/`。
>
> 🔐 **密码说明**：
> - 上面的命令通过 `-e PROTOFORGE_ADMIN_PASSWORD=admin` 指定了密码为 `admin`
> - 如果不加这个参数，系统会自动生成随机密码，查看方式：`docker logs protoforge`（找 `Login:` 那一行）
> - 生产环境请务必修改为强密码

---

## 🎬 功能预览

### 📊 仪表盘 — 全局状态一目了然

设备总数、运行中协议、仿真场景、设备模板数量实时统计，快速操作入口一键触达。

![仪表盘](docs/images/1.png)

### 🔧 设备管理 — 所有仿真设备集中管控

支持按协议筛选、批量启停、快速创建。每台设备显示协议类型、在线状态、测点数量，支持测点读写、链路追踪、编辑配置。

![设备管理](docs/images/2.png)

### 🌐 协议服务 — 26 种工业协议一键启停

Modbus TCP/RTU、OPC-UA、MQTT、HTTP、GB28181、BACnet、Siemens S7、Mitsubishi MC、Omron FINS、Rockwell AB、OPC-DA、FANUC FOCAS、MTConnect、Mettler-Toledo、PROFINET IO、EtherCAT、IEC 60870-5-104、IEC 61850、CoAP、DDS，全部支持独立配置端口和高级参数。

![协议服务](docs/images/3.png)

### 🏭 仿真场景 — 组合多设备定义联动规则

创建场景、批量管理设备集合，支持导入导出，快速复现工厂环境。

![仿真场景](docs/images/4.png)

### 🎨 场景编排器 — 可视化拖拽设备拓扑

自由拖拽布局设备节点，直观展示设备间关系，支持保存布局、添加设备、一键启停整个场景。

![场景编排器](docs/images/5.png)

### 📦 模板市场 — 131 设备模板开箱即用

PLC、传感器、数控机床、IoT 设备、摄像头、楼宇设备、电力保护装置、IED、环境传感器等分类筛选，选择模板一键创建仿真设备。

![模板市场](docs/images/6.png)

### 🧪 仿真测试 — 自动生成测试用例

系统根据当前设备和场景自动生成测试任务，一键验证测点读写、场景启停、规则触发等功能。

![仿真测试](docs/images/7.png)

### 📋 测试计划 — 版本化测试用例管理

创建测试计划，定义测试套件和故障场景，一键执行并生成 JUnit XML / JSON / HTML 报告。支持克隆、版本管理、执行历史追踪，CI/CD 集成一行命令搞定。

### 🛡️ 合规检测 — 协议标准合规性验证

内置 Modbus TCP、S7、OPC-UA、IEC 104、MQTT 五大协议合规检测器，一键检测通信报文是否符合协议标准，生成合规评分和违规详情报告。

### 🐛 调试日志 — 实时协议报文追踪

WebSocket 零延迟推送，按协议/方向筛选，关键词搜索，支持暂停、导出 JSON，快速定位开发问题。

![调试日志](docs/images/8.png)

### 🔗 联调集成 — EdgeLite 网关无缝对接

对接 EdgeLite 网关，完成设备注册→连接→采集→验证→监控的完整联调链路，5 步可视化流程一目了然。

![联调集成](docs/images/9.png)

### ⚙️ 系统设置 — 可视化配置无需改代码

服务器端口、数据库路径、日志级别、CORS 源、InfluxDB 转发、协议端口等全部可在前端直接修改。

![系统设置](docs/images/10.png)

### 🛡️ 审计日志 — 全操作留痕

用户操作、资源变更全程记录，支持按用户名、操作类型、资源类型筛选审计。

![审计日志](docs/images/11.png)

### 💾 备份恢复 — 一键导出导入全库数据

将设备、场景、模板和审计日志导出为 JSON 备份文件，跨环境迁移、版本控制、灾难恢复轻松搞定。

![备份恢复](docs/images/12.png)

---

## ✨ 核心特性

- **26 种工业协议** — Modbus TCP/RTU、OPC-UA、MQTT、HTTP、GB28181、BACnet、Siemens S7/S7Comm-Plus、Mitsubishi MC、Omron FINS、Rockwell AB、OPC-DA、FANUC FOCAS、MTConnect、Mettler-Toledo、PROFINET IO、EtherCAT、IEC 60870-5-104、IEC 61850、CoAP、DDS、DLT/T 645、CJ/T 188、自定义 TCP/UDP
- **全链路仿真** — 不只是模拟数据，完整模拟协议交互过程（如 GB28181：SIP注册→目录查询→INVITE→RTP视频推流→BYE）
- **131 设备模板** — PLC、传感器、CNC、摄像头、HVAC、伺服驱动器、保护继电器、IED、环境传感器、微电网、智能电表、水/气/热表，选模板→起名字→一键创建
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
- **CSV 批量导入导出** — 设备配置一键导出 CSV，批量导入快速创建多台设备，跨环境迁移效率倍增
- **录制回放压缩** — Gzip 压缩存储，节省磁盘空间
- **数据库备份恢复** — 一键导出/导入全库数据 JSON
- **协议安全增强** — OPC-UA 证书自动生成、MQTT TLS 加密、GB28181 SRTP、录制报文加密
- **K8s/Helm 部署** — 完整 Kubernetes 部署方案 + Helm Chart
- **IoT 测试平台** — 测试计划管理（版本化/克隆/执行历史）、协议合规检测（5 协议合规规则+评分报告）、JUnit/JSON/HTML 报告导出、CI/CD 集成（`protoforge test run`）
- **故障切换** — 主备健康检查，自动晋升，回调通知
- **前端国际化** — 中英文双语，一键切换
- **Docker 多架构** — 支持 amd64/arm64（通过 docker buildx 构建），CI 自动推送 Docker Hub + PyPI

***

## 📥 更多安装方式

### 方式二：一键脚本部署

✅ Windows · ✅ Linux · ✅ macOS

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

脚本会自动检测 Python 版本、创建虚拟环境、安装依赖、构建前端，然后自动启动服务。

**启动后**，浏览器打开 **http://localhost:8000**（即脚本窗口显示的地址），用 `admin` / 你设置的密码 登录。

> 🌐 **http://localhost:8000 就是 Web 界面**。后端自动托管前端，不需要 Nginx。

> 💡 如果脚本安装依赖时卡住不动，通常是网络问题。可以先设置国内镜像再重试：
>
> ```bash
> # pip 镜像（二选一，cmd 或 PowerShell 里运行）
> pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
>
> # npm 镜像
> npm config set registry https://registry.npmmirror.com
> ```

### 方式三：手动部署（开发者 / 高级用户）

✅ Windows · ✅ Linux · ✅ macOS

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
# 浏览器打开 http://localhost:8000，用 admin / admin 登录（demo 模式默认密码，旧数据也会自动同步）
# 可用环境变量 PROTOFORGE_ADMIN_PASSWORD 覆盖；正式模式（protoforge run）密码随机生成，见启动横幅
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
# 或后台运行：protoforge demo -d
# 停止后台服务：protoforge stop
# 浏览器打开 http://localhost:8000，用 admin / admin 登录（demo 模式默认密码，旧数据也会自动同步）
# 可用环境变量 PROTOFORGE_ADMIN_PASSWORD 覆盖；正式模式（protoforge run）密码随机生成，见启动横幅
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

#### 📋 前置条件速查

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

#### 📦 可选：安装更多协议

`pip install -e .` 只安装核心协议（Modbus TCP/RTU、HTTP、GB28181、MC、FINS、AB、OPC-DA、FANUC、MTConnect、Toledo、PROFINET、EtherCAT、IEC 104、IEC 61850、CoAP、DDS 共 17 种，开箱即用）。以下 4 种协议需要额外依赖：

```bash
pip install -e ".[all]"        # 安装全部 26 种协议
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
| IEC 60870-5-104 | 不需要      | 2404  | 电力远动协议 (SCADA)    |
| IEC 61850       | 不需要        | 102   | 变电站自动化标准 (MMS)   |
| CoAP           | 不需要        | 5683  | 受限 IoT 应用协议 (UDP) |
| DDS            | 不需要        | 7400  | 数据分发服务 (发布/订阅)  |

***

## 🚀 5 分钟上手

> **前提**：已按上述任一方式完成部署，浏览器能打开 <http://localhost:8000。>
>
> 🌐 **不想安装？直接体验演示站点**：[https://protoforge.jjtt.net/](https://protoforge.jjtt.net/) 用户名：`admin`　密码：`Protoforge123`

1. **登录** — 输入 `admin` / `admin`
2. **启动协议** — 左侧菜单「协议服务」→ 点击「一键启动」
3. **创建设备** — 左侧菜单「模板市场」→ 选择一个模板 → 填写名称 → 一键创建
4. **查看数据** — 设备列表 → 点击「测点」→ 看到实时变化的仿真数据
5. **运行测试** — 左侧菜单「仿真测试」→ 点击「一键测试全部」

> ⚠️ **页面空白？** Docker 部署检查 `docker logs protoforge`。源码部署执行：`cd web && npm install && npm run build`，然后重启后端。

> 📖 **需要更详细的操作指引？** 请阅读完整的 [操作手册](docs/USER_GUIDE.md)，涵盖设备创建、协议连接、场景编排、故障注入、数据转发、调试排障等全流程。

***

## 🔗 与第三方系统对接

### ProtoForge 是什么？—— 一句话搞懂

> **ProtoForge 是一台「虚拟设备工厂」。它启动标准协议服务端（Modbus TCP Server、OPC-UA Server、S7 Server……），任何能连接这些协议的软件都能直接对接，不需要任何适配层或特殊 SDK。**

### 对接架构图

```
                    ┌─────────────────────────────────┐
                    │        ProtoForge（仿真端）         │
                    │                                   │
                    │  Modbus TCP Server  ←─ 端口 5020  │
                    │  OPC-UA Server      ←─ 端口 4840  │
                    │  S7 Server          ←─ 端口 102   │
                    │  MQTT Broker        ←─ 端口 1883  │
                    │  HTTP Server        ←─ 端口 8080  │
                    │  GB28181 SIP        ←─ 端口 5060  │
                    │  ...（26 种协议服务端）              │
                    └──────────┬──────────────────────┘
                               │ 标准 TCP/UDP 协议通信
                               │（和真实设备一模一样）
          ┌──────────┬─────────┼─────────┬──────────┐
          ▼          ▼         ▼         ▼          ▼
     ┌─────────┐ ┌────────┐ ┌───────┐ ┌───────┐ ┌─────────┐
     │ EdgeLite│ │Kepware │ │Node-RED│ │Ignition│ │ 你的程序 │
     │  网关   │ │  网关  │ │       │ │ SCADA │ │(pymodbus│
     │         │ │        │ │       │ │       │ │  等)   │
     └─────────┘ └────────┘ └───────┘ └───────┘ └─────────┘
       自动注册      手动配置    手动配置   手动配置    直接连接
```

### 三种对接方式

| 方式 | 适合场景 | 怎么做 |
|------|---------|--------|
| **① 直接连接**（推荐） | 你有自己的采集程序或网关 | ProtoForge 启动协议服务后，你的程序作为客户端连接对应端口即可（如 pymodbus 连 5020） |
| **② EdgeLite 自动注册** | 你用 EdgeLite 做网关 | 设备配置中填 `edgelite_url`，ProtoForge 自动把设备配置推送到 EdgeLite，免手动配置 |
| **③ 标准网关手动配置** | 你用 Kepware/Node-RED/Ignition 等第三方网关 | 在网关中手动添加设备，地址填 ProtoForge 的 IP 和端口（如 `127.0.0.1:5020`） |

### 方式 ①：直接连接（最通用）

ProtoForge 启动协议服务后，任何协议客户端都能直接连接。**不需要在 ProtoForge 做任何额外配置。**

```python
# Python — 用 pymodbus 连接 ProtoForge 的 Modbus TCP 仿真设备
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("127.0.0.1", port=5020)
client.connect()
result = client.read_holding_registers(address=100, count=2, device_id=1)
print(f"温度: {result.registers}")
```

```javascript
// Node.js — 用 mqtt 库连接 ProtoForge 的 MQTT 仿真设备
import mqtt from 'mqtt'
const client = mqtt.connect('mqtt://127.0.0.1:1883')
client.on('message', (topic, message) => {
  console.log(`${topic}: ${message.toString()}`)
})
client.subscribe('sensor/temperature')
```

> ⚠️ **MQTT 连接注意事项**
>
> - 内置 MQTT Broker 仅支持 **MQTT 3.1.1** 协议，**不支持 MQTT 5.0**。MQTTX 等客户端连接时，请在连接设置中手动将 **Protocol Version** 选为 `3.1.1`（默认 5.0 会连接失败，这是最常踩的坑）。
> - MQTT 仿真设备还支持**上报到你自己的 MQTT 服务器**：在设备协议配置中填写「自定义 MQTT 服务器」（`server_host` / `server_port`，可选认证用户名密码），设备将以 MQTT 客户端身份连接并上报数据 —— EMQX / Mosquitto / 阿里云 IoT 等均可对接。

> 💡 **其他协议的数据外送**：Modbus / S7 / OPC-UA / IEC104 等协议中，仿真设备是“被访问的服务端”（由你的主站/网关连接设备），不存在“设备外连上报”的语义；若需把这些设备的数据推送到你自己的 HTTP 服务器，请使用平台的数据转发功能。GB28181 仿真设备本身就会主动向你配置的 SIP 平台注册。

### 📍 PLC 地址映射 — 精确到每个测点

ProtoForge 的每个测点都绑定了**具体的 PLC 协议地址**，你的上位机/网关按这个地址去读，和读真实 PLC 一模一样。

#### 各协议地址格式

| 协议 | 地址格式 | 示例 | 说明 |
| ---- | ------- | ---- | ---- |
| **Modbus TCP/RTU** | 寄存器偏移量（数字） | `address: "0"` | 寄存器 40001（holding register），`"2"` = 40003。**布尔量（bool）点位自动落线圈区（0xxxxx）**：主站用功能码 01 读线圈、05 写线圈，读保持寄存器（FC03）看不到布尔量点位 |
| **Siemens S7** | DB块.类型+偏移 | `address: "DB1.DBD2"` | DB块1，D=双字，偏移2字节；`DBX` = 位，`DBW` = 字 |
| **Omron FINS** | 区域+地址 | `address: "DM100"` | DM区域地址100；`CIO0` = CIO区域地址0 |
| **Mitsubishi MC** | 设备号+地址 | `address: "D100"` | D寄存器100；`M0` = 中间继电器0 |
| **OPC-UA** | 节点ID | `address: "ns=2;s=Temperature"` | 命名空间2，节点名 Temperature |
| **IEC 60870-5-104** | ASDU地址 | `address: "1"` | IOA（信息对象地址）= 1 |

#### 完整示例：智能水表模板（Modbus TCP）

设备模板中的测点定义：

```json
{
  "name": "total_flow",
  "address": "0",           // ← Modbus 寄存器 40001
  "data_type": "float32",
  "unit": "m³",
  "generator_type": "increment",
  "min_value": 0,
  "max_value": 999999
}
```

你的采集程序这样读：

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("127.0.0.1", port=5020)
client.connect()

# 读 total_flow（address=0 → 寄存器 40001，float32 占 2 个寄存器）
result = client.read_holding_registers(address=0, count=2, slave_id=1)
# 解析 float32
value = struct.unpack('>f', struct.pack('>HH', *result.registers))[0]
print(f"累计流量: {value} m³")

# 读 instant_flow（address=2 → 寄存器 40003）
result = client.read_holding_registers(address=2, count=2, slave_id=1)
# 同样解析 float32
```

#### 完整示例：西门子 S7-1200 模板

```json
{
  "name": "temperature",
  "address": "DB1.DBD2",     // ← DB块1，双字，偏移2
  "data_type": "real",
  "unit": "°C"
}
```

用 snap7 读取：

```python
import snap7

client = snap7.client.Client()
client.connect("127.0.0.1", 0, 1)  # rack=0, slot=1

# 读 DB1.DBD2（Real/Float，4字节）
data = client.db_read(1, 2, 4)       # db_number=1, start=2, size=4
temperature = snap7.util.get_real(data, 0)
print(f"温度: {temperature} °C")
```

#### 完整示例：欧姆龙 FINS 模板

```json
{
  "name": "motor_speed",
  "address": "DM100",       // ← DM区域地址100
  "data_type": "int16"
}
```

> 💡 **在 Web 界面查看地址**：设备管理 → 点击「数据测点」→ 可以看到每个测点的名称、当前值、时间、质量。点击「编辑」设备可以查看和修改每个测点的协议地址、数据类型、生成器参数。
>
> 💡 **自定义地址**：创建设备时可以自由指定每个测点的 PLC 地址，完全匹配你真实设备的地址表。

#### Modbus 寄存器类型与功能码映射

ProtoForge 支持完整的 Modbus 四种寄存器区域，通过地址格式自动识别：

| 寄存器区域 | 地址格式示例 | Modbus 地址范围 | 功能码 | 说明 |
| --------- | ----------- | -------------- | ------ | ---- |
| **线圈 (Coil)** | `0`, `00001`, `0x0`, `C0` | 00001–09999 | FC01 读 / FC05 写单 / FC0F 写多 | 位操作，可读可写 |
| **离散输入 (Discrete Input)** | `10001`, `1x0`, `DI0` | 10001–19999 | FC02 读 | 位操作，只读 |
| **输入寄存器 (Input Register)** | `30001`, `3x0`, `IR0`, `I0` | 30001–39999 | FC04 读 | 字操作，只读 |
| **保持寄存器 (Holding Register)** | `0`, `40001`, `4x0`, `HR0`, `H0` | 40001–49999 | FC03 读 / FC06 写单 / FC10 写多 | 字操作，可读可写 |

> 💡 **纯数字地址的自动判断规则**：`bool` 类型 → 线圈 (Coil)；其他类型 → 保持寄存器 (Holding Register)。如果你想使用输入寄存器或离散输入，请使用 `30001`、`10001` 等 5 位 PLC 地址格式，或 `IR0`、`DI0` 等前缀格式。

#### 数据类型与寄存器占用

不同数据类型占用的寄存器数量和字节序：

| 数据类型 | 字节数 | 占用寄存器数 | 字节序 | 适用协议 |
| -------- | ----- | ----------- | ------ | ------- |
| `bool` | 1 bit | 1 (位) | — | Modbus (Coil/DI)、S7 (DBX)、FINS (CIO bit) |
| `int16` | 2 | 1 | 大端序 (Big-Endian) | Modbus、S7 (DBW)、FINS、MC |
| `uint16` | 2 | 1 | 大端序 | Modbus、S7、MC |
| `int32` | 4 | 2 | 大端序 | Modbus、S7 (DBD)、MC |
| `uint32` | 4 | 2 | 大端序 | Modbus、S7、MC |
| `float32` | 4 | 2 | 大端序 (IEEE 754) | Modbus、S7 (DBD Real)、FINS、MC |
| `float64` | 8 | 4 | 大端序 (IEEE 754) | Modbus、S7 |
| `string` | 可变 | 可变 (每寄存器 2 字节) | 大端序 (UTF-8) | Modbus、S7 |
| `real` | 4 | 2 | 大端序 | S7 专用（等同 float32） |

> ⚠️ **字节序说明**：ProtoForge 所有协议统一使用**大端序 (Big-Endian)**，这是工业设备最常用的字节序。如果你的上位机使用小端序，需要在采集端做字节翻转。
>
> 例如：`float32` 值 `1.0` 在 ProtoForge 中存储为 `0x3F800000`，拆分为两个寄存器 → `HR[n]=0x3F80, HR[n+1]=0x0000`。用 pymodbus 读取后：`struct.unpack('>f', struct.pack('>HH', 0x3F80, 0x0000))` → `1.0`。

#### 📋 从真实地址表创建设备教程

假设你有一份设备说明书上的 Modbus 地址表：

| 参数名 | Modbus 地址 | 数据类型 | 单位 | 读写 |
| ------ | ----------- | -------- | ---- | ---- |
| A相电压 | 40001 | float32 | V | RO |
| B相电压 | 40003 | float32 | V | RO |
| 有功功率 | 40005 | float32 | kW | RO |
| 功率因数 | 40007 | float32 | - | RO |
| 开关状态 | 00001 | bool | - | RW |

**第 1 步：转换为 ProtoForge 地址格式**

| 参数名 | 说明书地址 | ProtoForge address | data_type |
| ------ | --------- | ------------------ | --------- |
| A相电压 | 40001 | `0` (40001-40001=0) | float32 |
| B相电压 | 40003 | `2` (40003-40001=0) | float32 |
| 有功功率 | 40005 | `4` | float32 |
| 功率因数 | 40007 | `6` | float32 |
| 开关状态 | 00001 | `00001` 或 `0` | bool |

> 💡 **5 位 PLC 地址自动转换**：你也可以直接填 `40001`、`30001`、`10001`、`00001`，ProtoForge 会自动减去基地址（40001→偏移 0，30001→偏移 0）。

**第 2 步：在 Web 界面创建设备**

1. 进入「设备管理」→ 点击「创建设备」
2. 选择协议 `modbus_tcp`，填写设备名称
3. 在测点配置中，逐条添加上表中的参数
4. 设置 `slave_id`（如 `1`）
5. 保存并启动设备

**第 3 步：用你的采集程序验证**

```python
from pymodbus.client import ModbusTcpClient
import struct

client = ModbusTcpClient("127.0.0.1", port=5020)
client.connect()

# 读 A相电压 (address=0, float32, 占2个寄存器)
result = client.read_holding_registers(address=0, count=2, slave_id=1)
voltage_a = struct.unpack('>f', struct.pack('>HH', *result.registers))[0]

# 读 B相电压 (address=2)
result = client.read_holding_registers(address=2, count=2, slave_id=1)
voltage_b = struct.unpack('>f', struct.pack('>HH', *result.registers))[0]

# 读开关状态 (address=00001 → coil 0)
result = client.read_coils(address=0, count=1, slave_id=1)
switch_status = result.bits[0]

print(f"A相电压: {voltage_a}V, B相电压: {voltage_b}V, 开关: {'ON' if switch_status else 'OFF'}")
```

**就是这么简单——ProtoForge 的地址和真实设备完全一致，你的采集代码不需要改一行。**

#### Modbus RTU 串口配置

Modbus RTU 模板支持完整的串口参数配置：

```json
{
  "protocol": "modbus_rtu",
  "protocol_config": {
    "slave_id": 2,
    "serial_port": "COM3",
    "baudrate": 9600,
    "databits": 8,
    "parity": "even",
    "stopbits": 1
  }
}
```

| 参数 | 说明 | 可选值 | 默认值 |
| ---- | ---- | ------ | ------ |
| `serial_port` | 串口设备路径 | Windows: `COM3`; Linux: `/dev/ttyUSB0` | — |
| `baudrate` | 波特率 | `1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200` | `9600` |
| `databits` | 数据位 | `7, 8` | `8` |
| `parity` | 校验位 | `none, even, odd` | `even` |
| `stopbits` | 停止位 | `1, 1.5, 2` | `1` |

> 💡 **无串口硬件也能用**：ProtoForge 的 Modbus RTU 模式在没有物理串口时也可以启动（使用虚拟串口或 TCP-over-RTU 桥接）。在 Linux 上可以用 `socat` 创建虚拟串口：`socat -d -d PTY,raw,echo=0 PTY,raw,echo=0`。

#### 多设备共存仿真

ProtoForge 支持在**同一协议端口**下同时仿真多台设备，就像一条 RS-485 总线上挂多个从站：

**Modbus 多 Slave 共存**：

```
设备A: slave_id=1, 协议=modbus_tcp, 端口=5020
设备B: slave_id=2, 协议=modbus_tcp, 端口=5020  ← 同端口不同 slave_id
设备C: slave_id=3, 协议=modbus_tcp, 端口=5020
```

采集程序通过 `slave_id` 区分不同设备：

```python
# 读设备A的数据
result = client.read_holding_registers(address=0, count=2, slave_id=1)
# 读设备B的数据
result = client.read_holding_registers(address=0, count=2, slave_id=2)
```

> 💡 每个 Modbus 设备在创建时可以指定不同的 `slave_id`，它们共享同一协议端口但拥有独立的数据空间。

**S7/OPC-UA/MQTT 等协议多设备**：每种协议都支持在同端口下创建多台虚拟设备，通过设备名/节点空间区分。

#### 写入行为说明

当你的采集程序向 ProtoForge 写入数据时，行为与真实 PLC 完全一致：

| 操作 | ProtoForge 响应 | 后续读取行为 |
| ---- | --------------- | ----------- |
| **写单个线圈 (FC05)** | 返回正常响应（回显地址+值） | 读该地址返回写入的值 |
| **写多个线圈 (FC0F)** | 返回正常响应（回显起始地址+数量） | 读该地址范围返回写入的值 |
| **写单个寄存器 (FC06)** | 返回正常响应（回显地址+值） | 读该地址返回写入的值 |
| **写多个寄存器 (FC10)** | 返回正常响应（回显起始地址+数量） | 读该地址范围返回写入的值 |
| **读写多个寄存器 (FC17)** | 返回读部分的值 | 写入部分同时生效 |
| **掩码写寄存器 (FC16)** | 返回正常响应 | 按掩码 AND/OR 逻辑更新寄存器 |

> ⚠️ **写入与生成器的关系**：如果测点配置了 `generator_type`（如 `random`、`sine`），生成器会在每次更新周期覆盖写入的值。要保留写入值，请将 `generator_type` 设为 `fixed`。

#### 数据更新频率与生成器

每个测点可以配置数据生成器来模拟真实设备的变化行为：

| 生成器类型 | 说明 | 关键参数 | 适用场景 |
| ---------- | ---- | -------- | ------- |
| `fixed` | 固定值 | `fixed_value` | 状态量、开关 |
| `random` | 随机值 | `min_value`, `max_value` | 传感器噪声模拟 |
| `sine` | 正弦波 | `min_value`, `max_value`, `period` | 周期性变化量 |
| `increment` | 递增值 | `min_value`, `max_value`, `step` | 流量计、计数器 |
| `ramp` | 线性变化 | `start_value`, `end_value`, `duration` | 渐变过程模拟 |

```json
{
  "name": "temperature",
  "address": "0",
  "data_type": "float32",
  "generator_type": "sine",
  "min_value": 20.0,
  "max_value": 80.0,
  "period": 60,
  "update_frequency": 1.0
}
```

| 参数 | 说明 | 默认值 |
| ---- | ---- | ------ |
| `update_frequency` | 数据更新频率（秒/次） | `1.0`（1秒更新一次） |
| `period` | 正弦周期（秒） | `60` |
| `step` | 递增步长 | `1.0` |
| `duration` | 渐变持续时间（秒） | `10` |

> 💡 `update_frequency` 决定了数据多久变化一次。设为 `0.5` 表示每 0.5 秒更新一次（2Hz），设为 `5` 表示每 5 秒更新一次。这与真实设备的采样周期类似。

### 方式 ②：EdgeLite 自动注册（便捷）

如果你用 [EdgeLite](https://github.com/suoten/EdgeLiteGateway) 做网关，ProtoForge 可以自动把设备配置推送过去，免去手动在 EdgeLite 中添加设备的步骤。详见下方 [EdgeLite 网关对接](#-edgelite-网关对接) 章节。

### 方式 ③：标准网关手动配置（Kepware / Node-RED / Ignition 等）

以 Kepware 为例：

1. ProtoForge 中启动 Modbus TCP 协议服务（默认端口 5020）
2. ProtoForge 中创建一台 Modbus 设备（记住 slave_id 和测点地址）
3. Kepware 中新建一个 Modbus TCP 驱动，IP 填 ProtoForge 所在机器 IP，端口填 5020
4. Kepware 中新建设备，slave_id 与 ProtoForge 中一致
5. Kepware 中添加点位，地址与 ProtoForge 中一致

**就是这么简单——ProtoForge 对你的网关来说，和一台真实 PLC 没有任何区别。**

> 💡 **核心理解**：ProtoForge 不是网关，不采集数据，不转发数据。它是「被采集的对象」——一台虚拟设备。你的网关/SCADA/采集程序去连它，就像连真实设备一样。

***

## 🔗 EdgeLite 网关对接

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

### 🔌 EdgeLite 联合一键部署（推荐）

不想手动配置两套系统？ProtoForge 提供 `docker-compose.joint.yml`，**一条命令同时启动 ProtoForge + EdgeLite + MQTT + InfluxDB**，开箱即用联调。

#### 第 1 步：准备配置文件

```bash
# 复制环境变量模板
cp .env.joint.example .env.joint

# 用编辑器打开 .env.joint，把所有 change_me_* 改成你自己的密码
# 重点修改这几项：
#   PROTOFORGE_ADMIN_PASSWORD=你的强密码
#   PROTOFORGE_JWT_SECRET=至少32位随机字符串
#   EDGELITE_ADMIN_PASSWORD=你的强密码
#   SECRET_KEY=至少32位随机字符串
```

> 💡 JWT 密钥可以用这个命令生成：`python -c "import secrets; print(secrets.token_urlsafe(32))"`

#### 第 2 步：一键启动

```bash
docker compose -f docker-compose.joint.yml --env-file .env.joint up -d
```

等待 30 秒让所有服务就绪，然后：

- **ProtoForge 界面**：http://localhost:8000 （用 `.env.joint` 里的 `PROTOFORGE_ADMIN_PASSWORD` 登录）
- **EdgeLite 界面**：http://localhost:8081 （用 `.env.joint` 里的 `EDGELITE_ADMIN_PASSWORD` 登录）

#### 第 3 步：验证联调

1. 打开 ProtoForge（http://localhost:8000），创建一台 Modbus 设备，在协议配置中填写：
   ```
   edgelite_url: http://edgelite:8100
   edgelite_username: admin
   edgelite_password: （你在 .env.joint 里设的 EDGELITE_ADMIN_PASSWORD）
   ```
2. 启动设备的 Modbus 协议，ProtoForge 会自动把设备推送到 EdgeLite
3. 打开 EdgeLite（http://localhost:8081），在设备列表中能看到刚推送的设备，数据实时采集

> 🔍 也可以调用 ProtoForge 的 API 一键验证全链路：
> ```bash
> curl -X POST http://localhost:8000/api/v1/edgelite/verify-pipeline \
>   -H "Authorization: Bearer <你的token>" \
>   -H "Content-Type: application/json" \
>   -d '{"device_id": "你的设备ID", "auto_fix": true}'
> ```
> 返回 `{"ok": true}` 说明认证→注册→连接→采集四步全通。

#### 📋 端口映射表

联合部署后，以下端口被占用（如需修改请在 `.env.joint` 中调整）：

| 服务 | 端口 | 说明 |
|------|------|------|
| ProtoForge Web/API | 8000 | 主界面 + REST API |
| ProtoForge Modbus TCP | 5020 | Modbus 仿真设备 |
| ProtoForge OPC-UA | 4840 | OPC-UA 仿真设备 |
| ProtoForge MQTT | 1883 | MQTT 仿真设备 |
| ProtoForge HTTP | 8080 | HTTP Webhook 仿真 |
| EdgeLite Web/API | 8081 | EdgeLite 管理界面（避让 ProtoForge 8080） |
| EdgeLite MQTT | 1884 | EdgeLite MQTT 服务（避让 ProtoForge 1883） |
| InfluxDB | 8086 | 时序数据库 |

#### 🛠 故障排查 FAQ

**Q: 启动时报端口占用？**
A: 检查本机是否已有其他服务占用上述端口。Windows 用 `netstat -ano | findstr :8000`，Linux 用 `lsof -i:8000`。可在 `.env.joint` 中修改端口映射。

**Q: EdgeLite 设备列表里看不到推送的设备？**
A: ① 确认设备协议配置里的 `edgelite_url` 填的是 `http://edgelite:8100`（容器内网名），不是 `localhost`；② 在 ProtoForge 调用 `verify-pipeline` API 看具体哪一步失败；③ 查看 EdgeLite 日志 `docker compose -f docker-compose.joint.yml logs edgelite`。

**Q: 联调 API 返回 401？**
A: EdgeLite 密码不匹配。确认设备配置里的 `edgelite_password` 与 `.env.joint` 中的 `EDGELITE_ADMIN_PASSWORD` 一致。首次登录 EdgeLite 可能要求改密码，改完后同步更新 ProtoForge 设备配置。

**Q: 停止联合部署？**
A: `docker compose -f docker-compose.joint.yml down`（加 `-v` 会同时删除数据卷，谨慎使用）。

***

## 🔗 全链路仿真

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

## 🐛 开发调试

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

## ⚙️ 配置说明

所有配置项均可在 `.env` 文件中修改，也可登录后台在「系统设置」页面直接修改。

```bash
# .env 文件示例
PROTOFORGE_HOST=0.0.0.0          # Web 服务监听地址
PROTOFORGE_PORT=8000             # Web 服务端口
PROTOFORGE_DB_PATH=data/protoforge.db  # 数据库路径（SQLite 或 PostgreSQL）
PROTOFORGE_JWT_SECRET=           # JWT 密钥（留空自动生成，生产环境建议设置）
PROTOFORGE_ADMIN_PASSWORD=admin  # 管理员密码（不设置则自动生成随机密码，生产环境务必设置强密码！）
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
| 2404  | IEC 60870-5-104 | 电力远动协议（SCADA）                      |
| 102   | IEC 61850       | 变电站自动化标准（MMS）                      |
| 5683  | CoAP           | 受限 IoT 应用协议（UDP）                    |
| 7400  | DDS            | 数据分发服务（发布/订阅）                      |
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

## 🔔 Webhook 通知和告警规则

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

## 🧪 仿真测试框架

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

## 🎬 场景规则引擎

5 种规则类型 × 5 种动作，支持冷却机制、多设备协同链式联动和时间序列回放。

**规则类型**：

| 类型              | 说明                   | 配置示例                                                               |
| --------------- | -------------------- | ------------------------------------------------------------------ |
| `threshold`     | 阈值规则（支持 AND/OR 多条件）  | `{"conditions": [{"operator": ">", "value": 80}], "logic": "and"}` |
| `value_change`  | 值变化规则（支持 delta 阈值）   | `{"delta": 10}`                                                    |
| `timer`         | 定时规则                 | `{"interval": 60}`                                                 |
| `script`        | 脚本规则（安全沙箱）           | `{"expression": "value > 80 and value < 120"}`                     |
| `collaboration` | 多设备协同联动（链式动作 + 故障注入） | 见下方协同联动示例                                                          |

**规则动作**：

| 动作              | 说明                  |
| --------------- | ------------------- |
| `set`           | 设定目标测点值             |
| `toggle`        | 切换布尔值               |
| `increment`     | 递增                  |
| `decrement`     | 递减                  |
| `inject_fault`  | 注入故障（传感器噪声/漂移/卡死等）  |

**协同联动示例**（温度超 80°C → 启动风扇 → 注入传感器噪声）：

```json
{
  "rule_type": "collaboration",
  "source_device_id": "temp-sensor",
  "source_point": "temperature",
  "condition": {"operator": ">", "value": 80},
  "actions": [
    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100},
    {"target_device_id": "temp-sensor", "target_point": "temperature", "action_type": "inject_fault", "value": {"fault_type": "sensor_noise", "parameters": {"noise_std": 2.0, "duration": 60}}}
  ],
  "cooldown": 5.0
}
```

**时间序列回放**：场景支持 `replay_config`，从历史数据（内联 JSON / CSV 文件）驱动仿真，支持加速回放（`speed`）和循环（`loop`）：

```json
{
  "replay_config": {
    "source": [{"ts": 0, "device_id": "sensor", "point": "temp", "value": 25.0}],
    "speed": 2.0,
    "loop": true
  }
}
```

**冷却机制**：协同规则在 Rule 级设置 `cooldown`（秒），防止规则频繁触发：

```json
{"cooldown": 30}
```

***

## 🛠 CLI 命令

| 命令                   | 说明                                                     |
| -------------------- | ------------------------------------------------------ |
| `protoforge run`     | 启动服务（`--host` / `--port` / `--reload` / `--log-level` / `--daemon`） |
| `protoforge demo`    | 演示模式（自动创建示例设备和场景，`--daemon` / `-d` 后台运行）                 |
| `protoforge stop`    | 停止后台运行的服务（仅 Linux / macOS）                              |
| `protoforge init`    | 初始化数据目录和默认配置（创建 `data/` 目录，从 `.env.example` 复制 `.env`） |
| `protoforge migrate` | 运行数据库迁移（`--revision head`）                             |
| `protoforge test run` | 执行测试计划（CI/CD 集成，支持 `--plan-id` 指定计划）                    |
| `protoforge version` | 查看版本号                                                  |

***

## 📊 性能基准参考

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

## 🔄 升级指南

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

## 🖥 前端开发

```bash
cd web
npm install
npm run dev     # 开发服务器（热更新）
npm run build   # 生产构建 → web/dist/
```

***

## 🧪 测试

```bash
# 运行全部单元测试
python -m pytest tests/ -v

# 运行测试并生成覆盖率报告
python -m pytest tests/ -v --cov=protoforge --cov-report=html
```

***

## 📐 项目结构

```
ProtoForge/
├── protoforge/                # Python 后端包
│   ├── api/v1/               # REST API 端点
│   │   ├── common.py         # 统一响应格式和异常处理
│   │   ├── rate_limit.py     # API 限流中间件
│   │   ├── router.py         # API 路由
│   │   ├── test_plan_routes.py # 测试计划 API
│   │   └── compliance_routes.py # 合规检测 API
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
│   ├── protocols/            # 26 种协议服务端实现
│   ├── testing/              # IoT 测试平台（计划/执行/合规检测）
│   ├── sdk/                  # Python SDK（同步/异步）
│   └── templates/            # 131 设备模板（JSON）
├── sdk/                       # 多语言 SDK
│   ├── java/                 # Java SDK
│   ├── go/                   # Go SDK
│   └── csharp/               # C# SDK
├── web/                       # Vue3 前端
│   ├── e2e/                  # Playwright E2E 浏试（31 项全通过）
│   └── src/
│       ├── views/            # 页面组件（含 TestPlans/Compliance）
│       ├── App.vue           # 主布局（含i18n）
│       ├── i18n.js           # 国际化框架（中英文）
│       ├── api.js            # API 调用
│       └── main.js           # 入口
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

## 📡 API 文档

后端启动后，访问以下地址查看交互式 API 文档（直接访问后端端口）：

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

> 这是后端 API 文档，不是前端页面。前端页面请访问 `http://localhost:8000`（与后端同端口）。

***

## 📦 Python SDK

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

## 📊 监控端点

| 端点                           | 格式         | 说明                         |
| ---------------------------- | ---------- | -------------------------- |
| `GET /health`                | JSON       | 健康检查（数据库状态、活跃设备数、协议状态）     |
| `GET /metrics`               | Prometheus | 标准指标格式（uptime、设备数、转发/录制计数） |
| `GET /api/v1/forward/stats`  | JSON       | 数据转发统计                     |
| `GET /api/v1/recorder/stats` | JSON       | 录制统计                       |

***

## 🔒 安全说明

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

## 💾 数据库备份与恢复

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

## 🔌 gRPC 远程管理

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

## ☸️ Kubernetes / Helm 部署

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

## 🔄 故障切换

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

## 📊 竞品对比

### ProtoForge vs 同类工具

| 特性 | ProtoForge | Modbus Slave/Poll | Kepware | Node-RED Mock | 真实 PLC |
| ---- | ---------- | ----------------- | ------- | ------------- | -------- |
| **协议数量** | 26 种 | 仅 Modbus | 150+ (需付费驱动) | 仅 MQTT/HTTP | 单一品牌 |
| **开源免费** | ✅ MIT | ❌ 付费 | ❌ 商业 | ✅ 但需自建 | ❌ |
| **多协议同时仿真** | ✅ 26 种同时 | ❌ | ✅ (需购买驱动) | ❌ | ❌ |
| **Web 管理界面** | ✅ 开箱即用 | ❌ 桌面软件 | ✅ | ❌ | 品牌专用 |
| **设备模板库** | ✅ 122+ 模板 | ❌ 手动配置 | ✅ | ❌ | — |
| **批量设备生成** | ✅ 一键 100 台 | ❌ | ✅ (付费) | ❌ | ❌ |
| **数据生成器** | ✅ 5 种 (随机/正弦/递增/渐变/固定) | ❌ 手动改值 | ❌ | ✅ 简单 | ✅ 真实数据 |
| **异常码模拟** | ✅ 设备状态映射异常码 | ❌ | ❌ | ❌ | ✅ |
| **写入支持** | ✅ 完整读写 | ✅ | ✅ | ❌ | ✅ |
| **Docker 部署** | ✅ 30 秒启动 | ❌ | ❌ | ✅ | ❌ |
| **ARM/树莓派** | ✅ 支持 | ❌ | ❌ | ✅ | — |
| **中文支持** | ✅ 双语 | ❌ | ❌ | ❌ | — |
| **成本** | **免费** | $69+ | $1,500+/驱动 | 免费 | $500+ |

> 💡 **ProtoForge 的独特价值**：一台电脑同时仿真 26 种协议设备，零硬件成本。不是替代真实 PLC，而是让你在**没有硬件**时也能开发、测试、联调。

### 协议一致性说明

ProtoForge 严格遵循工业协议标准，确保你的采集程序对接真实设备时无缝切换：

| 协议 | 遵循标准 | 异常码/错误处理 |
| ---- | -------- | -------------- |
| **Modbus TCP/RTU** | Modbus Application Protocol v1.1b3 | 完整异常码：0x01 非法功能、0x02 非法地址、0x03 非法数据值、0x04 从站故障、0x05 确认、0x06 从站忙、0x0A 网关不可达 |
| **Siemens S7** | S7 Communication (ISO-on-TCP, RFC1006) | SZL 请求响应、错误帧完整支持 |
| **Omron FINS** | FINS/TCP (CV-mode 命令) | EndCode 错误码完整返回 |
| **Mitsubishi MC** | SLMP 3E/4E 帧格式 | 子头 0x5000，大端序读写 |
| **OPC-UA** | OPC 1.05 Part 6: Mappings | NodeId/QualifiedName/DataValue 完整 |
| **IEC 60870-5-104** | IEC 60870-5-104 (TI/CI/CD 等 ASDU) | APDU/APCI 帧、IOA 地址完整 |
| **MQTT** | MQTT 3.1.1 / 5.0 | QoS 0/1/2、Retain、Last Will |
| **BACnet** | BACnet/IP (ASHRAE 135) | ReadProperty/WriteProperty 服务 |

> 💡 **设备状态→异常码映射**：ProtoForge 仿真设备的运行状态（stop/error/starting/stopping/maintenance/program）会自动映射为对应协议的异常码，就像真实设备在故障时会返回错误一样。例如 Modbus 设备处于 `error` 状态时返回异常码 `0x04` (Slave Device Failure)。

***

## 🍓 ARM / 树莓派部署

ProtoForge 支持 ARM64 架构，可以在树莓派、工业网关等低功耗设备上运行：

### Docker 部署（推荐）

```bash
# 树莓派 / ARM64 设备
docker run -d --name protoforge \
  -p 8000:8000 \
  -e PROTOFORGE_ADMIN_PASSWORD=admin \
  -v protoforge-data:/app/data \
  suoten/protoforge:latest
```

> Docker 镜像自动识别 CPU 架构（amd64 / arm64），无需指定平台。

### Python 源码部署

```bash
# 安装 Python 3.10+
sudo apt install python3.10 python3.10-venv

# 克隆并安装
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e .

# 启动
protoforge run --host 0.0.0.0 --port 8000
```

### 资源消耗参考

| 配置项 | 最低要求 | 推荐 | 测试基准 |
| ------ | -------- | ---- | -------- |
| **CPU** | ARM Cortex-A53 (1.2GHz) | ARM Cortex-A72 (1.5GHz+) | 树莓派 4B (4GB) |
| **内存** | 256MB (10 台设备) | 512MB (50 台设备) | 1GB (100+ 台设备) |
| **磁盘** | 100MB (应用) | 1GB (含数据) | — |
| **并发设备** | 10 台 | 50 台 | 100+ 台 |
| **协议端口** | 5 个同时 | 10 个同时 | 全部 26 种 |

> 💡 **树莓派实测**：在树莓派 4B (4GB) 上运行 50 台设备（Modbus + S7 + MQTT 同时），CPU 占用约 15%，内存约 180MB，完全流畅。

> ⚠️ **ARM 限制**：部分协议驱动（如 OPC-DA、FANUC FOCAS）依赖 Windows 原生 DLL，在 ARM 上不可用。核心协议（Modbus、S7、OPC-UA、MQTT、FINS、MC、IEC 104、BACnet、CoAP、DDS）均完整支持 ARM64。

***

## 📋 开源版 vs 企业版功能对比

| 功能 | 开源版 (MIT) | 企业版 |
| ---- | ----------- | ------ |
| **协议数量** | 26 种全支持 | 26 种 + 定制协议 |
| **设备模板** | 122+ 模板 | 122+ + 行业定制模板 |
| **同时仿真设备数** | 无限制 | 无限制 |
| **Web 管理界面** | ✅ 完整功能 | ✅ + 品牌定制 |
| **API 接口** | ✅ 完整 REST API | ✅ + gRPC 批量接口 |
| **Python SDK** | ✅ 同步+异步 | ✅ + Java/Go SDK |
| **Docker 部署** | ✅ | ✅ + Helm/K8s Operator |
| **ARM 支持** | ✅ | ✅ |
| **CSV 导入导出** | ✅ | ✅ |
| **测试计划** | ✅ | ✅ + CI/CD 插件 |
| **合规检查** | ✅ | ✅ + 行业标准包 |
| **SSO / LDAP** | ❌ | ✅ |
| **多租户** | ❌ | ✅ |
| **审计日志** | ❌ | ✅ |
| **SLA 支持** | ❌ | ✅ 7×24 |
| **专业服务** | 社区支持 | 专属技术经理 |

> 💡 **开源版永久免费**：ProtoForge 开源版包含全部核心功能，没有任何功能限制、设备数量限制或协议限制。企业版提供组织级管理能力和专业服务支持。

***

## ❓ 常见问题排查

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

A: 你可能访问了 `http://localhost:8000/docs`。直接访问 `http://localhost:8000`（不带 `/docs`）就是前端 Web 界面。前端和后端都在 8000 端口上，由 FastAPI 统一托管，不需要 Nginx。

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
- 确认访问的是 `http://localhost:8000`（前端和后端都在此端口，由 FastAPI 统一托管）。

**Docker 部署：**

- 检查容器日志：`docker logs protoforge`，看是否有 "前端静态文件目录不存在" 的警告。如果有，说明 Docker 镜像构建时前端编译失败了。
- 确认访问的是 `http://localhost:8000`（不带 `/docs`）。

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

A: 删除 `data/protoforge.db` 文件（SQLite 模式）然后重启，系统会重新创建 admin 账号并生成新的随机密码（显示在终端日志中）。你也可以设置 `PROTOFORGE_ADMIN_PASSWORD` 环境变量来指定新密码。

> ⚠️ 这会清空所有数据！如果数据重要，请先备份 `data/` 目录。

**Q: 怎么备份数据？**

A: 登录后进入「系统设置」页面，点击「导出备份」按钮即可下载 JSON 文件。也可以直接用命令：

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/v1/backup -o backup.json
```

Token 可以在浏览器开发者工具（F12）→ Application → Local Storage → token 中找到。

***

## 🔗 相关项目

| 项目                                                           | 说明                        | 仓库地址                                                                                                    |
| ------------------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------- |
| [EdgeLiteGateway](https://github.com/suoten/EdgeLiteGateway) | 轻量级边缘计算物联网网关，22 种工业协议开箱即用 | [Gitee](https://gitee.com/suoten/EdgeLiteGateway) · [GitHub](https://github.com/suoten/EdgeLiteGateway) |

***

## 💬 社区交流

[![QQ群](https://img.shields.io/badge/QQ%E7%BE%A4-866599071-eb1923?logo=tencentqq&logoColor=white)](https://qm.qq.com/cgi-bin/qm/qr?k=8jGiq7UgneoOCuc5SV-FOFsb49mlmEhK&jump_from=webapi&authKey=efY0P+0PSa3KjkWLsg4Kt1M7+pQZPv7iBiwRkn6e5u8MbzK8cklSKSwvY3WGrnFa) **进群答案：ProtoForge**

***

## 🏢 企业服务 & 专业支持

> ProtoForge 开源版永久免费。如果你的团队需要更深层次的支持，我们提供以下专业服务：

| 服务 | 说明 | 适用场景 |
|------|------|--------|
| 🔧 **协议联调服务** | 专家协助完成特定协议的联调测试，快速定位报文/地址/编码问题 | 项目上线前联调 |
| 🎨 **协议定制开发** | 定制非标协议、特殊报文格式、私有协议扩展 | 标准协议不满足需求 |
| 🚀 **私有化部署** | ProtoForge + EdgeLite 私有化部署、集成、培训 | 企业内网环境 |
| 📊 **企业版 License** | SSO/LDAP、多租户、审计日志、SLA 支持 | 生产级使用 |
| 🎓 **技术培训** | 工业协议体系化培训 + ProtoForge 实操 | 团队技能提升 |

> 💬 联系方式：[QQ群](https://qm.qq.com/cgi-bin/qm/qr?k=8jGiq7UgneoOCuc5SV-FOFsb49mlmEhK)（群主）或邮箱 `suoten@163.com`

---

## ☕ 赞助作者

> ProtoForge 是一个开源项目，如果你觉得它对你有帮助，可以考虑请作者喝杯咖啡 ☕
> 你的支持是项目持续维护的动力！

<table align="center">
  <tr>
    <td align="center">
      <img src="docs/images/weixin.jpg" width="200" />
      <br /><b>微信赞赏</b>
    </td>
    <td align="center">
      <img src="docs/images/zfb.jpg" width="200" />
      <br /><b>支付宝赞赏</b>
    </td>
  </tr>
</table>

> 💝 感谢每一位支持者！如果在企业项目中使用了 ProtoForge，欢迎反馈使用场景，也欢迎在 [GitHub Issues](https://github.com/suoten/ProtoForge/issues) 留言。

