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
| 5 | **New hires don't understand protocols, takes a week** | Address offset, function codes, byte order all confused | 4-language code examples (Python/C#/Java/Go) per protocol, 131 ready-to-use templates |
| 6 | **Multi-protocol testing, takes a week to set up** | Testing Modbus+S7+MQTT simultaneously, find 3 different vendor devices | 26 protocols on one computer, Docker 30-second startup, generate 100 virtual devices with one click |
| 7 | **Protocol security can't be tested** | OPC-UA certs/TLS/GB28181 SRTP, can't touch production, no test env | Auto certificate generation, TLS encryption, SRTP support, test security freely |

## ✨ Features

- **26 Industrial Protocols** — Modbus TCP/RTU, OPC-UA, MQTT, HTTP, GB28181, BACnet, Siemens S7/S7Comm-Plus, Mitsubishi MC, Omron FINS, Rockwell AB, OPC-DA, FANUC FOCAS, MTConnect, Mettler-Toledo, PROFINET IO, EtherCAT, IEC 60870-5-104, IEC 61850, CoAP, DDS, DLT/T 645, CJ/T 188, Custom TCP/UDP
- **Full-chain Simulation** — Complete protocol interactions including GB28181 SIP registration, RTP video streaming, and more
- **131 Device Templates** — PLC, sensor, CNC, camera, HVAC, servo drive, protection relay, IED, env sensor, microgrid, smart meter, water/gas/heat meter — pick a template, name it, create with one click
- **Real-time Debug Logs** — WebSocket real-time protocol messages, filterable by protocol/direction/keyword
- **Visual Scenario Editor** — Visual device orchestration with threshold/change/timer/script rule types
- **One-click Testing** — Auto-generated test cases with smart diagnostics
- **Test Plans** — Versioned test plan management with CRUD, clone, execution history, JUnit/JSON/HTML reports, CI/CD integration (`protoforge test run`)
- **Compliance Checking** — Protocol compliance verification for Modbus TCP, S7, OPC-UA, IEC 104, MQTT with rule-based scoring and violation reports
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
# Open http://localhost:8000, login admin / admin (demo-mode default; existing data is synced automatically)
# Override with PROTOFORGE_ADMIN_PASSWORD; non-demo mode (protoforge run) generates a random password, see the startup banner
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
# Open http://localhost:8000, login admin / admin (demo-mode default; existing data is synced automatically)
# Override with PROTOFORGE_ADMIN_PASSWORD; non-demo mode (protoforge run) generates a random password, see the startup banner
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
pip install -e ".[all]"        # All 26 protocols
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

## 📍 PLC Address Mapping — Per-Point Precision

Every point in ProtoForge is bound to a **specific PLC protocol address**. Your SCADA/gateway reads from this address exactly like reading a real PLC.

### Address Formats by Protocol

| Protocol | Address Format | Example | Description |
| -------- | -------------- | ------- | ----------- |
| **Modbus TCP/RTU** | Register offset (number) | `address: "0"` | Register 40001 (holding), `"2"` = 40003 |
| **Siemens S7** | DB.type+offset | `address: "DB1.DBD2"` | DB1, D=double word, offset 2; `DBX`=bit, `DBW`=word |
| **Omron FINS** | Area+address | `address: "DM100"` | DM area address 100; `CIO0` = CIO area |
| **Mitsubishi MC** | Device+address | `address: "D100"` | D register 100; `M0` = internal relay 0 |
| **OPC-UA** | Node ID | `address: "ns=2;s=Temperature"` | Namespace 2, node Temperature |
| **IEC 60870-5-104** | ASDU address | `address: "1"` | IOA (Information Object Address) = 1 |

### Modbus Register Types & Function Code Mapping

ProtoForge supports all four Modbus register areas, auto-detected by address format:

| Register Area | Address Format | Modbus Range | Function Codes | Description |
| ------------- | -------------- | ------------ | -------------- | ----------- |
| **Coil** | `0`, `00001`, `0x0`, `C0` | 00001–09999 | FC01 Read / FC05 Write / FC0F Write Multi | Bit, read/write |
| **Discrete Input** | `10001`, `1x0`, `DI0` | 10001–19999 | FC02 Read | Bit, read-only |
| **Input Register** | `30001`, `3x0`, `IR0` | 30001–39999 | FC04 Read | Word, read-only |
| **Holding Register** | `0`, `40001`, `4x0`, `HR0` | 40001–49999 | FC03 Read / FC06 Write / FC10 Write Multi | Word, read/write |

> 💡 **Auto-detection for plain numbers**: `bool` type → Coil; other types → Holding Register. Use `30001`, `10001` or `IR0`, `DI0` prefixes for Input Register / Discrete Input.

### Data Types & Register Usage

| Data Type | Bytes | Registers | Byte Order | Protocols |
| --------- | ----- | --------- | ---------- | --------- |
| `bool` | 1 bit | 1 (bit) | — | Modbus, S7 (DBX), FINS |
| `int16` | 2 | 1 | Big-Endian | Modbus, S7 (DBW), FINS, MC |
| `uint16` | 2 | 1 | Big-Endian | Modbus, S7, MC |
| `int32` | 4 | 2 | Big-Endian | Modbus, S7 (DBD), MC |
| `uint32` | 4 | 2 | Big-Endian | Modbus, S7, MC |
| `float32` | 4 | 2 | Big-Endian (IEEE 754) | Modbus, S7 (DBD Real), FINS, MC |
| `float64` | 8 | 4 | Big-Endian (IEEE 754) | Modbus, S7 |
| `string` | Variable | Variable | Big-Endian (UTF-8) | Modbus, S7 |
| `real` | 4 | 2 | Big-Endian | S7 (same as float32) |

> ⚠️ **Byte Order**: ProtoForge uses **Big-Endian** for all protocols — the most common byte order in industrial devices. If your client uses Little-Endian, you'll need to swap bytes on the client side.

### Data Generators

| Generator | Description | Key Parameters | Use Case |
| --------- | ----------- | -------------- | -------- |
| `fixed` | Fixed value | `fixed_value` | Status, switches |
| `random` | Random value | `min_value`, `max_value` | Sensor noise |
| `sine` | Sine wave | `min_value`, `max_value`, `period` | Periodic changes |
| `increment` | Incrementing | `min_value`, `max_value`, `step` | Flow meters, counters |
| `ramp` | Linear ramp | `start_value`, `end_value`, `duration` | Gradual changes |

> 💡 `update_frequency` (seconds per update, default `1.0`) controls how often data changes — similar to a real device's sampling period.

### Write Behavior

Writes to ProtoForge behave exactly like writing to a real PLC:

| Operation | ProtoForge Response | Subsequent Read |
| --------- | ------------------- | --------------- |
| Write Single Coil (FC05) | Normal echo response | Returns written value |
| Write Multiple Coils (FC0F) | Normal echo response | Returns written values |
| Write Single Register (FC06) | Normal echo response | Returns written value |
| Write Multiple Registers (FC10) | Normal echo response | Returns written values |
| Read/Write Multiple (FC17) | Returns read values | Write takes effect immediately |
| Mask Write Register (FC16) | Normal response | Updated per AND/OR mask logic |

> ⚠️ If `generator_type` is set (e.g., `random`, `sine`), the generator will overwrite written values each cycle. Set `generator_type` to `fixed` to retain written values.

### Multi-Device Coexistence

Multiple devices can share the **same protocol port** — like multiple slaves on an RS-485 bus:

```
Device A: slave_id=1, protocol=modbus_tcp, port=5020
Device B: slave_id=2, protocol=modbus_tcp, port=5020  ← same port, different slave_id
Device C: slave_id=3, protocol=modbus_tcp, port=5020
```

Your acquisition program differentiates devices by `slave_id` — identical to real multi-device bus topology.

### Modbus RTU Serial Configuration

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

| Parameter | Options | Default |
| --------- | ------- | ------- |
| `baudrate` | 1200–115200 | 9600 |
| `databits` | 7, 8 | 8 |
| `parity` | none, even, odd | even |
| `stopbits` | 1, 1.5, 2 | 1 |

---

## 📊 Competitor Comparison

| Feature | ProtoForge | Modbus Slave/Poll | Kepware | Node-RED Mock | Real PLC |
| ------- | ---------- | ----------------- | ------- | ------------- | -------- |
| **Protocols** | 26 | Modbus only | 150+ (paid drivers) | MQTT/HTTP only | Single brand |
| **Open Source** | ✅ MIT | ❌ Paid | ❌ Commercial | ✅ DIY | ❌ |
| **Multi-protocol simultaneous** | ✅ 26 at once | ❌ | ✅ (paid) | ❌ | ❌ |
| **Web UI** | ✅ Out of box | ❌ Desktop | ✅ | ❌ | Brand-specific |
| **Device Templates** | ✅ 122+ | ❌ Manual | ✅ | ❌ | — |
| **Batch Device Generation** | ✅ 100 with one click | ❌ | ✅ (paid) | ❌ | ❌ |
| **Data Generators** | ✅ 5 types | ❌ Manual | ❌ | ✅ Basic | ✅ Real data |
| **Exception Code Simulation** | ✅ State-mapped | ❌ | ❌ | ❌ | ✅ |
| **Write Support** | ✅ Full read/write | ✅ | ✅ | ❌ | ✅ |
| **Docker** | ✅ 30s start | ❌ | ❌ | ✅ | ❌ |
| **ARM/Raspberry Pi** | ✅ | ❌ | ❌ | ✅ | — |
| **Cost** | **Free** | $69+ | $1,500+/driver | Free | $500+ |

### Protocol Compliance

ProtoForge strictly follows industrial protocol standards:

| Protocol | Standard | Error Handling |
| -------- | -------- | -------------- |
| Modbus TCP/RTU | Modbus App Protocol v1.1b3 | Full exception codes (0x01–0x0A) |
| Siemens S7 | S7 Comm (ISO-on-TCP, RFC1006) | SZL response, error frames |
| Omron FINS | FINS/TCP (CV-mode) | EndCode error codes |
| Mitsubishi MC | SLMP 3E/4E frame | Subheader 0x5000, big-endian |
| OPC-UA | OPC 1.05 Part 6 | Full NodeId/DataValue |
| IEC 60870-5-104 | IEC 60870-5-104 | APDU/APCI frames, full IOA |
| MQTT | 3.1.1 / 5.0 | QoS 0/1/2, Retain, LWT |
| BACnet | BACnet/IP (ASHRAE 135) | ReadProperty/WriteProperty |

> 💡 **Device state → exception code mapping**: Device states (stop/error/starting/stopping/maintenance/program) automatically map to protocol-specific exception codes — just like real devices returning errors on fault.

---

## 🍓 ARM / Raspberry Pi Deployment

ProtoForge supports ARM64 architecture — runs on Raspberry Pi, industrial gateways, and other low-power devices:

### Docker (Recommended)

```bash
docker run -d --name protoforge \
  -p 8000:8000 \
  -e PROTOFORGE_ADMIN_PASSWORD=admin \
  -v protoforge-data:/app/data \
  suoten/protoforge:latest
```

> Docker image auto-detects CPU architecture (amd64/arm64).

### Resource Usage

| Config | Minimum | Recommended | Tested Baseline |
| ------ | ------- | ----------- | --------------- |
| CPU | ARM Cortex-A53 (1.2GHz) | ARM Cortex-A72 (1.5GHz+) | Pi 4B (4GB) |
| Memory | 256MB (10 devices) | 512MB (50 devices) | 1GB (100+ devices) |
| Disk | 100MB (app) | 1GB (with data) | — |
| Concurrent Devices | 10 | 50 | 100+ |

> 💡 **Pi 4B tested**: 50 devices (Modbus + S7 + MQTT), CPU ~15%, Memory ~180MB — fully smooth.

> ⚠️ **ARM limitations**: OPC-DA and FANUC FOCAS require Windows DLLs (unavailable on ARM). Core protocols (Modbus, S7, OPC-UA, MQTT, FINS, MC, IEC 104, BACnet, CoAP, DDS) fully support ARM64.

---

## 📋 Open Source vs Enterprise

| Feature | Open Source (MIT) | Enterprise |
| ------- | ----------------- | ---------- |
| Protocols | 26, all included | 26 + custom protocols |
| Device Templates | 122+ | 122+ + industry templates |
| Concurrent Devices | Unlimited | Unlimited |
| Web UI | ✅ Full | ✅ + branding |
| REST API | ✅ Full | ✅ + gRPC batch |
| Python SDK | ✅ Sync+Async | ✅ + Java/Go SDK |
| Docker | ✅ | ✅ + Helm/K8s Operator |
| ARM Support | ✅ | ✅ |
| CSV Import/Export | ✅ | ✅ |
| Test Plans | ✅ | ✅ + CI/CD plugins |
| Compliance Checking | ✅ | ✅ + industry standard packs |
| SSO / LDAP | ❌ | ✅ |
| Multi-tenant | ❌ | ✅ |
| Audit Log | ❌ | ✅ |
| SLA Support | ❌ | ✅ 24/7 |
| Professional Services | Community | Dedicated technical manager |

> 💡 **Open source is free forever**: ProtoForge open source includes all core features with no protocol, device, or functionality limits. Enterprise adds organizational management and professional support.

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

> 💬 Contact: [QQ Group](https://qm.qq.com/q/ProtoForge) (Group Owner) or email `suoten@163.com`

---

## 📄 License

MIT