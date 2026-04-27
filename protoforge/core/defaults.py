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
    "profinet": {
        "host": "0.0.0.0", "port": 34964,
        "display_name": "PROFINET IO",
        "description": "PROFINET IO实时工业以太网协议 — PI组织标准，基于以太网的实时通信，支持DCP发现/配置、RT/IRT循环数据交换、GSD设备描述",
        "icon": "🏭",
    },
    "ethercat": {
        "host": "0.0.0.0", "port": 34980,
        "display_name": "EtherCAT",
        "description": "EtherCAT实时工业以太网协议 — 倍福(Beckhoff)开发，基于\"飞速处理\"(On-the-fly)技术，极低延迟的分布式时钟同步，广泛用于运动控制",
        "icon": "⚡",
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
    "profinet": [
        {"key": "device_name", "label": "设备名称(DeviceName)", "type": "string", "default": "protoforge-device", "description": "PROFINET设备名称，DCP识别和寻址使用(如: my-plc-01)"},
        {"key": "vendor_id", "label": "厂商ID(VendorID)", "type": "number", "default": 266, "min": 0, "max": 65535, "description": "PROFINET厂商标识符(PI组织分配)"},
        {"key": "device_id", "label": "设备ID(DeviceID)", "type": "number", "default": 256, "min": 0, "max": 65535, "description": "PROFINET设备标识符(标识设备类型)"},
    ],
    "ethercat": [
        {"key": "slave_address", "label": "从站地址", "type": "number", "default": 4097, "min": 1, "max": 65535, "description": "EtherCAT从站地址(Station Address)，主站通过此地址寻址从站"},
    ],
}

PROTOCOL_USAGE = {
    "modbus_tcp": {
        "mode": "server",
        "mode_label": "服务端模拟(从站)",
        "mode_desc": "ProtoForge 模拟 Modbus TCP 从站(Slave)，你的应用作为主站(Master)连接读写寄存器",
        "connect_hint": "在你的 Modbus 主站程序中，连接参数填写：",
        "code_examples": {
            "python": "# pymodbus 示例 — Modbus TCP 主站\nfrom pymodbus.client import ModbusTcpClient\n\nclient = ModbusTcpClient('{host}', port={port})\nclient.connect()\n\n# 功能码03: 读取保持寄存器\nresult = client.read_holding_registers(address=0, count=10, slave={slave_id})\nif not result.isError():\n    print('寄存器值:', result.registers)\n\n# 功能码06: 写入单个保持寄存器\nclient.write_register(address=0, value=100, slave={slave_id})",
            "csharp": "// NModbus4 示例 — Modbus TCP 主站\nusing NModbus;\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar factory = new ModbusFactory();\nvar master = factory.CreateMaster(tcp);\n\n// 功能码03: 读取保持寄存器\nushort[] registers = await master.ReadHoldingRegistersAsync({slave_id}, 0, 10);\nConsole.WriteLine($\"寄存器值: {{string.Join(\", \", registers)}}\");\n\n// 功能码06: 写入单个保持寄存器\nawait master.WriteSingleRegisterAsync({slave_id}, 0, 100);",
            "java": "// modbus4j 示例 — Modbus TCP 主站\nimport com.serotonin.modbus4j.ModbusFactory;\nimport com.serotonin.modbus4j.ip.IpParameters;\n\nIpParameters params = new IpParameters();\nparams.setHost(\"{host}\");\nparams.setPort({port});\nModbusMaster master = new ModbusFactory().createTcpMaster(params, false);\nmaster.init();\n\n// 功能码03: 读取保持寄存器\nReadInputRegistersRequest req = new ReadInputRegistersRequest({slave_id}, 0, 10);\nReadInputRegistersResponse res = (ReadInputRegistersResponse) master.send(req);\nSystem.out.println(\"寄存器值: \" + Arrays.toString(res.getShortData()));",
            "go": "// modbus 示例 — Modbus TCP 主站\nimport (\n    \"github.com/goburrow/modbus\"\n)\n\nhandler := modbus.NewTCPClientHandler(\"{host}:{port}\")\nhandler.Connect()\nclient := modbus.NewClient(handler)\n\n// 功能码03: 读取保持寄存器\nresults, _ := client.ReadHoldingRegisters(0, 10)\nfmt.Printf(\"寄存器值: %v\\n\", results)\n\n// 功能码06: 写入单个保持寄存器\nclient.WriteSingleRegister(0, 100)",
        },
    },
    "modbus_rtu": {
        "mode": "server",
        "mode_label": "服务端模拟(从站)",
        "mode_desc": "ProtoForge 模拟 Modbus RTU 从站(Slave)，你的应用通过RS-485串口作为主站连接",
        "connect_hint": "配置串口参数连接：",
        "code_examples": {
            "python": "# pymodbus 示例 — Modbus RTU 主站\nfrom pymodbus.client import ModbusSerialClient\n\nclient = ModbusSerialClient(\n    port='{host}', baudrate={baudrate},\n    parity='N', stopbits=1, bytesize=8,\n)\nclient.connect()\nresult = client.read_holding_registers(0, 10, slave={slave_id})",
            "csharp": "// NModbus4 示例 — Modbus RTU 主站\nusing NModbus;\nusing System.IO.Ports;\n\nusing var port = new SerialPort(\"{host}\", {baudrate}, Parity.None, 8, StopBits.One);\nport.Open();\nvar factory = new ModbusFactory();\nvar master = factory.CreateRtuMaster(port);\n\nushort[] registers = await master.ReadHoldingRegistersAsync({slave_id}, 0, 10);",
            "java": "// modbus4j 示例 — Modbus RTU 主站\nimport com.serotonin.modbus4j.ModbusFactory;\nimport com.serotonin.modbus4j.serial.SerialPort;\n\nModbusMaster master = new ModbusFactory().createRtuMaster(\n    new SerialPortImpl(\"{host}\", {baudrate})\n);\nmaster.init();\nReadInputRegistersResponse res = (ReadInputRegistersResponse)\n    master.send(new ReadInputRegistersRequest({slave_id}, 0, 10));",
            "go": "// modbus 示例 — Modbus RTU 主站\nimport \"github.com/goburrow/modbus\"\n\nhandler := modbus.NewRTUClientHandler(\"{host}\")\nhandler.BaudRate = {baudrate}\nhandler.Connect()\nclient := modbus.NewClient(handler)\nresults, _ := client.ReadHoldingRegisters(0, 10)",
        },
    },
    "opcua": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 OPC-UA 服务器，你的应用作为客户端连接，浏览节点并读写变量",
        "connect_hint": "在你的 OPC-UA 客户端中，连接端点(Endpoint)填写：",
        "code_examples": {
            "python": "# opcua 示例 — OPC-UA 客户端\nfrom opcua import Client\n\nclient = Client('opc.tcp://{host}:{port}')\nclient.connect()\n\n# 浏览地址空间\nroot = client.get_root_node()\nfor child in root.get_children():\n    print(child.get_browse_name())\n\n# 读取变量\nnode = client.get_node('ns=2;s=protoforge.temperature')\nvalue = node.get_value()\nprint(f'温度: {value}')\n\n# 写入变量\nnode.set_value(25.5)",
            "csharp": "// OPC-UA SDK 示例 — OPC-UA 客户端\nusing Opc.Ua;\nusing Opc.Ua.Client;\n\nvar endpoint = new EndpointDescription(\"opc.tcp://{host}:{port}\");\nvar session = await Session.Create(\n    new ApplicationConfiguration(),\n    new ConfiguredEndpoint(null, endpoint),\n    true, \"\", 60000, null, null);\n\n// 读取节点\nvar node = session.ReadNode(new NodeId(\"protoforge.temperature\", 2));\nConsole.WriteLine($\"温度: {{node.Value}}\");\n\n// 写入节点\nsession.WriteNode(new NodeId(\"protoforge.temperature\", 2), 25.5);",
            "java": "// eclipse milo 示例 — OPC-UA 客户端\nimport org.eclipse.milo.opcua.sdk.client.OpcUaClient;\n\nOpcUaClient client = OpcUaClient.create(\"opc.tcp://{host}:{port}\");\nclient.connect().get();\n\n// 读取节点\nNodeId nodeId = new NodeId(2, \"protoforge.temperature\");\nDataValue value = client.readValue(0, TimestampsToReturn.Both, nodeId).get();\nSystem.out.println(\"温度: \" + value.getValue().getValue());",
            "go": "// opcua 示例 — OPC-UA 客户端\nimport \"github.com/gopcua/opcua\"\n\nclient, _ := opcua.NewClient(\"opc.tcp://{host}:{port}\")\nclient.Connect(context.Background())\n\n// 读取节点\nid := opcua.NewStringNodeID(2, \"protoforge.temperature\")\nresp, _ := client.Read(context.Background(), &ua.ReadRequest{\n    NodesToRead: []*ua.ReadValueID{{NodeID: id}},\n})\nfmt.Printf(\"温度: %v\\n\", resp.Results[0].Value)",
        },
    },
    "mqtt": {
        "mode": "broker",
        "mode_label": "Broker代理",
        "mode_desc": "ProtoForge 内置 MQTT Broker，自动发布仿真数据到 Topic，你的应用订阅即可接收",
        "connect_hint": "你的 MQTT 客户端连接 ProtoForge Broker 后，订阅以下 Topic：",
        "code_examples": {
            "python": "# paho-mqtt 示例 — MQTT 客户端订阅\nimport paho.mqtt.client as mqtt\nimport json\n\ndef on_message(client, userdata, msg):\n    data = json.loads(msg.payload.decode())\n    print(f'Topic: {msg.topic}')\n    print(f'  数值: {data[\"value\"]} {data[\"unit\"]}')\n\nclient = mqtt.Client()\nclient.on_message = on_message\nclient.connect('{host}', {port})\nclient.subscribe('protoforge/#')\nclient.loop_forever()",
            "csharp": "// MQTTnet 示例 — MQTT 客户端订阅\nusing MQTTnet;\nusing MQTTnet.Client;\n\nvar factory = new MqttFactory();\nvar client = factory.CreateMqttClient();\n\nclient.ApplicationMessageReceivedAsync += e =>\n{\n    Console.WriteLine($\"Topic: {{e.ApplicationMessage.Topic}}\");\n    Console.WriteLine($\"Payload: {{e.ApplicationMessage.ConvertPayloadToString()}}\");\n    return Task.CompletedTask;\n};\n\nawait client.ConnectAsync(new MqttClientOptionsBuilder()\n    .WithTcpServer(\"{host}\", {port}).Build());\nawait client.SubscribeAsync(\"protoforge/#\");",
            "java": "// Eclipse Paho 示例 — MQTT 客户端订阅\nimport org.eclipse.paho.client.mqttv3.*;\n\nMqttClient client = new MqttClient(\"tcp://{host}:{port}\", \"subscriber\");\nclient.connect();\nclient.subscribe(\"protoforge/#\", (topic, msg) -> {\n    System.out.println(\"Topic: \" + topic);\n    System.out.println(\"Payload: \" + new String(msg.getPayload()));\n});",
            "go": "// paho.mqtt 示例 — MQTT 客户端订阅\nimport (\n    \"github.com/eclipse/paho.mqtt.golang\"\n)\n\nopts := mqtt.NewClientOptions().AddBroker(\"tcp://{host}:{port}\")\nopts.SetDefaultPublishHandler(func(c mqtt.Client, m mqtt.Message) {\n    fmt.Printf(\"Topic: %s\\nPayload: %s\\n\", m.Topic(), m.Payload())\n})\nclient := mqtt.NewClient(opts)\nclient.Connect()\nclient.Subscribe(\"protoforge/#\", 0, nil)",
        },
    },
    "http": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 HTTP REST API，你的应用发送 HTTP 请求获取/写入仿真数据",
        "connect_hint": "在你的应用中，API 基础地址填写：",
        "code_examples": {
            "python": "# requests 示例 — HTTP REST 客户端\nimport requests\n\nbase_url = 'http://{host}:{port}{api_prefix}'\n\n# GET 读取设备所有测点\nresp = requests.get(f'{base_url}/devices/{{device_id}}/points')\nfor point in resp.json():\n    print(f'{point[\"name\"]}: {point[\"value\"]}')\n\n# POST 写入指定测点\nrequests.post(f'{base_url}/devices/{{device_id}}/points/temperature', json={{'value': 25.5}})",
            "csharp": "// HttpClient 示例 — HTTP REST 客户端\nusing System.Net.Http.Json;\n\nvar http = new HttpClient {{ BaseAddress = new Uri(\"http://{host}:{port}{api_prefix}\") }};\n\n// GET 读取设备所有测点\nvar points = await http.GetFromJsonAsync<List<Point>>(\"/devices/device-001/points\");\nforeach (var p in points) Console.WriteLine($\"{{p.Name}}: {{p.Value}}\");\n\n// POST 写入指定测点\nawait http.PostAsJsonAsync(\"/devices/device-001/points/temperature\", new {{ value = 25.5 }});",
            "java": "// OkHttp 示例 — HTTP REST 客户端\nimport okhttp3.*;\nimport com.google.gson.*;\n\nOkHttpClient client = new OkHttpClient();\nString baseUrl = \"http://{host}:{port}{api_prefix}\";\n\n// GET 读取设备所有测点\nRequest req = new Request.Builder().url(baseUrl + \"/devices/device-001/points\").build();\nResponse resp = client.newCall(req).execute();\nSystem.out.println(resp.body().string());",
            "go": "// net/http 示例 — HTTP REST 客户端\nimport \"net/http\"\n\nbaseUrl := \"http://{host}:{port}{api_prefix}\"\n\n// GET 读取设备所有测点\nresp, _ := http.Get(baseUrl + \"/devices/device-001/points\")\nbody, _ := io.ReadAll(resp.Body)\nfmt.Println(string(body))",
        },
    },
    "gb28181": {
        "mode": "client",
        "mode_label": "客户端注册(模拟IPC/NVR)",
        "mode_desc": "ProtoForge 模拟国标摄像头/NVR设备，主动向上级视频平台发起SIP注册，支持实时视频推流(RTP/PS)",
        "connect_hint": "ProtoForge 会向你配置的国标平台发起 SIP REGISTER，你的平台需要：",
        "code_examples": {
            "python": "# 国标视频平台配置要求\n# 1. 开放 SIP 信令端口(默认5060)\n# 2. 配置 SIP 服务器ID: {sip_server_id}\n# 3. SIP 域编码: {sip_domain}\n# 4. 设备注册后，平台可发起：\n#    - INVITE: 实时视频请求\n#    - MESSAGE Catalog: 设备目录查询\n#    - MESSAGE Keepalive: 心跳保活\n#    - MESSAGE DeviceControl: 云台控制(PTZ)\n#\n# 设备国标编码: {device_id}\n# 注册周期: {register_interval}秒",
            "csharp": "// 国标视频平台配置要求\n// 1. 开放 SIP 信令端口(默认5060)\n// 2. 配置 SIP 服务器ID: {sip_server_id}\n// 3. SIP 域编码: {sip_domain}\n// 4. 设备注册后，平台可发起：\n//    - INVITE: 实时视频请求\n//    - MESSAGE Catalog: 设备目录查询\n//    - MESSAGE Keepalive: 心跳保活\n//    - MESSAGE DeviceControl: 云台控制(PTZ)\n//\n// 设备国标编码: {device_id}\n// 注册周期: {register_interval}秒",
            "java": "// 国标视频平台配置要求\n// 1. 开放 SIP 信令端口(默认5060)\n// 2. 配置 SIP 服务器ID: {sip_server_id}\n// 3. SIP 域编码: {sip_domain}\n// 4. 设备注册后，平台可发起：\n//    - INVITE: 实时视频请求\n//    - MESSAGE Catalog: 设备目录查询\n//    - MESSAGE Keepalive: 心跳保活\n//    - MESSAGE DeviceControl: 云台控制(PTZ)\n//\n// 设备国标编码: {device_id}\n// 注册周期: {register_interval}秒",
            "go": "// 国标视频平台配置要求\n// 1. 开放 SIP 信令端口(默认5060)\n// 2. 配置 SIP 服务器ID: {sip_server_id}\n// 3. SIP 域编码: {sip_domain}\n// 4. 设备注册后，平台可发起：\n//    - INVITE: 实时视频请求\n//    - MESSAGE Catalog: 设备目录查询\n//    - MESSAGE Keepalive: 心跳保活\n//    - MESSAGE DeviceControl: 云台控制(PTZ)\n//\n// 设备国标编码: {device_id}\n// 注册周期: {register_interval}秒",
        },
    },
    "bacnet": {
        "mode": "server",
        "mode_label": "服务端模拟",
        "mode_desc": "ProtoForge 模拟 BACnet/IP 设备，你的应用作为 BACnet 客户端读写对象属性",
        "connect_hint": "在你的 BACnet 客户端中，设备地址填写：",
        "code_examples": {
            "python": "# BAC0 示例 — BACnet 客户端\nimport BAC0\n\nbacnet = BAC0.lite()\nname = bacnet.read('{host} device {device_id} objectName')\nvalue = bacnet.read('{host} analogInput 1 presentValue')\nbacnet.write('{host} analogOutput 1 presentValue 75.0')",
            "csharp": "// BACnet 示例 — 使用 BACnet/IP 通信\nusing System.Net;\nusing System.Net.Sockets;\n\nvar udp = new UdpClient();\nudp.Connect(IPAddress.Parse(\"{host}\"), 47808);\n\n// 构建 BACnet ReadProperty 请求\n// 对象: device {device_id}, 属性: objectName\n// 对象: analogInput 1, 属性: presentValue\nConsole.WriteLine(\"发送 BACnet 读请求...\");",
            "java": "// BACnet4J 示例 — BACnet 客户端\nimport com.serotonin.bacnet4j.*;\n\nLocalDevice local = new LocalDevice(1234, \"0.0.0.0\");\nlocal.initialize();\n\nRemoteDevice d = local.findRemoteDevice(new Address(new UnsignedInteger({device_id})), 1234);\n// 读取 analogInput 1 presentValue\nPropertyIdentifier pid = PropertyIdentifier.presentValue;",
            "go": "// bacnet 示例 — BACnet 客户端\n// 设备地址: {host}:{port}\n// 设备ID: {device_id}\n// 读取 analogInput 1 presentValue\n// 写入 analogOutput 1 presentValue = 75.0",
        },
    },
    "s7": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟西门子 S7 PLC，你的应用作为 S7 客户端连接，读写DB/I/Q/M区数据",
        "connect_hint": "在你的 S7 通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# python-snap7 示例 — S7 客户端\nimport snap7\nfrom snap7.util import get_real, set_real\n\nclient = snap7.client.Client()\nclient.connect('{host}', {rack}, {slot}, {port})\n\ndata = client.db_read(db_number=1, start=0, size=4)\nvalue = get_real(data, 0)\nprint(f'DB1.DBD0 = {value}')\n\nset_real(data, 0, 25.5)\nclient.db_write(db_number=1, start=0, data=data)",
            "csharp": "// S7.Net 示例 — S7 客户端\nusing S7.Net;\n\nusing var plc = new Plc(CpuType.S71200, \"{host}\", {rack}, {slot});\nplc.Open();\n\n// 读取 DB1.DBD0 (浮点数)\nvar value = (float)plc.Read(\"DB1.DBD0\");\nConsole.WriteLine($\"DB1.DBD0 = {{value}}\");\n\n// 写入 DB1.DBD0\nplc.Write(\"DB1.DBD0\", 25.5f);",
            "java": "// S7Connector 示例 — S7 客户端\nimport de.re.easymodbus.modbusclient.*;\n\nS7Client client = new S7Client();\nclient.ConnectTo(\"{host}\", {rack}, {slot});\n\n// 读取 DB1.DBD0\nbyte[] buffer = new byte[4];\nclient.DBRead(1, 0, 4, buffer);\nfloat value = ByteBuffer.wrap(buffer).getFloat();\nSystem.out.println(\"DB1.DBD0 = \" + value);",
            "go": "// s7comm 示例 — S7 客户端\nimport \"github.com/robinson/gos7\"\n\nclient := gos7.NewTCPClient(\"{host}:{port}\")\nclient.Connect()\n\n// 读取 DB1.DBD0\ndata := make([]byte, 4)\nclient.DBRead(1, 0, 4, data)\nvalue := gos7.GetReal(data, 0)\nfmt.Printf(\"DB1.DBD0 = %v\\n\", value)",
        },
    },
    "mc": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟三菱 PLC，你的应用通过 SLMP(Binary/ASCII) 协议连接，读写D/R/X/Y/M设备",
        "connect_hint": "在你的 MC/SLMP 通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# pymcprotocol 示例 — SLMP客户端\nfrom pymcprotocol import Type3E\n\nclient = Type3E()\nclient.connect('{host}', {port})\n\nwords = client.batch_read_word_units(head_device='D100', device_number=10)\nclient.batch_write_word_units(head_device='D100', write_values=[100, 200, 300])",
            "csharp": "// MC协议 示例 — SLMP客户端\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// SLMP Binary 帧读取 D100 开始10个字\nbyte[] frame = BuildSLMPReadFrame(\"D100\", 10);\nstream.Write(frame, 0, frame.Length);",
            "java": "// MC协议 示例 — SLMP客户端\nimport java.net.Socket;\n\nSocket socket = new Socket(\"{host}\", {port});\nOutputStream out = socket.getOutputStream();\n\n// SLMP Binary 帧读取 D100 开始10个字\nbyte[] frame = buildSLMPReadFrame(\"D100\", 10);\nout.write(frame);",
            "go": "// mcprotocol 示例 — SLMP客户端\nimport \"github.com/taka-wang/gomc\"\n\nclient := gomc.NewTCPClient(\"{host}:{port}\")\nclient.Connect()\n\n// 批量读取 D100 开始10个字\nwords, _ := client.ReadWords(\"D100\", 10)\nfmt.Printf(\"D100-D109: %v\\n\", words)",
        },
    },
    "fins": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟欧姆龙 PLC，你的应用通过 FINS TCP 协议连接，读写CIO/DM/WR/HR内存区域",
        "connect_hint": "在你的 FINS 通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# pyfins 示例 — FINS TCP 客户端\nfrom pyfins import FinsClient\n\nclient = FinsClient('{host}', {port})\nvalues = client.memory_area_read(memory_area=0x82, start_address=0, count=10)\nclient.memory_area_write(memory_area=0x82, start_address=0, data=[100, 200, 300])",
            "csharp": "// FINS TCP 示例\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// FINS 命令: 读取 DM 区(DM0, 10个字)\nbyte[] finsFrame = BuildFinsReadFrame(0x82, 0, 10);\nstream.Write(finsFrame, 0, finsFrame.Length);",
            "java": "// FINS TCP 示例\nimport java.net.Socket;\n\nSocket socket = new Socket(\"{host}\", {port});\n// FINS 命令: 读取 DM 区\nbyte[] finsFrame = buildFinsReadFrame(0x82, 0, 10);\nsocket.getOutputStream().write(finsFrame);",
            "go": "// fins 示例 — FINS TCP 客户端\n// 连接: {host}:{port}\n// 读取 DM 区(DM0开始, 10个字)\n// memory_area=0x82, start=0, count=10",
        },
    },
    "ab": {
        "mode": "server",
        "mode_label": "服务端模拟(PLC)",
        "mode_desc": "ProtoForge 模拟罗克韦尔 PLC，你的应用通过 EtherNet/IP(CIP) 协议连接，读写Tag标签",
        "connect_hint": "在你的 EtherNet/IP 通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# pylogix 示例 — EtherNet/IP 客户端\nfrom pylogix import PLC\n\nwith PLC() as comm:\n    comm.IPAddress = '{host}'\n    comm.ProcessorSlot = {slot}\n    ret = comm.Read('Temperature')\n    print(f'Temperature = {ret.Value}')\n    comm.Write('Temperature', 25.5)",
            "csharp": "// libplctag 示例 — EtherNet/IP 客户端\nusing libplctag;\n\nvar tag = new Tag<FloatPlcMapper, float>()\n{\n    Name = \"Temperature\",\n    Gateway = \"{host}\",\n    Path = \"1,{slot}\",\n    Timeout = TimeSpan.FromSeconds(5)\n};\ntag.Initialize();\nfloat value = tag.Read();\nConsole.WriteLine($\"Temperature = {{value}}\");\ntag.Write(25.5f);",
            "java": "// libplctag4j 示例 — EtherNet/IP 客户端\nimport org.libplctag.*;\n\nTag tag = new Tag(\"protocol=ab_eip&gateway={host}&path=1,{slot}&elemType=REAL&name=Temperature\");\ntag.read();\nfloat value = tag.getFloat(0);\nSystem.out.println(\"Temperature = \" + value);",
            "go": "// goethernet 示例 — EtherNet/IP 客户端\n// 连接: {host}, Slot: {slot}\n// 读取标签: Temperature\n// 写入标签: Temperature = 25.5",
        },
    },
    "opcda": {
        "mode": "server",
        "mode_label": "服务端模拟(Windows COM)",
        "mode_desc": "ProtoForge 模拟 OPC-DA 服务器(Windows COM组件)，你的应用作为OPC客户端通过COM接口读写标签",
        "connect_hint": "在你的 OPC-DA 客户端中，ProgID 填写：",
        "code_examples": {
            "python": "# OpenOPC 示例 — OPC-DA 客户端(仅Windows)\nimport OpenOPC\n\nopc = OpenOPC.client()\nopc.connect('{prog_id}')\nvalue = opc.read('protoforge.temperature')\nopc.write(('protoforge.temperature', 25.5))",
            "csharp": "// OPC-DA 示例 — 使用 COM 互操作\nusing OPCAutomation;\n\nvar server = new OPCServer();\nserver.Connect(\"{prog_id}\");\nvar group = server.OPCGroups.Add(\"Group1\");\ngroup.OPCItems.AddItem(\"protoforge.temperature\", 1);\n\n// 同步读取\nobject values, errors, qualities, timestamps;\ngroup.SyncRead(2, 1, out values, out errors, out qualities, out timestamps);",
            "java": "// OPC-DA 示例 — 使用 OPC Foundation Java SDK\n// 需要通过 JNI 或 COM Bridge 连接\n// ProgID: {prog_id}\n// 读取标签: protoforge.temperature\n// 写入标签: protoforge.temperature = 25.5",
            "go": "// OPC-DA 示例 (仅Windows)\n// 需要通过 COM 接口访问\n// ProgID: {prog_id}\n// 读取标签: protoforge.temperature",
        },
    },
    "fanuc": {
        "mode": "server",
        "mode_label": "服务端模拟(CNC)",
        "mode_desc": "ProtoForge 模拟 FANUC CNC 数控系统，你的应用通过 FOCAS2 库连接，读取坐标/状态/参数",
        "connect_hint": "在你的 FOCAS2 通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# FOCAS2 示例 — FANUC CNC 客户端\n# 需要: Fwlib32.dll\n# 连接: {host}:{port}\n# cnc_statinfo() -> 运行状态、主轴转速、进给率\n# cnc_rdaxis() -> 各轴坐标\n# cnc_rdparam() -> CNC参数读写\n# cnc_alarm() -> 报警信息",
            "csharp": "// FOCAS2 示例 — FANUC CNC 客户端\n// 需要: Fwlib32.dll\n// 连接: {host}:{port}\n// cnc_statinfo() -> 运行状态、主轴转速\n// cnc_rdaxis() -> 各轴坐标\n// cnc_rdparam() -> CNC参数读写\n// cnc_alarm() -> 报警信息",
            "java": "// FOCAS2 示例 — FANUC CNC 客户端\n// 需要: Fwlib32.dll (通过 JNI)\n// 连接: {host}:{port}\n// cnc_statinfo() -> 运行状态\n// cnc_rdaxis() -> 各轴坐标\n// cnc_alarm() -> 报警信息",
            "go": "// FOCAS2 示例 — FANUC CNC 客户端\n// 需要: Fwlib32.dll (通过 CGO)\n// 连接: {host}:{port}\n// cnc_statinfo() -> 运行状态\n// cnc_rdaxis() -> 各轴坐标",
        },
    },
    "mtconnect": {
        "mode": "server",
        "mode_label": "服务端模拟(Agent)",
        "mode_desc": "ProtoForge 模拟 MTConnect Agent，你的应用通过 HTTP 请求获取设备数据(XML格式)",
        "connect_hint": "在你的 MTConnect 客户端中，Agent 地址填写：",
        "code_examples": {
            "python": "# MTConnect HTTP 客户端\nimport requests\n\nbase = 'http://{host}:{port}'\nresp = requests.get(f'{base}/current')\nprint(resp.text)",
            "csharp": "// MTConnect HTTP 客户端\nusing var http = new HttpClient {{ BaseAddress = new Uri(\"http://{host}:{port}\") }};\n\nvar current = await http.GetStringAsync(\"/current\");\nConsole.WriteLine(current);\n\nvar probe = await http.GetStringAsync(\"/probe\");\nConsole.WriteLine(probe);",
            "java": "// MTConnect HTTP 客户端\nimport java.net.http.*;\n\nHttpClient client = HttpClient.newHttpClient();\nHttpRequest req = HttpRequest.newBuilder()\n    .uri(URI.create(\"http://{host}:{port}/current\"))\n    .build();\nString body = client.send(req, HttpResponse.BodyHandlers.ofString()).body();\nSystem.out.println(body);",
            "go": "// MTConnect HTTP 客户端\nimport \"net/http\"\n\nresp, _ := http.Get(\"http://{host}:{port}/current\")\nbody, _ := io.ReadAll(resp.Body)\nfmt.Println(string(body))",
        },
    },
    "toledo": {
        "mode": "server",
        "mode_label": "服务端模拟(称重仪表)",
        "mode_desc": "ProtoForge 模拟梅特勒-托利多称重仪表，你的应用通过TCP/串口发送SI/S命令读取重量数据",
        "connect_hint": "在你的称重通信程序中，连接参数填写：",
        "code_examples": {
            "python": "# Toledo TCP 客户端\nimport socket\n\nsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\nsock.connect(('{host}', {port}))\nsock.sendall(b'SI\\r\\n')\nresponse = sock.recv(1024)\nprint(response.decode())",
            "csharp": "// Toledo TCP 客户端\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// SI命令: 读取稳定重量\nvar cmd = Encoding.ASCII.GetBytes(\"SI\\r\\n\");\nstream.Write(cmd, 0, cmd.Length);\nvar buf = new byte[1024];\nint n = stream.Read(buf, 0, buf.Length);\nConsole.WriteLine(Encoding.ASCII.GetString(buf, 0, n));",
            "java": "// Toledo TCP 客户端\nimport java.net.Socket;\n\nSocket sock = new Socket(\"{host}\", {port});\nOutputStream out = sock.getOutputStream();\nBufferedReader in = new BufferedReader(new InputStreamReader(sock.getInputStream()));\n\nout.write(\"SI\\r\\n\".getBytes());\nString response = in.readLine();\nSystem.out.println(response);",
            "go": "// Toledo TCP 客户端\nimport \"net\"\n\nconn, _ := net.Dial(\"tcp\", \"{host}:{port}\")\nconn.Write([]byte(\"SI\\r\\n\"))\nbuf := make([]byte, 1024)\nn, _ := conn.Read(buf)\nfmt.Println(string(buf[:n]))",
        },
    },
    "profinet": {
        "mode": "server",
        "mode_label": "服务端模拟(IO Device)",
        "mode_desc": "ProtoForge 模拟 PROFINET IO Device(从站)，你的 IO Controller(主站)通过DCP发现并建立连接，交换循环数据",
        "connect_hint": "在你的 PROFINET IO Controller 配置中，添加设备并填写：",
        "code_examples": {
            "python": "# profinet-py 示例 — PROFINET IO Controller\nfrom profinet import ProfinetIOController\n\ncontroller = ProfinetIOController('{device_name}')\ncontroller.connect('{host}', {port})\ndevice = controller.dcp_identify('{device_name}')\ninput_data = controller.read_cyclic_data()",
            "csharp": "// PROFINET 示例 — 使用 PROFINET SDK\n// 设备名: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// 配置 GSDML 文件后建立连接\n// 读写循环数据",
            "java": "// PROFINET 示例\n// 设备名: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// 配置 GSDML 文件后建立连接",
            "go": "// PROFINET 示例\n// 设备名: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// 配置 GSDML 文件后建立连接",
        },
    },
    "ethercat": {
        "mode": "server",
        "mode_label": "服务端模拟(Slave)",
        "mode_desc": "ProtoForge 模拟 EtherCAT 从站(Slave)，你的 EtherCAT Master 连接后可读写PDO过程数据和SDO服务数据",
        "connect_hint": "在你的 EtherCAT Master 程序中，配置从站参数：",
        "code_examples": {
            "python": "# pysoem 示例 — EtherCAT Master\nimport pysoem\n\nmaster = pysoem.Master()\nmaster.open('{host}')\nslave_count = master.config_init()\n\nif slave_count > 0:\n    slave = master.slaves[0]\n    master.state = pysoem.OP_STATE\n    master.write_state()\n    master.send_processdata()\n    master.receive_processdata(5000)",
            "csharp": "// SOEM.NET 示例 — EtherCAT Master\nusing SOEM;\n\nvar master = new Master();\nmaster.Open(\"{host}\");\nint slaveCount = master.ConfigInit();\n\nif (slaveCount > 0)\n{\n    master.State = OpState.OP;\n    master.WriteState();\n    master.SendProcessData();\n    master.ReceiveProcessData(5000);\n}",
            "java": "// EtherCAT 示例\n// 使用 SOEM JNI 绑定\n// 连接: {host}\n// 扫描从站 → PRE-OP → SAFE-OP → OP\n// 读写 PDO 过程数据",
            "go": "// ethercat 示例 — EtherCAT Master\n// 使用 SOEM CGO 绑定\n// 连接: {host}\n// 扫描从站 → PRE-OP → SAFE-OP → OP\n// 读写 PDO 过程数据",
        },
    },
}

for _proto_name, _proto_usage in PROTOCOL_USAGE.items():
    if "code_examples" in _proto_usage and "code_example" not in _proto_usage:
        _proto_usage["code_example"] = _proto_usage["code_examples"].get("python", "")

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
