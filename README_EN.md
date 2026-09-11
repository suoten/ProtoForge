# ProtoForge

**IoT Protocol Simulation & Testing Platform**

[![Python](https://flat.badgen.net/badge/Python/3.10+/blue)](https://python.org) [![FastAPI](https://flat.badgen.net/badge/FastAPI/0.115+/green)](https://fastapi.tiangolo.com) [![Vue3](https://flat.badgen.net/badge/Vue/3.x/brightgreen)](https://vuejs.org) [![Naive UI](https://flat.badgen.net/badge/Naive_UI/2.x/5f25d4)](https://naiveui.com) [![License](https://flat.badgen.net/badge/License/MIT/yellow)](LICENSE) [![QQ Group](https://flat.badgen.net/badge/QQ%20Group/866599071/eb1923)](https://qm.qq.com/q/ProtoForge)

**Join Code: ProtoForge**

[中文](README.md) | [English](README_EN.md)

> ✅ **Windows** &nbsp; ✅ **Linux** &nbsp; ✅ **macOS**

---

## What is ProtoForge?

ProtoForge is an open-source IoT protocol simulation and testing platform. No hardware required — simulate PLCs, sensors, cameras, and other industrial devices right on your computer to test whether your SCADA, gateway, or data acquisition systems communicate correctly.

**Simply put: Install it, click a few buttons, and get real-time simulated device data.**

## 🔥 Real Developer Pain Points

| # | Pain Point | How Bad Is It | ProtoForge Solution |
|---|-----------|---------------|---------------------|
| 1 | **Protocol bytes don't match, can't find the bug** | Client says "no data", you stare at hex dump for 3 days | WebSocket real-time debug logs, filter by protocol/direction/keyword, click to inspect frame details |
| 2 | **Simulator too well-behaved, breaks in production** | Test env always returns perfect values, real PLC disconnects/timeouts/returns error codes | 9 fault injection types: sensor stuck/drift/noise/failure, intermittent disconnect/delay/packet loss, device failure/actuator stuck |
| 3 | **Testing is all manual, regression takes all afternoon** | Every code change: create device→start→read→verify manually | Automated test engine: 13 assertion types, variable extraction, test suites, HTML reports + trend analysis |
| 4 | **Can't reproduce customer site issues** | Client says "data was wrong at 3pm yesterday", no recording, can only guess | Protocol recording & replay: record→replay→verify fix, with Gzip compression |
| 5 | **New hires don't understand protocols, takes a week** | Address offset, function codes, byte order all confused | 4-language code examples (Python/C#/Java/Go) per protocol, 122 ready-to-use templates |
| 6 | **Multi-protocol testing, takes a week to set up** | Testing Modbus+S7+MQTT simultaneously, find 3 different vendor devices | 21 protocols on one computer, Docker 30-second startup, generate 100 virtual devices with one click |
| 7 | **Protocol security can't be tested** | OPC-UA certs/TLS/GB28181 SRTP, can't touch production, no test env | Auto certificate generation, TLS encryption, SRTP support, test security freely |

## ✨ Features

- **21 Industrial Protocols** — Modbus TCP/RTU, OPC-UA, MQTT, HTTP, GB28181, BACnet, Siemens S7, Mitsubishi MC, Omron FINS, Rockwell AB, OPC-DA, FANUC FOCAS, MTConnect, Mettler-Toledo, PROFINET IO, EtherCAT, IEC 60870-5-104, IEC 61850, CoAP, DDS
- **Full-chain Simulation** — Complete protocol interactions including GB28181 SIP registration, RTP video streaming, and more
- **122 Device Templates** — PLC, sensor, CNC, camera, HVAC, servo drive, protection relay, IED, env sensor, microgrid — pick a template, name it, create with one click
- **Real-time Debug Logs** — WebSocket real-time protocol messages, filterable by protocol/direction/keyword
- **Visual Scenario Editor** — Visual device orchestration with threshold/change/timer/script rule types
- **One-click Testing** — Auto-generated test cases with smart diagnostics
- **Data Forwarding** — InfluxDB / HTTP Webhook / File export
- **Protocol Recording & Playback** — Record communication messages and replay for verification
- **Prometheus Metrics** — Built-in monitoring endpoint, Grafana-ready
- **JWT Auth + RBAC** — 4 roles (admin/operator/user/viewer), bcrypt password storage
- **Rate Limiting** — Built-in protection against brute force and abuse
- **Dual Database** — SQLite out of the box, PostgreSQL for production
- **EdgeLite Integration** — Auto-register devices with EdgeLite gateway
- **Multi-language SDK** — Python (sync/async), Java, Go, C#
- **gRPC Remote Management** — 15 RPC methods, cross-language support
- **Database Backup & Restore** — One-click JSON export/import
- **K8s/Helm Deployment** — Full Kubernetes deployment + Helm Chart
- **High Availability** — Primary/standby health checks, auto-promotion
- **i18n** — Chinese/English bilingual, one-click switch
- **Multi-arch Docker** — amd64/arm64 images pushed to Docker Hub

---

## 📥 Installation

### Prerequisites

| Required | Docker Path | Script Path | Manual Path |
| -------- | :---: | :---: | :---: |
| Docker Desktop | ✅ Required | ❌ | ❌ |
| Python 3.10+ | ❌ | ✅ Required | ✅ Required |
| Node.js 18+ | ❌ | Optional¹ | ✅ Required |
| Git | ❌ | ✅ Required² | ✅ Required |

> ¹ No Node.js? Script uses pre-built frontend included in the repo  
> ² Download ZIP or git clone from GitHub

**Download Links**:

| Software | Link | Notes |
| -------- | ---- | ----- |
| **Docker Desktop** | [docker.com](https://www.docker.com/products/docker-desktop/) | Windows requires WSL2 |
| **Python** | [python.org](https://www.python.org/downloads/) | Check "Add Python to PATH" on Windows |
| **Node.js** | [nodejs.org](https://nodejs.org/) | Download LTS (green button) |
| **Git** | [git-scm.com](https://git-scm.com/downloads) | Default options are fine |

---

### Method 1: Docker (Recommended)

✅ **Windows** &nbsp; ✅ **Linux** &nbsp; ✅ **macOS**

The simplest method. No Python, Node.js, or Git required. Opens with demo data ready.

**Step 1: Install Docker Desktop**

Download from the table above. Verify installation:

```bash
docker --version    # Should show 20.x or higher
```

**Step 2: Run this single command in terminal**

```bash
docker run -d --name protoforge -p 8000:8000 -v protoforge-data:/app/data suoten/protoforge:latest
```

> 🔹 **What's a terminal?** On Windows: PowerShell (search "powershell" in Start menu). On macOS: Terminal app.
>
> 🔹 Prefer GUI? Open Docker Desktop → Images → search `suoten/protoforge` → Pull → Run.

**Step 3: Open your browser**

Visit **http://localhost:8000**, log in with `admin` / `admin`.

You'll see pre-configured demo devices, protocols, and test scenarios ready to use.

Stop the service:

```bash
docker stop protoforge && docker rm protoforge
```

> 💡 Uses built-in SQLite. Data persists in a Docker volume. For advanced usage see [docker-compose.simple.yml](docker-compose.simple.yml).

---

### Method 2: One-Click Script

✅ **Windows** &nbsp; ✅ **Linux** &nbsp; ✅ **macOS**

**Step 1: Download the project**

Open [https://github.com/suoten/ProtoForge](https://github.com/suoten/ProtoForge), click the green **"Code"** button → **"Download ZIP"** → extract the ZIP (folder usually named `ProtoForge-main`).

**Step 2: Run the install script**

- **Windows**: Double-click `install.bat` in the extracted folder
- **Linux / macOS**: Open terminal in the extracted folder, run:
  ```bash
  chmod +x install.sh
  ./install.sh
  ```

**Step 3: Start the service**

```bash
# Windows (Shift+Right-click in folder → Open PowerShell here):
.\venv\Scripts\python.exe -m protoforge.cli demo

# Linux / macOS:
source venv/bin/activate
protoforge demo
```

Open **http://localhost:8000**, log in with `admin` / `admin`.

> 💡 Slow network? Set a mirror first:
> ```bash
> pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
> npm config set registry https://registry.npmmirror.com
> ```

---

### Method 3: Manual (Developers)

Full details in [DEPLOYMENT.md](DEPLOYMENT.md).

<details>
<summary><b>Windows — Click to expand</b></summary>

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[all]"
cd web && npm install && npm run build && cd ..
protoforge demo
# Open http://localhost:8000, login admin / admin
```

> ⚠️ If `.\venv\Scripts\activate` shows "running scripts is disabled", open PowerShell as admin and run:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

</details>

<details>
<summary><b>Linux / macOS — Click to expand</b></summary>

```bash
git clone https://github.com/suoten/ProtoForge.git
cd ProtoForge
python3 -m venv venv
source venv/bin/activate
pip install -e ".[all]"
cd web && npm install && npm run build && cd ..
protoforge demo
# Open http://localhost:8000, login admin / admin
```

</details>

> 💡 **Source deployment users**: `.env.example` is pre-configured with working defaults. Copy to `.env` _(already done by install scripts)_. For production, change `PROTOFORGE_JWT_SECRET` and `PROTOFORGE_ADMIN_PASSWORD`.

---

## 🚀 5-Minute Quick Start

> **Prerequisite**: Deployment completed, browser opens http://localhost:8000.

1. **Login** — Enter `admin` / `admin`
2. **Start Protocols** — Left menu "Protocol Services" → Click "Start All"
3. **Create Device** — Left menu "Template Market" → Pick a template → Enter name → Create
4. **View Data** — Device list → Click "Points" → See real-time simulated data
5. **Run Tests** — Left menu "Simulation Test" → Click "Test All"

> ⚠️ **Blank page?** Docker: check `docker logs protoforge`. Source: run `cd web && npm install && npm run build`, then restart.

---

## 📦 Optional: Install More Protocols

Core protocols (Modbus TCP/RTU, HTTP, GB28181, MC, FINS, AB, OPC-DA, FANUC, MTConnect, Toledo, PROFINET, EtherCAT, IEC 104, IEC 61850, CoAP, DDS — 17 total) work out of the box. These 4 require extra deps:

```bash
pip install -e ".[all]"        # All 21 protocols
pip install -e ".[opcua]"     # OPC-UA
pip install -e ".[mqtt]"      # MQTT
pip install -e ".[bacnet]"    # BACnet
pip install -e ".[s7]"        # Siemens S7
```

| Protocol | Extra Install? | Default Port | Description |
| -------- | :---: | ------------ | ----------- |
| Modbus TCP | No | 5020 | Industrial standard |
| HTTP | No | 8080 | RESTful API simulation |
| Modbus RTU | No | Serial | Serial comm |
| GB28181 | No | 5060 | Video surveillance |
| Mitsubishi MC | No | 5000 | SLMP protocol |
| Omron FINS | No | 9600 | PLC FINS |
| Rockwell AB | No | 44818 | EtherNet/IP |
| OPC-DA | No | 51340 | Classic OPC |
| FANUC FOCAS | No | 8193 | CNC data |
| MTConnect | No | 7878 | Machine tool data |
| Mettler-Toledo | No | 1701 | Weighing |
| PROFINET IO | No | 34964 | Real-time Ethernet |
| EtherCAT | No | 34980 | Real-time Ethernet |
| OPC-UA | `[opcua]` | 4840 | Unified Architecture |
| MQTT | `[mqtt]` | 1883 | IoT messaging |
| BACnet | `[bacnet]` | 47808 | Building automation |
| Siemens S7 | `[s7]` | 102 | Siemens PLC |
| IEC 60870-5-104 | No | 2404 | Power telecontrol (SCADA) |
| IEC 61850 | No | 102 | Substation automation (MMS) |
| CoAP | No | 5683 | Constrained IoT protocol (UDP) |
| DDS | No | 7400 | Data Distribution Service |

---

## 🤝 Support

**QQ Group: 866599071** — Join code: **ProtoForge**

---

## 🏢 Enterprise Service & Professional Support

> ProtoForge open-source is free forever. If your team needs deeper support, we offer:

| Service | Description | Use Case |
|---------|-------------|----------|
| 🔧 **Protocol Debug Service** | Expert assistance for protocol integration testing | Pre-launch testing |
| 🎨 **Custom Protocol Development** | Custom non-standard protocols, private extensions | When standard protocols aren't enough |
| 🚀 **Private Deployment** | ProtoForge + EdgeLite private deployment & training | Enterprise intranet |
| 📊 **Enterprise License** | SSO/LDAP, multi-tenant, audit log, SLA support | Production-grade use |
| 🎓 **Technical Training** | Industrial protocol training + ProtoForge hands-on | Team skill building |

> 💬 Contact: [QQ Group](https://qm.qq.com/q/ProtoForge) (Group Owner) or email `suoten@jjtt.net`

---

## 📄 License

MIT