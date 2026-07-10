# ProtoForge 与第三方系统对接指南

本指南介绍如何将 ProtoForge 与任意上位机、SCADA、物联网网关、采集程序对接。

## 核心理解：ProtoForge 是什么？

> **ProtoForge 不是网关，不采集数据，不转发数据。它是「被采集的对象」——一台虚拟设备。**

ProtoForge 启动的是**标准协议服务端**（Modbus TCP Server、OPC-UA Server、S7 Server、MQTT Broker……），任何能连接这些协议的软件都能直接对接，**不需要任何适配层或特殊 SDK**。对你的网关/SCADA/采集程序来说，ProtoForge 和一台真实 PLC/传感器没有任何区别。

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
                    │  ...（17 种协议服务端）              │
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

## 三种对接方式

| 方式 | 适合场景 | 怎么做 |
|------|---------|--------|
| **① 直接连接**（推荐） | 你有自己的采集程序或网关 | ProtoForge 启动协议服务后，你的程序作为客户端连接对应端口即可（如 pymodbus 连 5020） |
| **② EdgeLite 自动注册** | 你用 EdgeLite 做网关 | 设备配置中填 `edgelite_url`，ProtoForge 自动把设备配置推送到 EdgeLite，免手动配置 |
| **③ 标准网关手动配置** | 你用 Kepware/Node-RED/Ignition 等第三方网关 | 在网关中手动添加设备，地址填 ProtoForge 的 IP 和端口（如 `127.0.0.1:5020`） |

---

## 方式 ①：直接连接（最通用）

ProtoForge 启动协议服务后，任何协议客户端都能直接连接。**不需要在 ProtoForge 做任何额外配置。**

### Python — Modbus TCP

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("127.0.0.1", port=5020)
client.connect()
# pymodbus 3.8+ 使用 device_id 参数（旧版本用 slave_id）
result = client.read_holding_registers(address=100, count=2, device_id=1)
print(f"温度寄存器: {result.registers}")
client.close()
```

### Python — OPC-UA

```python
from asyncua.sync import Client

client = Client("opc.tcp://127.0.0.1:4840")
client.connect()
node = client.get_node("ns=2;s=Temperature")
print(f"温度: {node.read_value()}")
client.disconnect()
```

### Python — S7（西门子）

```python
from snap7.client import Client as S7Client

client = S7Client()
client.connect("127.0.0.1", 0, 1)  # IP, rack, slot
data = client.db_read(1, 0, 4)      # DB1, offset 0, 4 bytes
print(f"数据: {data}")
client.disconnect()
```

### Node.js — MQTT

```javascript
import mqtt from 'mqtt'
const client = mqtt.connect('mqtt://127.0.0.1:1883')
client.on('message', (topic, message) => {
  console.log(`${topic}: ${message.toString()}`)
})
client.subscribe('sensor/temperature')
```

### 通用 HTTP

```bash
# ProtoForge 的 HTTP 协议服务提供 RESTful 接口
curl http://127.0.0.1:8080/devices/modbus-plc-001/points/temperature
```

---

## 方式 ②：EdgeLite 自动注册（便捷）

如果你用 [EdgeLite](https://github.com/suoten/EdgeLiteGateway) 做网关，ProtoForge 可以自动把设备配置推送过去，免去手动在 EdgeLite 中添加设备的步骤。

### 联调原理

和 GB28181 填「上级SIP服务器地址」一样的体验：

```
GB28181：设备 protocol_config 填 sip_server_addr → 自动注册到国标平台
EdgeLite：设备 protocol_config 填 edgelite_url → 自动注册到 EdgeLite 网关
```

**不填就不推送，不影响 ProtoForge 正常使用。**

### 快速开始

#### 1. 创建设备时填写 EdgeLite 地址

在创建设备时，`protocol_config` 中添加 3 个字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `edgelite_url` | EdgeLite 网关地址 | `http://192.168.1.200:8100` |
| `edgelite_username` | EdgeLite 用户名 | `admin` |
| `edgelite_password` | EdgeLite 密码 | `admin` |

> 不填 `edgelite_url` = 不推送，ProtoForge 正常模拟设备。

#### 2. 设备自动注册

设备创建后，ProtoForge 自动调用 EdgeLite API 注册设备，包括：
- 协议类型自动映射（如 `ab` → `allen_bradley`）
- 连接参数自动转换（host、port、slave_id 等）
- 测点定义自动同步（名称、数据类型、地址、单位）

#### 3. 手动推送（可选）

也可以通过 API 手动推送：

```bash
# 推送单个设备
curl -X POST http://localhost:8000/api/v1/integration/edgelite/push/{device_id}

# 测试 EdgeLite 连接
curl -X POST http://localhost:8000/api/v1/integration/edgelite/test \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.200:8100", "username": "admin", "password": "admin"}'
```

### 协议映射

| ProtoForge 协议 | EdgeLite 协议 | 说明 |
|----------------|--------------|------|
| modbus_tcp | modbus_tcp | host, port, slave_id |
| modbus_rtu | modbus_rtu | serial_port, baudrate, slave_id |
| opcua | opcua | endpoint, security_mode |
| mqtt | mqtt | broker, port |
| http | http | url, method |
| s7 | s7 | host, port, rack, slot |
| mc | mc | host, port |
| fins | fins | host, port |
| ab | allen_bradley | host, port |
| bacnet | bacnet | host, port |
| fanuc | fanuc | host, port |
| mtconnect | mtconnect | url |
| toledo | toledo | host, port |
| opcda | opc_da | prog_id |
| gb28181 | — | 不推送（通过国标平台直连） |

### 完整联调示例

**场景：模拟 Modbus PLC，EdgeLite 采集数据**

**1. ProtoForge 创建设备**

```json
{
  "id": "modbus-plc-001",
  "name": "测试PLC",
  "protocol": "modbus_tcp",
  "protocol_config": {
    "host": "192.168.1.100",
    "port": 5020,
    "slave_id": 1,
    "edgelite_url": "http://192.168.1.200:8100",
    "edgelite_username": "admin",
    "edgelite_password": "admin"
  },
  "points": [
    {"name": "temperature", "data_type": "float32", "address": "100", "unit": "°C"},
    {"name": "pressure", "data_type": "float32", "address": "102", "unit": "MPa"}
  ]
}
```

**2. EdgeLite 自动出现设备**

打开 EdgeLite Web 界面，设备列表中已出现 `modbus-plc-001`，配置已自动填好：
- 协议：`modbus_tcp`
- 连接：`192.168.1.100:5020`，slave_id=1
- 测点：temperature(HR100, float32)、pressure(HR102, float32)

**3. 启动 ProtoForge 协议服务**

在 ProtoForge 中启动 Modbus TCP 协议服务，EdgeLite 即可开始采集数据。

---

## 方式 ③：标准网关手动配置（Kepware / Node-RED / Ignition 等）

ProtoForge 对任何标准网关来说都是一台「真实设备」。你只需要在网关中手动添加设备，地址填 ProtoForge 的 IP 和端口即可。

### Kepware 对接示例

1. ProtoForge 中启动 Modbus TCP 协议服务（默认端口 5020）
2. ProtoForge 中创建一台 Modbus 设备（记住 slave_id 和测点地址）
3. Kepware 中新建一个 Modbus TCP 驱动，IP 填 ProtoForge 所在机器 IP，端口填 5020
4. Kepware 中新建设备，slave_id 与 ProtoForge 中一致
5. Kepware 中添加点位，地址与 ProtoForge 中一致

### Node-RED 对接示例

1. ProtoForge 中启动 Modbus TCP 协议服务
2. Node-RED 中安装 `node-red-contrib-modbus` 节点
3. 配置 Modbus-Read 节点：TCP Host=ProtoForge IP，Port=5020，Unit ID=slave_id
4. 部署流程即可读取 ProtoForge 仿真数据

### Ignition / 其他 SCADA 对接

流程相同：在网关/SCADA 中添加对应协议驱动，地址指向 ProtoForge 的 IP 和端口。ProtoForge 不会区分连接来源，对所有客户端一视同仁。

**就是这么简单——ProtoForge 对你的网关来说，和一台真实 PLC 没有任何区别。**

---

## 常见问题

### Q: ProtoForge 能和其他网关（非 EdgeLite）对接吗？

**能，而且不需要任何额外适配。** ProtoForge 启动的是标准协议服务端，任何支持 Modbus/OPC-UA/S7/MQTT 等协议的网关都能直接连接。EdgeLite 只是 ProtoForge 提供了「自动注册」便捷功能的一种网关，其他网关用手动配置方式即可。

### Q: 我必须用 EdgeLite 吗？

**不需要。** EdgeLite 只是可选的便捷项。你完全可以用 Kepware、Node-RED、Ignition、自研采集程序等任何系统直接连接 ProtoForge。

### Q: ProtoForge 是网关吗？会采集我的真实设备数据吗？

**不是，也不会。** ProtoForge 是一台「虚拟设备」，它只模拟设备产生数据，不采集任何真实设备数据，也不转发数据。它是「被采集的对象」，不是「采集者」。

### Q: 不填 edgelite_url 会怎样？

不填就不推送，ProtoForge 正常模拟设备，完全不受影响。

### Q: 推送失败怎么办？

1. 检查 EdgeLite 是否运行
2. 检查 `edgelite_url` 是否正确
3. 检查用户名密码
4. 通过 API 测试连接：`POST /api/v1/integration/edgelite/test`

### Q: 设备已存在怎么更新？

推送已存在的设备会自动更新（先尝试创建，409 冲突后自动改为更新）。

### Q: GB28181 设备能推送吗？

不能，也不需要。GB28181 设备直接通过国标平台参数注册，和 EdgeLite 无关。
