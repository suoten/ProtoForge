PROTOCOL_DEFAULTS = {
    "modbus_tcp": {
        "host": "0.0.0.0", "port": 5020,
        "display_name": "Modbus TCP",
        "description": "Modbus TCP/IP协议 — 工业自动化领域应用最广泛的通信协议，基于TCP传输，主从架构，功能码01-06覆盖线圈/寄存器读写",
        "icon": "🔌",
    },
    "modbus_rtu": {
        "host": "/dev/ttyUSB0", "baudrate": 9600,
        "display_name": "Modbus RTU",
        "description": "Modbus RTU协议 — 基于RS-485串行总线的工业通信协议，二进制帧格式，CRC16校验，适用于远距离、强干扰工业现场",
        "icon": "🔌",
    },
    "opcua": {
        "host": "0.0.0.0", "port": 4840,
        "display_name": "OPC UA",
        "description": "OPC统一架构(OPC UA) — 工业4.0标准互联协议，基于面向对象信息模型，支持安全证书认证与加密通信，跨平台互操作",
        "icon": "🌐",
    },
    "mqtt": {
        "host": "0.0.0.0", "port": 1883,
        "display_name": "MQTT",
        "description": "MQTT消息队列遥测传输协议 — IoT领域主流轻量级发布/订阅协议，QoS三级保障，适用于低带宽、高延迟网络环境",
        "icon": "📡",
    },
    "http": {
        "host": "0.0.0.0", "port": 8080,
        "display_name": "HTTP REST",
        "description": "HTTP RESTful API — 基于HTTP的REST接口模拟，支持GET/POST/PUT/DELETE方法，JSON数据格式，适用于Web API对接与集成测试",
        "icon": "🔗",
    },
    "gb28181": {
        "host": "0.0.0.0", "port": 5060, "sip_domain": "3402000000",
        "display_name": "GB/T 28181",
        "description": "GB/T 28181国标视频监控联网协议 — 基于SIP/RTP的视频监控设备互联标准，支持设备注册、实时视频、云台控制、录像回放",
        "icon": "📹",
    },
    "bacnet": {
        "host": "0.0.0.0", "port": 47808,
        "display_name": "BACnet/IP",
        "description": "BACnet/IP楼宇自动化协议 — ASHRAE 135标准，用于暖通空调(HVAC)、照明、安防等楼宇设备互联，对象模型驱动",
        "icon": "🏢",
    },
    "s7": {
        "host": "0.0.0.0", "port": 102, "rack": 0, "slot": 1,
        "display_name": "Siemens S7",
        "description": "西门子S7通信协议(S7 Communication) — S7-1200/1500/300/400 PLC原生协议，基于ISO-on-TCP(RFC 1006)，支持DB/DBX/DBW/DBD寻址",
        "icon": "⚙️",
    },
    "mc": {
        "host": "0.0.0.0", "port": 5000, "network": 0, "station": 0, "pc": 255,
        "display_name": "Mitsubishi MC",
        "description": "三菱MC协议(SLMP) — 三菱FX/Q/L/iQ-R系列PLC以太网通信协议，支持位/字/块读写，二进制/ASCII帧格式",
        "icon": "⚙️",
    },
    "fins": {
        "host": "0.0.0.0", "port": 9600,
        "display_name": "Omron FINS",
        "description": "欧姆龙FINS工厂自动化网络协议 — CJ/CP/NJ/NX系列PLC通信协议，支持CIO/DM/WR内存区域直接访问",
        "icon": "⚙️",
    },
    "ab": {
        "host": "0.0.0.0", "port": 44818,
        "display_name": "Rockwell AB",
        "description": "罗克韦尔EtherNet/IP(CIP) — ControlLogix/CompactLogix PLC通信协议，基于CIP通用工业协议，支持Tag读写与显式消息",
        "icon": "⚙️",
    },
    "opcda": {
        "host": "0.0.0.0", "port": 51340,
        "display_name": "OPC-DA",
        "description": "OPC数据访问经典协议 — 基于COM/DCOM的OPC DA 2.0/3.0，传统SCADA/DCS系统标准数据接口，仅限Windows平台",
        "icon": "🖥️",
    },
    "fanuc": {
        "host": "0.0.0.0", "port": 8193,
        "display_name": "FANUC FOCAS",
        "description": "FANUC FOCAS2数控系统通信库 — 0i/16i/18i/21i/30i/31i/32i系列CNC数据采集协议，支持坐标/状态/参数/程序读写",
        "icon": "🔧",
    },
    "mtconnect": {
        "host": "0.0.0.0", "port": 7878,
        "display_name": "MTConnect",
        "description": "MTConnect机床互联标准 — AMT开发的制造业开源标准，基于HTTP/XML的设备数据采集，支持probe/current/sample三种请求",
        "icon": "🏭",
    },
    "toledo": {
        "host": "0.0.0.0", "port": 1701,
        "display_name": "Mettler-Toledo",
        "description": "梅特勒-托利多称重通信协议 — IND/JAG/XPR系列称重仪表标准协议，支持SI/S/SIR命令集，稳定/毛重/净重/去皮",
        "icon": "⚖️",
    },
}

PROTOCOL_DEVICE_CONFIG = {
    "modbus_tcp": [
        {"key": "slave_id", "label": "从站地址(Unit ID)", "type": "number", "default": 1, "min": 1, "max": 247, "description": "Modbus从站地址，即功能码中的Unit ID(1-247)"},
    ],
    "modbus_rtu": [
        {"key": "slave_id", "label": "从站地址(Unit ID)", "type": "number", "default": 1, "min": 1, "max": 247, "description": "Modbus从站地址"},
        {"key": "baudrate", "label": "波特率", "type": "select", "default": 9600, "options": [2400, 4800, 9600, 19200, 38400, 57600, 115200], "description": "串口通信波特率(bps)"},
        {"key": "parity", "label": "校验位", "type": "select", "default": "none", "options": ["none", "even", "odd"], "description": "串口校验位(N=无校验 E=偶校验 O=奇校验)"},
        {"key": "stopbits", "label": "停止位", "type": "select", "default": 1, "options": [1, 2], "description": "串口停止位"},
    ],
    "opcua": [
        {"key": "server_name", "label": "服务器应用名称", "type": "string", "default": "ProtoForge OPC-UA Server", "description": "OPC-UA服务器ApplicationName，用于发现服务"},
        {"key": "namespace", "label": "命名空间URI", "type": "string", "default": "urn:protoforge:simulation", "description": "节点命名空间URI，客户端通过ns索引访问节点"},
        {"key": "security_mode", "label": "安全模式", "type": "select", "default": "None", "options": ["None", "Sign", "SignAndEncrypt"], "description": "OPC-UA安全模式(None=无加密 Sign=签名 SignAndEncrypt=签名加密)"},
    ],
    "mqtt": [
        {"key": "topic_prefix", "label": "Topic前缀", "type": "string", "default": "protoforge", "description": "MQTT发布主题前缀，格式: {prefix}/{device_id}/{point_name}"},
        {"key": "qos", "label": "QoS等级", "type": "select", "default": 0, "options": [0, 1, 2], "description": "消息服务质量(0=至多一次 1=至少一次 2=恰好一次)"},
        {"key": "username", "label": "用户名", "type": "string", "default": "", "description": "MQTT Broker认证用户名(可选)"},
        {"key": "password", "label": "密码", "type": "string", "default": "", "description": "MQTT Broker认证密码(可选)"},
    ],
    "http": [
        {"key": "api_prefix", "label": "API路径前缀", "type": "string", "default": "/api/v1", "description": "RESTful API路径前缀，如 /api/v1"},
    ],
    "gb28181": [
        {"key": "sip_server_id", "label": "上级SIP服务器ID", "type": "string", "default": "34020000002000000001", "description": "国标上级平台20位编码(中心编码8位+行业编码2位+类型编码3位+网络标识7位)"},
        {"key": "sip_domain", "label": "SIP域编码", "type": "string", "default": "3402000000", "description": "SIP服务器域编码(10位行政区划码)"},
        {"key": "sip_server_addr", "label": "上级SIP服务器地址", "type": "string", "default": "192.168.1.100", "description": "上级视频平台SIP服务器IP地址"},
        {"key": "sip_server_port", "label": "上级SIP端口", "type": "number", "default": 5060, "min": 1, "max": 65535, "description": "上级视频平台SIP信令端口(默认5060)"},
        {"key": "device_id", "label": "设备国标编码", "type": "string", "default": "34020000001320000001", "description": "本设备20位国标编码(中心编码8位+行业编码2位+类型编码3位+序号7位)，类型132=IPC"},
        {"key": "register_interval", "label": "注册周期(秒)", "type": "number", "default": 3600, "min": 60, "max": 86400, "description": "SIP REGISTER注册间隔，国标建议3600秒"},
        {"key": "username", "label": "SIP用户名", "type": "string", "default": "", "description": "SIP认证用户名(留空使用设备国标编码)"},
        {"key": "password", "label": "SIP密码", "type": "string", "default": "", "description": "SIP Digest认证密码"},
    ],
    "bacnet": [
        {"key": "device_id", "label": "设备实例号", "type": "number", "default": 101, "min": 0, "max": 4194303, "description": "BACnet设备对象实例号(BACnetObjectIdentifier)，全网唯一"},
        {"key": "device_name", "label": "设备对象名称", "type": "string", "default": "ProtoForge BACnet Device", "description": "BACnet Device对象的objectName属性"},
        {"key": "vendor_id", "label": "厂商ID", "type": "number", "default": 999, "min": 0, "max": 65535, "description": "BACnet vendorIdentifier(999=非注册厂商)"},
    ],
    "s7": [
        {"key": "rack", "label": "机架号(Rack)", "type": "number", "default": 0, "min": 0, "max": 7, "description": "S7 PLC机架号(S7-1200/1500通常为0)"},
        {"key": "slot", "label": "槽号(Slot)", "type": "number", "default": 1, "min": 0, "max": 31, "description": "CPU所在槽号(S7-1200=1, S7-1500=1, S7-300取决于实际位置)"},
    ],
    "mc": [
        {"key": "network", "label": "网络号", "type": "number", "default": 0, "min": 0, "max": 255, "description": "SLMP通信网络号(0=本地网络)"},
        {"key": "station", "label": "站号", "type": "number", "default": 0, "min": 0, "max": 255, "description": "SLMP通信站号(0=自身站)"},
        {"key": "pc", "label": "PC编号", "type": "number", "default": 255, "min": 0, "max": 255, "description": "SLMP通信PC编号(0xFF=自身PC)"},
    ],
    "fins": [
        {"key": "source_node", "label": "本地FINS节点号", "type": "number", "default": 0, "min": 0, "max": 254, "description": "FINS本地节点号(0=自动分配)"},
        {"key": "dest_node", "label": "目标FINS节点号", "type": "number", "default": 1, "min": 0, "max": 254, "description": "FINS目标节点号(PLC的FINS节点地址)"},
    ],
    "ab": [
        {"key": "slot", "label": "CPU槽号", "type": "number", "default": 0, "min": 0, "max": 17, "description": "ControlLogix/CompactLogix CPU所在槽号(CompactLogix=0)"},
    ],
    "opcda": [
        {"key": "prog_id", "label": "ProgID", "type": "string", "default": "ProtoForge.SimServer.1", "description": "OPC-DA服务器ProgID(Windows注册表标识符)"},
        {"key": "clsid", "label": "CLSID", "type": "string", "default": "", "description": "OPC-DA服务器CLSID(可选，留空自动从ProgID查找注册表)"},
        {"key": "update_rate", "label": "刷新率(ms)", "type": "number", "default": 500, "min": 100, "max": 60000, "description": "OPC组刷新周期(毫秒)"},
    ],
    "fanuc": [
        {"key": "cnc_type", "label": "CNC系统型号", "type": "select", "default": "0i-F", "options": ["0i-F", "0i-F Plus", "31i-B", "31i-A", "16i-B", "18i-B", "0i-MF", "32i"], "description": "FANUC CNC系统型号，影响FOCAS2可用API"},
        {"key": "axis_count", "label": "控制轴数", "type": "number", "default": 3, "min": 1, "max": 8, "description": "CNC控制轴数(车床通常2-3轴，加工中心3-5轴)"},
        {"key": "focas_version", "label": "FOCAS版本", "type": "select", "default": 2, "options": [1, 2], "description": "FOCAS库版本(FOCAS1=旧版 FOCAS2=当前标准)"},
    ],
    "mtconnect": [
        {"key": "device_uuid", "label": "设备UUID", "type": "string", "default": "", "description": "MTConnect设备UUID(留空自动生成，格式如: 000-000-000)"},
        {"key": "manufacturer", "label": "设备制造商", "type": "string", "default": "ProtoForge", "description": "MTConnect Device元素manufacturer属性"},
        {"key": "mtconnect_version", "label": "MTConnect版本", "type": "select", "default": "1.3.0", "options": ["1.2.0", "1.3.0", "1.4.0", "2.0.0"], "description": "MTConnect协议版本(1.3=当前最广泛 2.0=支持REST)"},
    ],
    "toledo": [
        {"key": "scale_addr", "label": "秤通讯地址", "type": "string", "default": "1", "description": "称重仪表通讯地址(SI/S命令中使用的地址编号)"},
        {"key": "unit", "label": "称重单位", "type": "select", "default": "kg", "options": ["kg", "g", "mg", "lb", "oz", "t", "ct"], "description": "称重单位(ct=克拉)"},
        {"key": "decimal_places", "label": "小数位数", "type": "number", "default": 3, "min": 0, "max": 6, "description": "称重显示小数位数"},
    ],
}

PROTOCOL_USAGE = {
    "modbus_tcp": {
        "mode": "server",
        "mode_label": "服务端模拟(从站)",
        "mode_desc": "ProtoForge 模拟 Modbus TCP 从站(Slave)，你的应用作为主站(Master)连接读写寄存器",
        "connect_hint": "在你的 Modbus 主站程序中，连接参数填写：",
        "code_example": "# pymodbus 示例 — Modbus TCP 主站\nfrom pymodbus.client import ModbusTcpClient\n\nclient = ModbusTcpClient('{host}', port={port})\nclient.connect()\n\n# 功能码03: 读取保持寄存器(Holding Registers)\nresult = client.read_holding_registers(address=0, count=10, slave={slave_id})\nif not result.isError():\n    print('寄存器值:', result.registers)\n\n# 功能码06: 写入单个保持寄存器\nclient.write_register(address=0, value=100, slave={slave_id})\n\n# 功能码01: 读取线圈(Coils)\nresult = client.read_coils(address=0, count=8, slave={slave_id})\n\n# 功能码04: 读取输入寄存器(Input Registers)\nresult = client.read_input_registers(address=0, count=4, slave={slave_id})",
    },
    "modbus_rtu": {
        "mode": "server",
        "mode_label": "服务端模拟(从站)",
        "mode_desc": "ProtoForge 模拟 Modbus RTU 从站(Slave)，你的应用通过RS-485串口作为主站连接",
        "connect_hint": "配置串口参数连接：",
        "code_example": "# pymodbus 示例 — Modbus RTU 主站\nfrom pymodbus.client import ModbusSerialClient\n\nclient = ModbusSerialClient(\n    port='{host}',       # 串口设备路径\n    baudrate={baudrate}, # 波特率\n    parity='N',          # 校验位(N=无 E=偶 O=奇)\n    stopbits=1,          # 停止位\n    bytesize=8,          # 数据位\n)\nclient.connect()\nresult = client.read_holding_registers(0, 10, slave={slave_id})",
    },
    "opcua": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 OPC-UA 服务器，你的应用作为客户端连接，浏览节点并读写变量",
        "connect_hint": "在你的 OPC-UA 客户端中，连接端点(Endpoint)填写：",
        "code_example": "# opcua/opcua-asyncio 示例 — OPC-UA 客户端\nfrom opcua import Client\n\nclient = Client('opc.tcp://{host}:{port}')\nclient.connect()\n\n# 浏览地址空间\nroot = client.get_root_node()\nfor child in root.get_children():\n    print(child.get_browse_name())\n\n# 通过节点ID读取变量\nnode = client.get_node('ns=2;s=protoforge.temperature')\nvalue = node.get_value()\nprint(f'温度: {value}')\n\n# 写入变量\nnode.set_value(25.5)",
    },
    "mqtt": {
        "mode": "broker",
        "mode_label": "Broker代理",
        "mode_desc": "ProtoForge 内置 MQTT Broker，自动发布仿真数据到 Topic，你的应用订阅即可接收",
        "connect_hint": "你的 MQTT 客户端连接 ProtoForge Broker 后，订阅以下 Topic：",
        "code_example": "# paho-mqtt 示例 — MQTT 客户端订阅\nimport paho.mqtt.client as mqtt\nimport json\n\ndef on_message(client, userdata, msg):\n    data = json.loads(msg.payload.decode())\n    print(f'Topic: {msg.topic}')\n    print(f'  设备: {data[\"device_id\"]}')\n    print(f'  测点: {data[\"point\"]}')\n    print(f'  数值: {data[\"value\"]} {data[\"unit\"]}')\n\nclient = mqtt.Client()\nclient.on_message = on_message\nclient.connect('{host}', {port})\n\n# 订阅所有设备的仿真数据\nclient.subscribe('protoforge/#')\nclient.loop_forever()",
    },
    "http": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 HTTP REST API，你的应用发送 HTTP 请求获取/写入仿真数据",
        "connect_hint": "在你的应用中，API 基础地址填写：",
        "code_example": "# requests 示例 — HTTP REST 客户端\nimport requests\n\nbase_url = 'http://{host}:{port}{api_prefix}'\n\n# GET 读取设备所有测点\nresp = requests.get(f'{base_url}/devices/{{device_id}}/points')\nfor point in resp.json():\n    print(f'{point[\"name\"]}: {point[\"value\"]} {point[\"unit\"]}')\n\n# POST 写入指定测点\nresp = requests.post(\n    f'{base_url}/devices/{{device_id}}/points/temperature',\n    json={'value': 25.5}\n)",
    },
    "gb28181": {
        "mode": "client",
        "mode_label": "客户端注册(模拟IPC/NVR)",
        "mode_desc": "ProtoForge 模拟国标摄像头/NVR设备，主动向上级视频平台发起SIP注册，支持实时视频推流(RTP/PS)",
        "connect_hint": "ProtoForge 会向你配置的国标平台发起 SIP REGISTER，你的平台需要：",
        "code_example": "# 你的国标视频平台需要：\n# 1. 开放 SIP 信令端口(默认5060)\n# 2. 配置 SIP 服务器ID: {sip_server_id}\n# 3. SIP 域编码: {sip_domain}\n# 4. 设备注册后，平台可发起：\n#    - INVITE: 实时视频请求(ProtoForge自动推送RTP/PS流)\n#    - MESSAGE Catalog: 设备目录查询\n#    - MESSAGE Keepalive: 心跳保活\n#    - MESSAGE DeviceControl: 云台控制(PTZ)\n#\n# 设备国标编码: {device_id}\n# 注册周期: {register_interval}秒\n# SIP传输: UDP",
    },
    "bacnet": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 BACnet/IP 设备，你的应用作为 BACnet 客户端读写对象属性",
        "connect_hint": "在你的 BACnet 客户端中，设备地址填写：",
        "code_example": "# BAC0 示例 — BACnet 客户端\nimport BAC0\n\nbacnet = BAC0.lite()\n\n# 读取设备属性\nname = bacnet.read('{host} device {device_id} objectName')\nprint(f'设备名称: {name}')\n\n# 读取模拟输入(AI)\nvalue = bacnet.read('{host} analogInput 1 presentValue')\nprint(f'AI-1 当前值: {value}')\n\n# 写入模拟输出(AO)\nbacnet.write('{host} analogOutput 1 presentValue 75.0')",
    },
    "s7": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟西门子 S7 PLC，你的应用作为 S7 客户端连接，读写DB/I/Q/M区数据",
        "connect_hint": "在你的 S7 通信程序中，连接参数填写：",
        "code_example": "# python-snap7 示例 — S7 客户端\nimport snap7\nfrom snap7.util import get_real, set_real\n\nclient = snap7.client.Client()\nclient.connect('{host}', {rack}, {slot}, {port})\n\n# 读取 DB1.DBD0 (浮点数, 4字节)\ndata = client.db_read(db_number=1, start=0, size=4)\nvalue = get_real(data, 0)\nprint(f'DB1.DBD0 = {value}')\n\n# 写入 DB1.DBD0\nset_real(data, 0, 25.5)\nclient.db_write(db_number=1, start=0, data=data)\n\n# 读取 DB1.DBX0.0 (布尔量)\ndata = client.db_read(db_number=1, start=0, size=1)\nbit = (data[0] >> 0) & 1\nprint(f'DB1.DBX0.0 = {bool(bit)}')",
    },
    "mc": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟三菱 PLC，你的应用通过 SLMP(Binary/ASCII) 协议连接，读写D/R/X/Y/M设备",
        "connect_hint": "在你的 MC/SLMP 通信程序中，连接参数填写：",
        "code_example": "# pymcprotocol 示例 — SLMP客户端\nfrom pymcprotocol import Type3E\n\nclient = Type3E()\nclient.connect('{host}', {port})\n\n# 批量读取字设备(D寄存器)\nwords = client.batch_read_word_units(head_device='D100', device_number=10)\nprint(f'D100-D109: {words}')\n\n# 批量写入字设备\nclient.batch_write_word_units(head_device='D100', write_values=[100, 200, 300])\n\n# 读取位设备(X输入)\nbits = client.batch_read_bit_units(head_device='X0', device_number=16)\n\n# 写入位设备(Y输出)\nclient.batch_write_bit_units(head_device='Y0', write_values=[1, 0, 1, 0])",
    },
    "fins": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟欧姆龙 PLC，你的应用通过 FINS TCP 协议连接，读写CIO/DM/WR/HR内存区域",
        "connect_hint": "在你的 FINS 通信程序中，连接参数填写：",
        "code_example": "# pyfins 示例 — FINS TCP 客户端\nfrom pyfins import FinsClient\n\nclient = FinsClient('{host}', {port})\n\n# 读取 DM 区(DM0开始, 10个字)\nvalues = client.memory_area_read(\n    memory_area=0x82,  # DM区\n    start_address=0,\n    count=10\n)\nprint(f'DM0-DM9: {values}')\n\n# 写入 DM 区\nclient.memory_area_write(\n    memory_area=0x82,\n    start_address=0,\n    data=[100, 200, 300]\n)\n\n# 读取 CIO 区\nvalues = client.memory_area_read(memory_area=0x80, start_address=0, count=10)",
    },
    "ab": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟罗克韦尔 PLC，你的应用通过 EtherNet/IP(CIP) 协议连接，读写Tag标签",
        "connect_hint": "在你的 EtherNet/IP 通信程序中，连接参数填写：",
        "code_example": "# pylogix 示例 — EtherNet/IP 客户端\nfrom pylogix import PLC\n\nwith PLC() as comm:\n    comm.IPAddress = '{host}'\n    comm.ProcessorSlot = {slot}\n\n    # 读取标签\n    ret = comm.Read('Temperature')\n    print(f'Temperature = {ret.Value}')\n\n    # 写入标签\n    comm.Write('Temperature', 25.5)\n\n    # 读取多个标签\n    tags = comm.GetTagList()\n    for tag in tags.Value:\n        print(tag.TagName, tag.DataType)",
    },
    "opcda": {
        "mode": "server",
        "mode_label": "服务端模拟(Windows COM)",
        "mode_desc": "ProtoForge 模拟 OPC-DA 服务器(Windows COM组件)，你的应用作为OPC客户端通过COM接口读写标签",
        "connect_hint": "在你的 OPC-DA 客户端中，ProgID 填写：",
        "code_example": "# OpenOPC 示例 — OPC-DA 客户端(仅Windows)\nimport OpenOPC\n\nopc = OpenOPC.client()\nopc.connect('{prog_id}')\n\n# 读取标签(同步)\nvalue = opc.read('protoforge.temperature')\nprint(f'温度: {value}')\n\n# 写入标签\nopc.write(('protoforge.temperature', 25.5))\n\n# 浏览标签树\ntags = opc.list('*')\nprint(f'可用标签: {tags}')",
    },
    "fanuc": {
        "mode": "server",
        "mode_label": "服务端模拟(CNC)",
        "mode_desc": "ProtoForge 模拟 FANUC CNC 数控系统，你的应用通过 FOCAS2 库连接，读取坐标/状态/参数",
        "connect_hint": "在你的 FOCAS2 通信程序中，连接参数填写：",
        "code_example": "# FOCAS2 示例 — FANUC CNC 客户端\n# 需要: Fwlib32.dll / Fwlib32E.dll\n# 连接: {host}:{port}\n# CNC型号: {cnc_type}\n# 轴数: {axis_count}\n\n# 读取 CNC 系统信息\n# cnc_statinfo() -> 运行状态、主轴转速、进给率\n# cnc_rdaxis() -> 各轴绝对/机械/相对坐标\n# cnc_rdparam() -> CNC参数读写\n# cnc_rdprognum() -> 当前执行程序号\n# cnc_alarm() -> 报警信息\n# cnc_exeprgname() -> 当前执行程序名",
    },
    "mtconnect": {
        "mode": "server",
        "mode_label": "服务端模拟(Agent)",
        "mode_desc": "ProtoForge 模拟 MTConnect Agent，你的应用通过 HTTP 请求获取设备数据(XML格式)",
        "connect_hint": "在你的 MTConnect 客户端中，Agent 地址填写：",
        "code_example": "# MTConnect HTTP 客户端示例\nimport requests\n\nbase = 'http://{host}:{port}'\n\n# probe: 获取设备能力描述(XML)\nresp = requests.get(f'{base}/probe')\nprint(resp.text)\n\n# current: 获取最新采样值\nresp = requests.get(f'{base}/current')\nprint(resp.text)\n\n# sample: 获取历史采样序列\nresp = requests.get(f'{base}/sample?from=1000&count=500')\nprint(resp.text)\n\n# 带路径的设备数据\nresp = requests.get(f'{base}/current?path=//Device[@name=\"device1\"]')",
    },
    "toledo": {
        "mode": "server",
        "mode_label": "服务端模拟(称重仪表)",
        "mode_desc": "ProtoForge 模拟梅特勒-托利多称重仪表，你的应用通过TCP/串口发送SI/S命令读取重量数据",
        "connect_hint": "在你的称重通信程序中，连接参数填写：",
        "code_example": "# Toledo TCP 客户端示例\nimport socket\n\nsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\nsock.connect(('{host}', {port}))\n\n# SI命令: 读取稳定重量\nsock.sendall(b'SI\\r\\n')\nresponse = sock.recv(1024)\nprint(response.decode())  # 如: 'S S     12.345 kg'\n\n# S命令: 立即读取(含动态)\nsock.sendall(b'S\\r\\n')\n\n# SIR命令: 连续发送重量数据\nsock.sendall(b'SIR\\r\\n')\n\n# T命令: 去皮\nsock.sendall(b'T\\r\\n')\n\n# Z命令: 清零\nsock.sendall(b'Z\\r\\n')",
    },
}

ERROR_MESSAGES = {
    "Device not found": "找不到该设备，可能已被删除或ID输入错误。请检查设备列表。",
    "Scenario not found": "找不到该场景，可能已被删除。请检查场景列表。",
    "Template not found": "找不到该模板。请从模板市场选择可用模板。",
    "Protocol not found": "找不到该协议服务。请先在「协议服务」页面启动对应协议。",
    "Protocol already running": "该协议已在运行中，无需重复启动。",
    "Protocol not running": "该协议未启动。请先启动协议后再操作设备。",
    "Device already exists": "设备ID已存在。请更换一个唯一的设备ID。",
    "Invalid credentials": "用户名或密码错误。默认账号: admin / admin",
    "Username already exists": "该用户名已被注册，请换一个。",
    "Password must be at least 6 characters": "密码至少需要6个字符，请设置更安全的密码。",
    "Cannot delete this user": "无法删除管理员账号。",
    "url is required": "请填写Webhook的URL地址。",
    "No active recording": "当前没有正在进行的录制。请先开始录制。",
    "devices= cannot be None": "Modbus从站上下文初始化失败，请确保至少有一个设备。",
}


def get_friendly_error(detail: str) -> str:
    for key, msg in ERROR_MESSAGES.items():
        if key.lower() in detail.lower():
            return msg
    return detail


def get_protocol_defaults(protocol_name: str) -> dict:
    from protoforge.config import get_protocol_port_map
    base = PROTOCOL_DEFAULTS.get(protocol_name, {"host": "0.0.0.0", "port": 8000})
    port_map = get_protocol_port_map()
    if protocol_name in port_map:
        base = {**base, **port_map[protocol_name]}
    return base


def get_all_protocol_info() -> list[dict]:
    from protoforge.config import get_protocol_port_map
    port_map = get_protocol_port_map()
    result = []
    for name, info in PROTOCOL_DEFAULTS.items():
        port_info = port_map.get(name, {})
        result.append({
            "name": name,
            "display_name": info.get("display_name", name),
            "description": info.get("description", ""),
            "default_port": port_info.get("port", info.get("port", 0)),
            "icon": info.get("icon", ""),
        })
    return result
