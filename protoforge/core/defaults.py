PROTOCOL_DEFAULTS = {
    "modbus_tcp": {"host": "0.0.0.0", "port": 5020, "display_name": "Modbus TCP", "description": "工业Modbus TCP协议，常用于PLC、传感器通信"},
    "modbus_rtu": {"host": "/dev/ttyUSB0", "baudrate": 9600, "display_name": "Modbus RTU", "description": "串口Modbus RTU协议，常用于RS485设备"},
    "opcua": {"host": "0.0.0.0", "port": 4840, "display_name": "OPC-UA", "description": "OPC统一架构协议，常用于工业4.0设备互联"},
    "mqtt": {"host": "0.0.0.0", "port": 1883, "display_name": "MQTT", "description": "物联网消息协议，常用于IoT设备上报"},
    "http": {"host": "0.0.0.0", "port": 8080, "display_name": "HTTP REST", "description": "HTTP RESTful API模拟，常用于Web API测试"},
    "gb28181": {"host": "0.0.0.0", "port": 5060, "sip_domain": "protoforge.local", "display_name": "GB28181", "description": "国标视频监控协议，常用于摄像头/NVR对接"},
    "bacnet": {"host": "0.0.0.0", "port": 47808, "display_name": "BACnet", "description": "楼宇自动化协议，常用于空调/照明控制"},
    "s7": {"host": "0.0.0.0", "port": 102, "rack": 0, "slot": 1, "display_name": "Siemens S7", "description": "西门子S7协议，常用于S7-1200/1500 PLC"},
    "mc": {"host": "0.0.0.0", "port": 5000, "network": 0, "station": 0, "pc": 255, "display_name": "Mitsubishi MC", "description": "三菱MC协议(SLMP)，常用于FX/Q/L系列PLC"},
    "fins": {"host": "0.0.0.0", "port": 9600, "display_name": "Omron FINS", "description": "欧姆龙FINS协议，常用于CJ/CP/NJ系列PLC"},
    "ab": {"host": "0.0.0.0", "port": 44818, "display_name": "Rockwell AB", "description": "罗克韦尔EtherNet/IP(CIP)，常用于ControlLogix/CompactLogix"},
    "opcda": {"host": "0.0.0.0", "port": 51340, "display_name": "OPC-DA", "description": "OPC数据访问协议(经典)，常用于传统SCADA/DCS系统"},
    "fanuc": {"host": "0.0.0.0", "port": 8193, "display_name": "FANUC FOCAS", "description": "FANUC数控系统FOCAS协议，常用于CNC数据采集"},
    "mtconnect": {"host": "0.0.0.0", "port": 7878, "display_name": "MTConnect", "description": "MTConnect标准协议，常用于机床数据互联"},
    "toledo": {"host": "0.0.0.0", "port": 1701, "display_name": "Mettler-Toledo", "description": "梅特勒-托利多称重协议，常用于电子秤/衡器"},
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
        })
    return result
