# ProtoForge + EdgeLite 联调指南

本指南介绍如何让 ProtoForge 模拟的设备自动注册到 EdgeLite 网关。

## 联调原理

和 GB28181 填「上级SIP服务器地址」一样，ProtoForge 的每个设备都可以在 `protocol_config` 中填写 EdgeLite 网关地址，设备创建后自动注册到 EdgeLite。

```
GB28181 模式（已有）：
  设备 protocol_config 填 sip_server_addr → 自动注册到国标平台

EdgeLite 模式（新增）：
  设备 protocol_config 填 edgelite_url → 自动注册到 EdgeLite 网关
```

**不填就不推送，不影响 ProtoForge 正常使用。**

## 快速开始

### 1. 创建设备时填写 EdgeLite 地址

在创建设备时，`protocol_config` 中添加 3 个字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `edgelite_url` | EdgeLite 网关地址 | `http://192.168.1.200:8100` |
| `edgelite_username` | EdgeLite 用户名 | `admin` |
| `edgelite_password` | EdgeLite 密码 | `admin` |

> 不填 `edgelite_url` = 不推送，ProtoForge 正常模拟设备。

### 2. 设备自动注册

设备创建后，ProtoForge 自动调用 EdgeLite API 注册设备，包括：
- 协议类型自动映射（如 `ab` → `allen_bradley`）
- 连接参数自动转换（host、port、slave_id 等）
- 测点定义自动同步（名称、数据类型、地址、单位）

### 3. 手动推送

也可以通过 API 手动推送：

```bash
# 推送单个设备
curl -X POST http://localhost:8000/api/v1/integration/edgelite/push/{device_id}

# 测试 EdgeLite 连接
curl -X POST http://localhost:8000/api/v1/integration/edgelite/test \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.200:8100", "username": "admin", "password": "admin"}'
```

---

## 协议映射

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

---

## 完整联调示例

### 场景：模拟 Modbus PLC，EdgeLite 采集数据

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

## 常见问题

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
