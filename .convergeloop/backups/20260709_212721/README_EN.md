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

## ✨ Features

- **17 Industrial Protocols** — Modbus TCP/RTU, OPC-UA, MQTT, HTTP, GB28181, BACnet, Siemens S7, Mitsubishi MC, Omron FINS, Rockwell AB, OPC-DA, FANUC FOCAS, MTConnect, Mettler-Toledo, PROFINET IO, EtherCAT
- **Full-chain Simulation** — Complete protocol interactions including GB28181 SIP registration, RTP video streaming, and more
- **90+ Device Templates** — PLC, sensor, CNC, camera, HVAC, servo drive — pick a template, name it, create with one click
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

Core protocols (Modbus TCP/RTU, HTTP, GB28181, MC, FINS, AB, OPC-DA, FANUC, MTConnect, Toledo, PROFINET, EtherCAT — 13 total) work out of the box. These 4 require extra deps:

```bash
pip install -e ".[all]"        # All 17 protocols
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

---

## 🤝 Support

**QQ Group: 866599071** — Join code: **ProtoForge**

---

## 📄 License

MIT