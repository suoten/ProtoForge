PROTOCOL_DEFAULTS = {
    "modbus_tcp": {
        "host": "0.0.0.0", "port": 5020,
        "display_name": "Modbus TCP",
        "description": "Modbus TCP/IP Protocol - The most widely used communication protocol in industrial automation, TCP-based, master-slave architecture, function codes 01-06 covering coil/register read/write",
        "icon": "🔌",
    },
    "modbus_rtu": {
        "host": "/dev/ttyUSB0", "baudrate": 9600,
        "display_name": "Modbus RTU",
        "description": "Modbus RTU Protocol - RS-485 serial bus industrial communication protocol, binary frame format, CRC16 checksum, suitable for long-distance, high-interference industrial environments",
        "icon": "🔌",
    },
    "opcua": {
        "host": "0.0.0.0", "port": 4840,
        "display_name": "OPC UA",
        "description": "OPC Unified Architecture (OPC UA) - Industry 4.0 standard interconnection protocol, object-oriented information model, supports security certificate authentication and encrypted communication, cross-platform interoperability",
        "icon": "🌐",
    },
    "opcua_client": {
        "endpoint": "opc.tcp://localhost:4840",
        "request_timeout": 10.0,
        "session_timeout": 3600000,
        "reconnect_interval": 5.0,
        "max_reconnect_attempts": 0,
        "display_name": "OPC-UA Client",
        "description": "OPC-UA Client Mode - Connect to external OPC-UA servers, read/write node data, supports automatic reconnection on disconnect",
        "icon": "🔗",
    },
    "mqtt": {
        "host": "0.0.0.0", "port": 1883,
        "display_name": "MQTT",
        "description": "MQTT Message Queuing Telemetry Transport - Mainstream lightweight pub/sub protocol in IoT, QoS three-level guarantee, suitable for low-bandwidth, high-latency network environments",
        "icon": "📡",
    },
    "http": {
        "host": "0.0.0.0", "port": 8080,
        "display_name": "HTTP REST",
        "description": "HTTP RESTful API - HTTP-based REST interface simulation, supports GET/POST/PUT/DELETE methods, JSON data format, suitable for Web API integration and testing",
        "icon": "🔗",
    },
    "gb28181": {
        "host": "0.0.0.0", "port": 5060, "sip_domain": "3402000000",
        "display_name": "GB/T 28181",
        "description": "GB/T 28181 National Standard Video Surveillance Interconnection Protocol - SIP/RTP-based video surveillance device interconnection standard, supports device registration, live video, PTZ control, video playback",
        "icon": "📹",
    },
    "bacnet": {
        "host": "0.0.0.0", "port": 47808,
        "display_name": "BACnet/IP",
        "description": "BACnet/IP Building Automation Protocol - ASHRAE 135 standard, for HVAC, lighting, security and other building equipment interconnection, object model driven",
        "icon": "🏢",
    },
    "s7": {
        "host": "0.0.0.0", "port": 102, "rack": 0, "slot": 1,
        "display_name": "Siemens S7",
        "description": "Siemens S7 Communication Protocol - S7-1200/1500/300/400 PLC native protocol, based on ISO-on-TCP (RFC 1006), supports DB/DBX/DBW/DBD addressing",
        "icon": "⚙️",
    },
    "mc": {
        "host": "0.0.0.0", "port": 5000, "network": 0, "station": 0, "pc": 255,
        "display_name": "Mitsubishi MC",
        "description": "Mitsubishi MC Protocol (SLMP) - Mitsubishi FX/Q/L/iQ-R series PLC Ethernet communication protocol, supports bit/word/block read/write, binary/ASCII frame format",
        "icon": "⚙️",
    },
    "fins": {
        "host": "0.0.0.0", "port": 9600,
        "display_name": "Omron FINS",
        "description": "Omron FINS Factory Automation Network Protocol - CJ/CP/NJ/NX series PLC communication protocol, supports CIO/DM/WR memory area direct access",
        "icon": "⚙️",
    },
    "ab": {
        "host": "0.0.0.0", "port": 44818,
        "display_name": "Rockwell AB",
        "description": "Rockwell EtherNet/IP (CIP) - ControlLogix/CompactLogix PLC communication protocol, based on CIP Common Industrial Protocol, supports Tag read/write and explicit messaging",
        "icon": "⚙️",
    },
    "opcda": {
        "host": "0.0.0.0", "port": 51340,
        "display_name": "OPC-DA",
        "description": "OPC Data Access Classic Protocol - COM/DCOM-based OPC DA 2.0/3.0, traditional SCADA/DCS system standard data interface, Windows platform only",
        "icon": "🖥️",
    },
    "fanuc": {
        "host": "0.0.0.0", "port": 8193,
        "display_name": "FANUC FOCAS",
        "description": "FANUC FOCAS2 CNC System Communication Library - 0i/16i/18i/21i/30i/31i/32i series CNC data acquisition protocol, supports coordinate/status/parameter/program read/write",
        "icon": "🔧",
    },
    "mtconnect": {
        "host": "0.0.0.0", "port": 7878,
        "display_name": "MTConnect",
        "description": "MTConnect Machine Tool Interconnection Standard - Open standard developed by AMT, HTTP/XML-based device data acquisition, supports probe/current/sample requests",
        "icon": "🏭",
    },
    "toledo": {
        "host": "0.0.0.0", "port": 1701,
        "display_name": "Mettler-Toledo",
        "description": "Mettler-Toledo Weighing Communication Protocol - IND/JAG/XPR series weighing instrument standard protocol, supports SI/S/SIR command set, stable/gross/net/tare",
        "icon": "⚖️",
    },
    "profinet": {
        "host": "0.0.0.0", "port": 34964,
        "display_name": "PROFINET IO",
        "description": "PROFINET IO Real-time Industrial Ethernet Protocol - PI organization standard, Ethernet-based real-time communication, supports DCP discovery/configuration, RT/IRT cyclic data exchange, GSD device description",
        "icon": "🏭",
    },
    "ethercat": {
        "host": "0.0.0.0", "port": 34980,
        "display_name": "EtherCAT",
        "description": "EtherCAT Real-time Industrial Ethernet Protocol - Developed by Beckhoff, based on \"On-the-fly\" processing technology, extremely low latency distributed clock synchronization, widely used in motion control",
        "icon": "⚡",
    },
}

PROTOCOL_DEVICE_CONFIG = {
    "modbus_tcp": [
        {"key": "slave_id", "label": "Slave Address (Unit ID)", "type": "number", "default": 1, "min": 1, "max": 247, "description": "Modbus slave address, i.e. Unit ID in function codes (1-247)"},
    ],
    "modbus_rtu": [
        {"key": "slave_id", "label": "Slave Address (Unit ID)", "type": "number", "default": 1, "min": 1, "max": 247, "description": "Modbus slave address"},
        {"key": "baudrate", "label": "Baud Rate", "type": "select", "default": 9600, "options": [2400, 4800, 9600, 19200, 38400, 57600, 115200], "description": "Serial communication baud rate (bps)"},
        {"key": "parity", "label": "Parity", "type": "select", "default": "none", "options": ["none", "even", "odd"], "description": "Serial parity (N=None E=Even O=Odd)"},
        {"key": "stopbits", "label": "Stop Bits", "type": "select", "default": 1, "options": [1, 2], "description": "Serial stop bits"},
    ],
    "opcua": [
        {"key": "server_name", "label": "Server Application Name", "type": "string", "default": "ProtoForge OPC-UA Server", "description": "OPC-UA server ApplicationName, used for discovery service"},
        {"key": "namespace", "label": "Namespace URI", "type": "string", "default": "urn:protoforge:simulation", "description": "Node namespace URI, clients access nodes via ns index"},
        {"key": "security_mode", "label": "Security Mode", "type": "select", "default": "None", "options": ["None", "Sign", "SignAndEncrypt"], "description": "OPC-UA security mode (None=No encryption Sign=Signature SignAndEncrypt=Signature+Encryption)"},
    ],
    "opcua_client": [
        {"key": "namespace", "label": "Namespace URI", "type": "string", "default": "urn:protoforge:simulation", "description": "Target server node namespace URI"},
        {"key": "security_mode", "label": "Security Mode", "type": "select", "default": "None", "options": ["None", "Sign", "SignAndEncrypt"], "description": "OPC-UA client security mode"},
    ],
    "mqtt": [
        {"key": "topic_prefix", "label": "Topic Prefix", "type": "string", "default": "protoforge", "description": "MQTT publish topic prefix, format: {prefix}/{device_id}/{point_name}"},
        {"key": "qos", "label": "QoS Level", "type": "select", "default": 0, "options": [0, 1, 2], "description": "Message quality of service (0=At most once 1=At least once 2=Exactly once)"},
        {"key": "username", "label": "Username", "type": "string", "default": "", "description": "MQTT Broker authentication username (optional)"},
        {"key": "password", "label": "Password", "type": "string", "default": "", "description": "MQTT Broker authentication password (optional)"},
    ],
    "http": [
        {"key": "api_prefix", "label": "API Path Prefix", "type": "string", "default": "/api/v1", "description": "RESTful API path prefix, e.g. /api/v1"},
    ],
    "gb28181": [
        {"key": "sip_server_id", "label": "Upstream SIP Server ID", "type": "string", "default": "34020000002000000001", "description": "National standard upstream platform 20-digit code (center code 8 digits + industry code 2 digits + type code 3 digits + network ID 7 digits)"},
        {"key": "sip_domain", "label": "SIP Domain Code", "type": "string", "default": "3402000000", "description": "SIP server domain code (10-digit administrative division code)"},
        {"key": "sip_server_addr", "label": "Upstream SIP Server Address", "type": "string", "default": "", "description": "Upstream video platform SIP server IP address (must be set before starting)"},
        {"key": "sip_server_port", "label": "Upstream SIP Port", "type": "number", "default": 5060, "min": 1, "max": 65535, "description": "Upstream video platform SIP signaling port (default 5060)"},
        {"key": "device_id", "label": "Device National Standard Code", "type": "string", "default": "34020000001320000001", "description": "This device 20-digit national standard code (center code 8 digits + industry code 2 digits + type code 3 digits + serial 7 digits), type 132=IPC"},
        {"key": "register_interval", "label": "Registration Interval (seconds)", "type": "number", "default": 3600, "min": 60, "max": 86400, "description": "SIP REGISTER interval, national standard recommends 3600 seconds"},
        {"key": "username", "label": "SIP Username", "type": "string", "default": "", "description": "SIP authentication username (leave empty to use device national standard code)"},
        {"key": "password", "label": "SIP Password", "type": "string", "default": "", "description": "SIP Digest authentication password"},
    ],
    "bacnet": [
        {"key": "device_id", "label": "Device Instance Number", "type": "number", "default": 101, "min": 0, "max": 4194303, "description": "BACnet device object instance number (BACnetObjectIdentifier), globally unique"},
        {"key": "device_name", "label": "Device Object Name", "type": "string", "default": "ProtoForge BACnet Device", "description": "BACnet Device object objectName property"},
        {"key": "vendor_id", "label": "Vendor ID", "type": "number", "default": 999, "min": 0, "max": 65535, "description": "BACnet vendorIdentifier (999=unregistered vendor)"},
    ],
    "s7": [
        {"key": "rack", "label": "Rack Number", "type": "number", "default": 0, "min": 0, "max": 7, "description": "S7 PLC rack number (S7-1200/1500 usually 0)"},
        {"key": "slot", "label": "Slot Number", "type": "number", "default": 1, "min": 0, "max": 31, "description": "CPU slot number (S7-1200=1, S7-1500=1, S7-300 depends on actual position)"},
    ],
    "mc": [
        {"key": "network", "label": "Network Number", "type": "number", "default": 0, "min": 0, "max": 255, "description": "SLMP communication network number (0=local network)"},
        {"key": "station", "label": "Station Number", "type": "number", "default": 0, "min": 0, "max": 255, "description": "SLMP communication station number (0=self station)"},
        {"key": "pc", "label": "PC Number", "type": "number", "default": 255, "min": 0, "max": 255, "description": "SLMP communication PC number (0xFF=self PC)"},
    ],
    "fins": [
        {"key": "source_node", "label": "Local FINS Node Number", "type": "number", "default": 0, "min": 0, "max": 254, "description": "FINS local node number (0=auto-assign)"},
        {"key": "dest_node", "label": "Remote FINS Node Number", "type": "number", "default": 1, "min": 0, "max": 254, "description": "FINS remote node number (PLC FINS node address)"},
    ],
    "ab": [
        {"key": "slot", "label": "CPU Slot Number", "type": "number", "default": 0, "min": 0, "max": 17, "description": "ControlLogix/CompactLogix CPU slot number (CompactLogix=0)"},
    ],
    "opcda": [
        {"key": "prog_id", "label": "ProgID", "type": "string", "default": "ProtoForge.SimServer.1", "description": "OPC-DA server ProgID (Windows registry identifier)"},
        {"key": "clsid", "label": "CLSID", "type": "string", "default": "", "description": "OPC-DA server CLSID (optional, leave empty to auto-lookup from ProgID in registry)"},
        {"key": "update_rate", "label": "Update Rate (ms)", "type": "number", "default": 500, "min": 100, "max": 60000, "description": "OPC group refresh cycle (milliseconds)"},
    ],
    "fanuc": [
        {"key": "cnc_type", "label": "CNC System Model", "type": "select", "default": "0i-F", "options": ["0i-F", "0i-F Plus", "31i-B", "31i-A", "16i-B", "18i-B", "0i-MF", "32i"], "description": "FANUC CNC system model, affects available FOCAS2 APIs"},
        {"key": "axis_count", "label": "Controlled Axis Count", "type": "number", "default": 3, "min": 1, "max": 8, "description": "CNC controlled axis count (lathe usually 2-3 axes, machining center 3-5 axes)"},
        {"key": "focas_version", "label": "FOCAS Version", "type": "select", "default": 2, "options": [1, 2], "description": "FOCAS library version (FOCAS1=legacy FOCAS2=current standard)"},
    ],
    "mtconnect": [
        {"key": "device_uuid", "label": "Device UUID", "type": "string", "default": "", "description": "MTConnect device UUID (leave empty to auto-generate, format: 000-000-000)"},
        {"key": "manufacturer", "label": "Device Manufacturer", "type": "string", "default": "ProtoForge", "description": "MTConnect Device element manufacturer attribute"},
        {"key": "mtconnect_version", "label": "MTConnect Version", "type": "select", "default": "1.3.0", "options": ["1.2.0", "1.3.0", "1.4.0", "2.0.0"], "description": "MTConnect protocol version (1.3=most widely used 2.0=supports REST)"},
    ],
    "toledo": [
        {"key": "scale_addr", "label": "Scale Communication Address", "type": "string", "default": "1", "description": "Weighing instrument communication address (address number used in SI/S commands)"},
        {"key": "unit", "label": "Weight Unit", "type": "select", "default": "kg", "options": ["kg", "g", "mg", "lb", "oz", "t", "ct"], "description": "Weight unit (ct=carat)"},
        {"key": "decimal_places", "label": "Decimal Places", "type": "number", "default": 3, "min": 0, "max": 6, "description": "Number of decimal places for weight display"},
    ],
    "profinet": [
        {"key": "device_name", "label": "Device Name (DeviceName)", "type": "string", "default": "protoforge-device", "description": "PROFINET device name, used for DCP identification and addressing (e.g. my-plc-01)"},
        {"key": "vendor_id", "label": "Vendor ID (VendorID)", "type": "number", "default": 266, "min": 0, "max": 65535, "description": "PROFINET vendor identifier (assigned by PI organization)"},
        {"key": "device_id", "label": "Device ID (DeviceID)", "type": "number", "default": 256, "min": 0, "max": 65535, "description": "PROFINET device identifier (identifies device type)"},
    ],
    "ethercat": [
        {"key": "slave_address", "label": "Slave Address", "type": "number", "default": 4097, "min": 1, "max": 65535, "description": "EtherCAT slave address (Station Address), master uses this address to address the slave"},
    ],
}

PROTOCOL_USAGE = {
    "modbus_tcp": {
        "mode": "server",
        "mode_label": "Server Simulation (Slave)",
        "mode_desc": "ProtoForge simulates a Modbus TCP Slave, your application connects as Master to read/write registers",
        "connect_hint": "In your Modbus Master program, fill in the connection parameters:",
        "code_examples": {
            "python": "# pymodbus example - Modbus TCP Master\nfrom pymodbus.client import ModbusTcpClient\n\nclient = ModbusTcpClient('{host}', port={port})\nclient.connect()\n\n# Function code 03: Read holding registers\nresult = client.read_holding_registers(address=0, count=10, slave={slave_id})\nif not result.isError():\n    print('Register values:', result.registers)\n\n# Function code 06: Write single holding register\nclient.write_register(address=0, value=100, slave={slave_id})",
            "csharp": "// NModbus4 example - Modbus TCP Master\nusing NModbus;\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar factory = new ModbusFactory();\nvar master = factory.CreateMaster(tcp);\n\n// Function code 03: Read holding registers\nushort[] registers = await master.ReadHoldingRegistersAsync({slave_id}, 0, 10);\nConsole.WriteLine($\"Register values: {{string.Join(\", \", registers)}}\");\n\n// Function code 06: Write single holding register\nawait master.WriteSingleRegisterAsync({slave_id}, 0, 100);",
            "java": "// modbus4j example - Modbus TCP Master\nimport com.serotonin.modbus4j.ModbusFactory;\nimport com.serotonin.modbus4j.ip.IpParameters;\n\nIpParameters params = new IpParameters();\nparams.setHost(\"{host}\");\nparams.setPort({port});\nModbusMaster master = new ModbusFactory().createTcpMaster(params, false);\nmaster.init();\n\n// Function code 03: Read holding registers\nReadInputRegistersRequest req = new ReadInputRegistersRequest({slave_id}, 0, 10);\nReadInputRegistersResponse res = (ReadInputRegistersResponse) master.send(req);\nSystem.out.println(\"Register values: \" + Arrays.toString(res.getShortData()));",
            "go": "// modbus example - Modbus TCP Master\nimport (\n    \"github.com/goburrow/modbus\"\n)\n\nhandler := modbus.NewTCPClientHandler(\"{host}:{port}\")\nhandler.Connect()\nclient := modbus.NewClient(handler)\n\n// Function code 03: Read holding registers\nresults, _ := client.ReadHoldingRegisters(0, 10)\nfmt.Printf(\"Register values: %v\\n\", results)\n\n// Function code 06: Write single holding register\nclient.WriteSingleRegister(0, 100)",
        },
    },
    "modbus_rtu": {
        "mode": "server",
        "mode_label": "Server Simulation (Slave)",
        "mode_desc": "ProtoForge simulates a Modbus RTU Slave, your application connects as Master via RS-485 serial port",
        "connect_hint": "Configure serial port parameters to connect:",
        "code_examples": {
            "python": "# pymodbus example - Modbus RTU Master\nfrom pymodbus.client import ModbusSerialClient\n\nclient = ModbusSerialClient(\n    port='{host}', baudrate={baudrate},\n    parity='N', stopbits=1, bytesize=8,\n)\nclient.connect()\nresult = client.read_holding_registers(0, 10, slave={slave_id})",
            "csharp": "// NModbus4 example - Modbus RTU Master\nusing NModbus;\nusing System.IO.Ports;\n\nusing var port = new SerialPort(\"{host}\", {baudrate}, Parity.None, 8, StopBits.One);\nport.Open();\nvar factory = new ModbusFactory();\nvar master = factory.CreateRtuMaster(port);\n\nushort[] registers = await master.ReadHoldingRegistersAsync({slave_id}, 0, 10);",
            "java": "// modbus4j example - Modbus RTU Master\nimport com.serotonin.modbus4j.ModbusFactory;\nimport com.serotonin.modbus4j.serial.SerialPort;\n\nModbusMaster master = new ModbusFactory().createRtuMaster(\n    new SerialPortImpl(\"{host}\", {baudrate})\n);\nmaster.init();\nReadInputRegistersResponse res = (ReadInputRegistersResponse)\n    master.send(new ReadInputRegistersRequest({slave_id}, 0, 10));",
            "go": "// modbus example - Modbus RTU Master\nimport \"github.com/goburrow/modbus\"\n\nhandler := modbus.NewRTUClientHandler(\"{host}\")\nhandler.BaudRate = {baudrate}\nhandler.Connect()\nclient := modbus.NewClient(handler)\nresults, _ := client.ReadHoldingRegisters(0, 10)",
        },
    },
    "opcua": {
        "mode": "server",
        "mode_label": "Server Simulation",
        "mode_desc": "ProtoForge simulates an OPC-UA server, your application connects as client to browse nodes and read/write variables",
        "connect_hint": "In your OPC-UA client, fill in the connection endpoint:",
        "code_examples": {
            "python": "# opcua example - OPC-UA Client\nfrom opcua import Client\n\nclient = Client('opc.tcp://{host}:{port}')\nclient.connect()\n\n# Browse address space\nroot = client.get_root_node()\nfor child in root.get_children():\n    print(child.get_browse_name())\n\n# Read variable\nnode = client.get_node('ns=2;s=protoforge.temperature')\nvalue = node.get_value()\nprint(f'Temperature: {value}')\n\n# Write variable\nnode.set_value(25.5)",
            "csharp": "// OPC-UA SDK example - OPC-UA Client\nusing Opc.Ua;\nusing Opc.Ua.Client;\n\nvar endpoint = new EndpointDescription(\"opc.tcp://{host}:{port}\");\nvar session = await Session.Create(\n    new ApplicationConfiguration(),\n    new ConfiguredEndpoint(null, endpoint),\n    true, \"\", 60000, null, null);\n\n// Read node\nvar node = session.ReadNode(new NodeId(\"protoforge.temperature\", 2));\nConsole.WriteLine($\"Temperature: {{node.Value}}\");\n\n// Write node\nsession.WriteNode(new NodeId(\"protoforge.temperature\", 2), 25.5);",
            "java": "// eclipse milo example - OPC-UA Client\nimport org.eclipse.milo.opcua.sdk.client.OpcUaClient;\n\nOpcUaClient client = OpcUaClient.create(\"opc.tcp://{host}:{port}\");\nclient.connect().get();\n\n// Read node\nNodeId nodeId = new NodeId(2, \"protoforge.temperature\");\nDataValue value = client.readValue(0, TimestampsToReturn.Both, nodeId).get();\nSystem.out.println(\"Temperature: \" + value.getValue().getValue());",
            "go": "// opcua example - OPC-UA Client\nimport \"github.com/gopcua/opcua\"\n\nclient, _ := opcua.NewClient(\"opc.tcp://{host}:{port}\")\nclient.Connect(context.Background())\n\n// Read node\nid := opcua.NewStringNodeID(2, \"protoforge.temperature\")\nresp, _ := client.Read(context.Background(), &ua.ReadRequest{\n    NodesToRead: []*ua.ReadValueID{{NodeID: id}},\n})\nfmt.Printf(\"Temperature: %v\\n\", resp.Results[0].Value)",
        },
    },
    "opcua_client": {
        "mode": "client",
        "mode_label": "Client Connection",
        "mode_desc": "ProtoForge connects as an OPC-UA client to an external OPC-UA server, reads/writes node data, supports automatic reconnection on disconnect",
        "connect_hint": "Configure the external OPC-UA server endpoint address:",
        "code_examples": {
            "python": "# ProtoForge OPC-UA Client Mode\n# Start the opcua_client protocol on the Protocol Services page\n# Configure endpoint to the target OPC-UA server address\n# e.g.: opc.tcp://192.168.1.100:4840\n# \n# After starting, create a device and set the point address to the Node ID\n# e.g.: ns=2;s=Temperature\n# ProtoForge will automatically read/write the node",
            "csharp": "// ProtoForge OPC-UA Client Mode\n// Start the opcua_client protocol on the Protocol Services page\n// Configure endpoint to the target OPC-UA server address\n// e.g.: opc.tcp://192.168.1.100:4840\n// \n// After starting, create a device and set the point address to the Node ID\n// e.g.: ns=2;s=Temperature",
            "java": "// ProtoForge OPC-UA Client Mode\n// Start the opcua_client protocol on the Protocol Services page\n// Configure endpoint to the target OPC-UA server address\n// e.g.: opc.tcp://192.168.1.100:4840\n// \n// After starting, create a device and set the point address to the Node ID\n// e.g.: ns=2;s=Temperature",
            "go": "// ProtoForge OPC-UA Client Mode\n// Start the opcua_client protocol on the Protocol Services page\n// Configure endpoint to the target OPC-UA server address\n// e.g.: opc.tcp://192.168.1.100:4840\n// \n// After starting, create a device and set the point address to the Node ID\n// e.g.: ns=2;s=Temperature",
        },
    },
    "mqtt": {
        "mode": "broker",
        "mode_label": "Broker Agent",
        "mode_desc": "ProtoForge built-in MQTT Broker, automatically publishes simulation data to Topics, your application subscribes to receive",
        "connect_hint": "After your MQTT client connects to the ProtoForge Broker, subscribe to the following Topic:",
        "code_examples": {
            "python": "# paho-mqtt example - MQTT Client Subscribe\nimport paho.mqtt.client as mqtt\nimport json\n\ndef on_message(client, userdata, msg):\n    data = json.loads(msg.payload.decode())\n    print(f'Topic: {msg.topic}')\n    print(f'  Value: {data[\"value\"]} {data[\"unit\"]}')\n\nclient = mqtt.Client()\nclient.on_message = on_message\nclient.connect('{host}', {port})\nclient.subscribe('protoforge/#')\nclient.loop_forever()",
            "csharp": "// MQTTnet example - MQTT Client Subscribe\nusing MQTTnet;\nusing MQTTnet.Client;\n\nvar factory = new MqttFactory();\nvar client = factory.CreateMqttClient();\n\nclient.ApplicationMessageReceivedAsync += e =>\n{\n    Console.WriteLine($\"Topic: {{e.ApplicationMessage.Topic}}\");\n    Console.WriteLine($\"Payload: {{e.ApplicationMessage.ConvertPayloadToString()}}\");\n    return Task.CompletedTask;\n};\n\nawait client.ConnectAsync(new MqttClientOptionsBuilder()\n    .WithTcpServer(\"{host}\", {port}).Build());\nawait client.SubscribeAsync(\"protoforge/#\");",
            "java": "// Eclipse Paho example - MQTT Client Subscribe\nimport org.eclipse.paho.client.mqttv3.*;\n\nMqttClient client = new MqttClient(\"tcp://{host}:{port}\", \"subscriber\");\nclient.connect();\nclient.subscribe(\"protoforge/#\", (topic, msg) -> {\n    System.out.println(\"Topic: \" + topic);\n    System.out.println(\"Payload: \" + new String(msg.getPayload()));\n});",
            "go": "// paho.mqtt example - MQTT Client Subscribe\nimport (\n    \"github.com/eclipse/paho.mqtt.golang\"\n)\n\nopts := mqtt.NewClientOptions().AddBroker(\"tcp://{host}:{port}\")\nopts.SetDefaultPublishHandler(func(c mqtt.Client, m mqtt.Message) {\n    fmt.Printf(\"Topic: %s\\nPayload: %s\\n\", m.Topic(), m.Payload())\n})\nclient := mqtt.NewClient(opts)\nclient.Connect()\nclient.Subscribe(\"protoforge/#\", 0, nil)",
        },
    },
    "http": {
        "mode": "server",
        "mode_label": "Server Simulation",
        "mode_desc": "ProtoForge simulates HTTP REST API, your application sends HTTP requests to get/write simulation data",
        "connect_hint": "In your application, fill in the API base address:",
        "code_examples": {
            "python": "# requests example - HTTP REST Client\nimport requests\n\nbase_url = 'http://{host}:{port}{api_prefix}'\n\n# GET Read all device points\nresp = requests.get(f'{base_url}/devices/{{device_id}}/points')\nfor point in resp.json():\n    print(f'{point[\"name\"]}: {point[\"value\"]}')\n\n# POST Write to specified point\nrequests.post(f'{base_url}/devices/{{device_id}}/points/temperature', json={{'value': 25.5}})",
            "csharp": "// HttpClient example - HTTP REST Client\nusing System.Net.Http.Json;\n\nvar http = new HttpClient {{ BaseAddress = new Uri(\"http://{host}:{port}{api_prefix}\") }};\n\n// GET Read all device points\nvar points = await http.GetFromJsonAsync<List<Point>>(\"/devices/device-001/points\");\nforeach (var p in points) Console.WriteLine($\"{{p.Name}}: {{p.Value}}\");\n\n// POST Write to specified point\nawait http.PostAsJsonAsync(\"/devices/device-001/points/temperature\", new {{ value = 25.5 }});",
            "java": "// OkHttp example - HTTP REST Client\nimport okhttp3.*;\nimport com.google.gson.*;\n\nOkHttpClient client = new OkHttpClient();\nString baseUrl = \"http://{host}:{port}{api_prefix}\";\n\n// GET Read all device points\nRequest req = new Request.Builder().url(baseUrl + \"/devices/device-001/points\").build();\nResponse resp = client.newCall(req).execute();\nSystem.out.println(resp.body().string());",
            "go": "// net/http example - HTTP REST Client\nimport \"net/http\"\n\nbaseUrl := \"http://{host}:{port}{api_prefix}\"\n\n// GET Read all device points\nresp, _ := http.Get(baseUrl + \"/devices/device-001/points\")\nbody, _ := io.ReadAll(resp.Body)\nfmt.Println(string(body))",
        },
    },
    "gb28181": {
        "mode": "client",
        "mode_label": "Client Registration (Simulated IPC/NVR)",
        "mode_desc": "ProtoForge simulates a national standard camera/NVR device, actively initiates SIP registration to the upstream video platform, supports live video streaming (RTP/PS)",
        "connect_hint": "ProtoForge will initiate SIP REGISTER to your configured national standard platform, your platform needs:",
        "code_examples": {
            "python": "# National Standard Video Platform Configuration Requirements\n# 1. Open SIP signaling port (default 5060)\n# 2. Configure SIP Server ID: {sip_server_id}\n# 3. SIP Domain Code: {sip_domain}\n# 4. After device registration, the platform can initiate:\n#    - INVITE: Live video request\n#    - MESSAGE Catalog: Device directory query\n#    - MESSAGE Keepalive: Heartbeat keepalive\n#    - MESSAGE DeviceControl: PTZ control\n#\n# Device national standard code: {device_id}\n# Registration interval: {register_interval}s",
            "csharp": "// National Standard Video Platform Configuration Requirements\n// 1. Open SIP signaling port (default 5060)\n// 2. Configure SIP Server ID: {sip_server_id}\n// 3. SIP Domain Code: {sip_domain}\n// 4. After device registration, the platform can initiate:\n//    - INVITE: Live video request\n//    - MESSAGE Catalog: Device directory query\n//    - MESSAGE Keepalive: Heartbeat keepalive\n//    - MESSAGE DeviceControl: PTZ control\n//\n// Device national standard code: {device_id}\n// Registration interval: {register_interval}s",
            "java": "// National Standard Video Platform Configuration Requirements\n// 1. Open SIP signaling port (default 5060)\n// 2. Configure SIP Server ID: {sip_server_id}\n// 3. SIP Domain Code: {sip_domain}\n// 4. After device registration, the platform can initiate:\n//    - INVITE: Live video request\n//    - MESSAGE Catalog: Device directory query\n//    - MESSAGE Keepalive: Heartbeat keepalive\n//    - MESSAGE DeviceControl: PTZ control\n//\n// Device national standard code: {device_id}\n// Registration interval: {register_interval}s",
            "go": "// National Standard Video Platform Configuration Requirements\n// 1. Open SIP signaling port (default 5060)\n// 2. Configure SIP Server ID: {sip_server_id}\n// 3. SIP Domain Code: {sip_domain}\n// 4. After device registration, the platform can initiate:\n//    - INVITE: Live video request\n//    - MESSAGE Catalog: Device directory query\n//    - MESSAGE Keepalive: Heartbeat keepalive\n//    - MESSAGE DeviceControl: PTZ control\n//\n// Device national standard code: {device_id}\n// Registration interval: {register_interval}s",
        },
    },
    "bacnet": {
        "mode": "server",
        "mode_label": "Server Simulation",
        "mode_desc": "ProtoForge simulates a BACnet/IP device, your application connects as BACnet client to read/write object properties",
        "connect_hint": "In your BACnet client, fill in the device address:",
        "code_examples": {
            "python": "# BAC0 example - BACnet Client\nimport BAC0\n\nbacnet = BAC0.lite()\nname = bacnet.read('{host} device {device_id} objectName')\nvalue = bacnet.read('{host} analogInput 1 presentValue')\nbacnet.write('{host} analogOutput 1 presentValue 75.0')",
            "csharp": "// BACnet example - Using BACnet/IP Communication\nusing System.Net;\nusing System.Net.Sockets;\n\nvar udp = new UdpClient();\nudp.Connect(IPAddress.Parse(\"{host}\"), 47808);\n\n// Build BACnet ReadProperty request\n// Object: device {device_id}, Property: objectName\n// Object: analogInput 1, Property: presentValue\nConsole.WriteLine(\"Sending BACnet read request...\");",
            "java": "// BACnet4J example - BACnet Client\nimport com.serotonin.bacnet4j.*;\n\nLocalDevice local = new LocalDevice(1234, \"0.0.0.0\");\nlocal.initialize();\n\nRemoteDevice d = local.findRemoteDevice(new Address(new UnsignedInteger({device_id})), 1234);\n// Read analogInput 1 presentValue\nPropertyIdentifier pid = PropertyIdentifier.presentValue;",
            "go": "// bacnet example - BACnet Client\n// Device address: {host}:{port}\n// Device ID: {device_id}\n// Read analogInput 1 presentValue\n// Write analogOutput 1 presentValue = 75.0",
        },
    },
    "s7": {
        "mode": "server",
        "mode_label": "Server Simulation (PLC)",
        "mode_desc": "ProtoForge simulates a Siemens S7 PLC, your application connects as S7 client to read/write DB/I/Q/M area data",
        "connect_hint": "In your S7 communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# python-snap7 example - S7 Client\nimport snap7\nfrom snap7.util import get_real, set_real\n\nclient = snap7.client.Client()\nclient.connect('{host}', {rack}, {slot}, {port})\n\ndata = client.db_read(db_number=1, start=0, size=4)\nvalue = get_real(data, 0)\nprint(f'DB1.DBD0 = {value}')\n\nset_real(data, 0, 25.5)\nclient.db_write(db_number=1, start=0, data=data)",
            "csharp": "// S7.Net example - S7 Client\nusing S7.Net;\n\nusing var plc = new Plc(CpuType.S71200, \"{host}\", {rack}, {slot});\nplc.Open();\n\n// Read DB1.DBD0 (float)\nvar value = (float)plc.Read(\"DB1.DBD0\");\nConsole.WriteLine($\"DB1.DBD0 = {{value}}\");\n\n// Write DB1.DBD0\nplc.Write(\"DB1.DBD0\", 25.5f);",
            "java": "// S7Connector example - S7 Client\nimport de.re.easymodbus.modbusclient.*;\n\nS7Client client = new S7Client();\nclient.ConnectTo(\"{host}\", {rack}, {slot});\n\n// Read DB1.DBD0\nbyte[] buffer = new byte[4];\nclient.DBRead(1, 0, 4, buffer);\nfloat value = ByteBuffer.wrap(buffer).getFloat();\nSystem.out.println(\"DB1.DBD0 = \" + value);",
            "go": "// s7comm example - S7 Client\nimport \"github.com/robinson/gos7\"\n\nclient := gos7.NewTCPClient(\"{host}:{port}\")\nclient.Connect()\n\n// Read DB1.DBD0\ndata := make([]byte, 4)\nclient.DBRead(1, 0, 4, data)\nvalue := gos7.GetReal(data, 0)\nfmt.Printf(\"DB1.DBD0 = %v\\n\", value)",
        },
    },
    "mc": {
        "mode": "server",
        "mode_label": "Server Simulation (PLC)",
        "mode_desc": "ProtoForge simulates a Mitsubishi PLC, your application connects via SLMP (Binary/ASCII) protocol to read/write D/R/X/Y/M devices",
        "connect_hint": "In your MC/SLMP communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# pymcprotocol example - SLMP Client\nfrom pymcprotocol import Type3E\n\nclient = Type3E()\nclient.connect('{host}', {port})\n\nwords = client.batch_read_word_units(head_device='D100', device_number=10)\nclient.batch_write_word_units(head_device='D100', write_values=[100, 200, 300])",
            "csharp": "// MC Protocol example - SLMP Client\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// SLMP Binary frame read 10 words starting from D100\nbyte[] frame = BuildSLMPReadFrame(\"D100\", 10);\nstream.Write(frame, 0, frame.Length);",
            "java": "// MC Protocol example - SLMP Client\nimport java.net.Socket;\n\nSocket socket = new Socket(\"{host}\", {port});\nOutputStream out = socket.getOutputStream();\n\n// SLMP Binary frame read 10 words starting from D100\nbyte[] frame = buildSLMPReadFrame(\"D100\", 10);\nout.write(frame);",
            "go": "// mcprotocol example - SLMP Client\nimport \"github.com/taka-wang/gomc\"\n\nclient := gomc.NewTCPClient(\"{host}:{port}\")\nclient.Connect()\n\n// Batch read 10 words starting from D100\nwords, _ := client.ReadWords(\"D100\", 10)\nfmt.Printf(\"D100-D109: %v\\n\", words)",
        },
    },
    "fins": {
        "mode": "server",
        "mode_label": "Server Simulation (PLC)",
        "mode_desc": "ProtoForge simulates an Omron PLC, your application connects via FINS TCP protocol to read/write CIO/DM/WR/HR memory areas",
        "connect_hint": "In your FINS communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# pyfins example - FINS TCP Client\nfrom pyfins import FinsClient\n\nclient = FinsClient('{host}', {port})\nvalues = client.memory_area_read(memory_area=0x82, start_address=0, count=10)\nclient.memory_area_write(memory_area=0x82, start_address=0, data=[100, 200, 300])",
            "csharp": "// FINS TCP example\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// FINS command: Read DM area (DM0, 10 words)\nbyte[] finsFrame = BuildFinsReadFrame(0x82, 0, 10);\nstream.Write(finsFrame, 0, finsFrame.Length);",
            "java": "// FINS TCP example\nimport java.net.Socket;\n\nSocket socket = new Socket(\"{host}\", {port});\n// FINS command: Read DM area\nbyte[] finsFrame = buildFinsReadFrame(0x82, 0, 10);\nsocket.getOutputStream().write(finsFrame);",
            "go": "// fins example - FINS TCP Client\n// Connection: {host}:{port}\n// Read DM area (from DM0, 10 words)\n// memory_area=0x82, start=0, count=10",
        },
    },
    "ab": {
        "mode": "server",
        "mode_label": "Server Simulation (PLC)",
        "mode_desc": "ProtoForge simulates a Rockwell PLC, your application connects via EtherNet/IP (CIP) protocol to read/write Tags",
        "connect_hint": "In your EtherNet/IP communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# pylogix example - EtherNet/IP Client\nfrom pylogix import PLC\n\nwith PLC() as comm:\n    comm.IPAddress = '{host}'\n    comm.ProcessorSlot = {slot}\n    ret = comm.Read('Temperature')\n    print(f'Temperature = {ret.Value}')\n    comm.Write('Temperature', 25.5)",
            "csharp": "// libplctag example - EtherNet/IP Client\nusing libplctag;\n\nvar tag = new Tag<FloatPlcMapper, float>()\n{\n    Name = \"Temperature\",\n    Gateway = \"{host}\",\n    Path = \"1,{slot}\",\n    Timeout = TimeSpan.FromSeconds(5)\n};\ntag.Initialize();\nfloat value = tag.Read();\nConsole.WriteLine($\"Temperature = {{value}}\");\ntag.Write(25.5f);",
            "java": "// libplctag4j example - EtherNet/IP Client\nimport org.libplctag.*;\n\nTag tag = new Tag(\"protocol=ab_eip&gateway={host}&path=1,{slot}&elemType=REAL&name=Temperature\");\ntag.read();\nfloat value = tag.getFloat(0);\nSystem.out.println(\"Temperature = \" + value);",
            "go": "// goethernet example - EtherNet/IP Client\n// Connection: {host}, Slot: {slot}\n// Read tag: Temperature\n// Write tag: Temperature = 25.5",
        },
    },
    "opcda": {
        "mode": "server",
        "mode_label": "Server Simulation (Windows COM)",
        "mode_desc": "ProtoForge simulates an OPC-DA server (Windows COM component), your application connects as OPC client to read/write tags via COM interface",
        "connect_hint": "In your OPC-DA client, fill in the ProgID:",
        "code_examples": {
            "python": "# OpenOPC example - OPC-DA Client (Windows only)\nimport OpenOPC\n\nopc = OpenOPC.client()\nopc.connect('{prog_id}')\nvalue = opc.read('protoforge.temperature')\nopc.write(('protoforge.temperature', 25.5))",
            "csharp": "// OPC-DA example - Using COM Interop\nusing OPCAutomation;\n\nvar server = new OPCServer();\nserver.Connect(\"{prog_id}\");\nvar group = server.OPCGroups.Add(\"Group1\");\ngroup.OPCItems.AddItem(\"protoforge.temperature\", 1);\n\n// Synchronous read\nobject values, errors, qualities, timestamps;\ngroup.SyncRead(2, 1, out values, out errors, out qualities, out timestamps);",
            "java": "// OPC-DA example - Using OPC Foundation Java SDK\n// Requires JNI or COM Bridge connection\n// ProgID: {prog_id}\n// Read tag: protoforge.temperature\n// Write tag: protoforge.temperature = 25.5",
            "go": "// OPC-DA example (Windows only)\n// Requires COM interface access\n// ProgID: {prog_id}\n// Read tag: protoforge.temperature",
        },
    },
    "fanuc": {
        "mode": "server",
        "mode_label": "Server Simulation (CNC)",
        "mode_desc": "ProtoForge simulates a FANUC CNC system, your application connects via FOCAS2 library to read coordinates/status/parameters",
        "connect_hint": "In your FOCAS2 communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# FOCAS2 example - FANUC CNC Client\n# Requires: Fwlib32.dll\n# Connection: {host}:{port}\n# cnc_statinfo() -> Running status, spindle speed, feed rate\n# cnc_rdaxis() -> Axis coordinates\n# cnc_rdparam() -> CNC parameter read/write\n# cnc_alarm() -> Alarm information",
            "csharp": "// FOCAS2 example - FANUC CNC Client\n// Requires: Fwlib32.dll\n// Connection: {host}:{port}\n// cnc_statinfo() -> Running status, spindle speed\n// cnc_rdaxis() -> Axis coordinates\n// cnc_rdparam() -> CNC parameter read/write\n// cnc_alarm() -> Alarm information",
            "java": "// FOCAS2 example - FANUC CNC Client\n// Requires: Fwlib32.dll (via JNI)\n// Connection: {host}:{port}\n// cnc_statinfo() -> Running status\n// cnc_rdaxis() -> Axis coordinates\n// cnc_alarm() -> Alarm information",
            "go": "// FOCAS2 example - FANUC CNC Client\n// Requires: Fwlib32.dll (via CGO)\n// Connection: {host}:{port}\n// cnc_statinfo() -> Running status\n// cnc_rdaxis() -> Axis coordinates",
        },
    },
    "mtconnect": {
        "mode": "server",
        "mode_label": "Server Simulation (Agent)",
        "mode_desc": "ProtoForge simulates an MTConnect Agent, your application gets device data (XML format) via HTTP requests",
        "connect_hint": "In your MTConnect client, fill in the Agent address:",
        "code_examples": {
            "python": "# MTConnect HTTP Client\nimport requests\n\nbase = 'http://{host}:{port}'\nresp = requests.get(f'{base}/current')\nprint(resp.text)",
            "csharp": "// MTConnect HTTP Client\nusing var http = new HttpClient {{ BaseAddress = new Uri(\"http://{host}:{port}\") }};\n\nvar current = await http.GetStringAsync(\"/current\");\nConsole.WriteLine(current);\n\nvar probe = await http.GetStringAsync(\"/probe\");\nConsole.WriteLine(probe);",
            "java": "// MTConnect HTTP Client\nimport java.net.http.*;\n\nHttpClient client = HttpClient.newHttpClient();\nHttpRequest req = HttpRequest.newBuilder()\n    .uri(URI.create(\"http://{host}:{port}/current\"))\n    .build();\nString body = client.send(req, HttpResponse.BodyHandlers.ofString()).body();\nSystem.out.println(body);",
            "go": "// MTConnect HTTP Client\nimport \"net/http\"\n\nresp, _ := http.Get(\"http://{host}:{port}/current\")\nbody, _ := io.ReadAll(resp.Body)\nfmt.Println(string(body))",
        },
    },
    "toledo": {
        "mode": "server",
        "mode_label": "Server Simulation (Weighing Instrument)",
        "mode_desc": "ProtoForge simulates a Mettler-Toledo weighing instrument, your application sends SI/S commands via TCP/serial to read weight data",
        "connect_hint": "In your weighing communication program, fill in the connection parameters:",
        "code_examples": {
            "python": "# Toledo TCP Client\nimport socket\n\nsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\nsock.connect(('{host}', {port}))\nsock.sendall(b'SI\\r\\n')\nresponse = sock.recv(1024)\nprint(response.decode())",
            "csharp": "// Toledo TCP Client\nusing System.Net.Sockets;\n\nusing var tcp = new TcpClient(\"{host}\", {port});\nvar stream = tcp.GetStream();\n\n// SI command: Read stable weight\nvar cmd = Encoding.ASCII.GetBytes(\"SI\\r\\n\");\nstream.Write(cmd, 0, cmd.Length);\nvar buf = new byte[1024];\nint n = stream.Read(buf, 0, buf.Length);\nConsole.WriteLine(Encoding.ASCII.GetString(buf, 0, n));",
            "java": "// Toledo TCP Client\nimport java.net.Socket;\n\nSocket sock = new Socket(\"{host}\", {port});\nOutputStream out = sock.getOutputStream();\nBufferedReader in = new BufferedReader(new InputStreamReader(sock.getInputStream()));\n\nout.write(\"SI\\r\\n\".getBytes());\nString response = in.readLine();\nSystem.out.println(response);",
            "go": "// Toledo TCP Client\nimport \"net\"\n\nconn, _ := net.Dial(\"tcp\", \"{host}:{port}\")\nconn.Write([]byte(\"SI\\r\\n\"))\nbuf := make([]byte, 1024)\nn, _ := conn.Read(buf)\nfmt.Println(string(buf[:n]))",
        },
    },
    "profinet": {
        "mode": "server",
        "mode_label": "Server Simulation (IO Device)",
        "mode_desc": "ProtoForge simulates a PROFINET IO Device (slave), your IO Controller (master) discovers and establishes connection via DCP, exchanges cyclic data",
        "connect_hint": "In your PROFINET IO Controller configuration, add a device and fill in:",
        "code_examples": {
            "python": "# profinet-py example - PROFINET IO Controller\nfrom profinet import ProfinetIOController\n\ncontroller = ProfinetIOController('{device_name}')\ncontroller.connect('{host}', {port})\ndevice = controller.dcp_identify('{device_name}')\ninput_data = controller.read_cyclic_data()",
            "csharp": "// PROFINET example - Using PROFINET SDK\n// Device name: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// Establish connection after configuring GSDML file\n// Read/write cyclic data",
            "java": "// PROFINET example\n// Device name: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// Establish connection after configuring GSDML file",
            "go": "// PROFINET example\n// Device name: {device_name}\n// IP: {host}:{port}\n// VendorID: {vendor_id}, DeviceID: {device_id}\n// Establish connection after configuring GSDML file",
        },
    },
    "ethercat": {
        "mode": "server",
        "mode_label": "Server Simulation (Slave)",
        "mode_desc": "ProtoForge simulates an EtherCAT Slave, your EtherCAT Master can read/write PDO process data and SDO service data after connection",
        "connect_hint": "In your EtherCAT Master program, configure the slave parameters:",
        "code_examples": {
            "python": "# pysoem example - EtherCAT Master\nimport pysoem\n\nmaster = pysoem.Master()\nmaster.open('{host}')\nslave_count = master.config_init()\n\nif slave_count > 0:\n    slave = master.slaves[0]\n    master.state = pysoem.OP_STATE\n    master.write_state()\n    master.send_processdata()\n    master.receive_processdata(5000)",
            "csharp": "// SOEM.NET example - EtherCAT Master\nusing SOEM;\n\nvar master = new Master();\nmaster.Open(\"{host}\");\nint slaveCount = master.ConfigInit();\n\nif (slaveCount > 0)\n{\n    master.State = OpState.OP;\n    master.WriteState();\n    master.SendProcessData();\n    master.ReceiveProcessData(5000);\n}",
            "java": "// EtherCAT example\n// Using SOEM JNI binding\n// Connection: {host}\n// Scan slaves -> PRE-OP -> SAFE-OP -> OP\n// Read/write PDO process data",
            "go": "// ethercat example - EtherCAT Master\n// Using SOEM CGO binding\n// Connection: {host}\n// Scan slaves -> PRE-OP -> SAFE-OP -> OP\n// Read/write PDO process data",
        },
    },
}

for _proto_name, _proto_usage in PROTOCOL_USAGE.items():
    if "code_examples" in _proto_usage and "code_example" not in _proto_usage:
        _proto_usage["code_example"] = _proto_usage["code_examples"].get("python", "")

HTTP_TIMEOUT_DEFAULT = 10.0
HTTP_TIMEOUT_SHORT = 5.0
HTTP_TIMEOUT_LONG = 30.0

import logging
_defaults_logger = logging.getLogger(__name__)


def get_http_timeout_default() -> float:
    try:
        from protoforge.config import get_settings
        return get_settings().http_timeout
    except Exception as e:
        _defaults_logger.debug("Failed to read http_timeout from config, using default: %s", e)
        return HTTP_TIMEOUT_DEFAULT


def get_http_timeout_short() -> float:
    try:
        from protoforge.config import get_settings
        return get_settings().http_timeout_short
    except Exception as e:
        _defaults_logger.debug("Failed to read http_timeout_short from config, using default: %s", e)
        return HTTP_TIMEOUT_SHORT


def get_http_timeout_long() -> float:
    try:
        from protoforge.config import get_settings
        return get_settings().http_timeout_long
    except Exception as e:
        _defaults_logger.debug("Failed to read http_timeout_long from config, using default: %s", e)
        return HTTP_TIMEOUT_LONG

ERROR_MESSAGES = {
    "Device not found": "The device was not found, it may have been deleted or the ID is incorrect. Please check the device list.",
    "Scenario not found": "The scenario was not found, it may have been deleted. Please check the scenario list.",
    "Template not found": "The template was not found. Please select an available template from the template marketplace.",
    "Protocol not found": "The protocol service was not found. Please start the corresponding protocol on the Protocol Services page first.",
    "Protocol already running": "The protocol is already running, no need to start again.",
    "Protocol not running": "The protocol is not running. Please start the protocol before operating the device.",
    "Device already exists": "The device ID already exists. Please use a unique device ID.",
    "Invalid credentials": "Incorrect username or password",
    "Username already exists": "The username is already registered, please choose another one.",
    "Password must be at least 6 characters": "Password does not meet strength requirements. Please set a password of at least 8 characters containing at least 3 of: uppercase, lowercase, digits, special characters.",
    "Cannot delete this user": "Cannot delete the administrator account.",
    "url is required": "Please fill in the Webhook URL address.",
    "No active recording": "There is no active recording. Please start recording first.",
    "devices= cannot be None": "Modbus slave context initialization failed, please ensure at least one device exists.",
    "address already in use": "Port is already in use, another service is running on this port. Please change the protocol port number in System Settings, or stop the other process using this port.",
    "could not bind": "Port binding failed, the port may be occupied by another service. Please change the protocol port number in System Settings.",
    "could not start listen": "Failed to start listening, the port may be in use or insufficient permissions. On Linux, ports below 1024 require root privileges.",
    "permission denied": "Insufficient permissions. On Linux, binding ports below 1024 requires root privileges. Please change to a port above 1024 in System Settings.",
    "ERROR state after start": "Protocol start failed, possibly due to port conflict, insufficient permissions, or configuration error. Please check server logs or try changing the port number.",
    "connection refused": "Unable to connect to the target server. Possible causes: 1) The target service is not running; 2) The IP/port is incorrect; 3) A firewall is blocking the connection. Please check the target service status and network configuration.",
    "connection timed out": "Connection timed out. The target server did not respond within the expected time. Possible causes: 1) The target service is overloaded; 2) Network latency is too high; 3) A firewall is blocking the connection. Please check network connectivity.",
    "timed out": "Operation timed out. The target service did not respond within the expected time. Please check network connectivity or try again later.",
    "name or service not known": "Unable to resolve the target hostname. Please check that the server address is correct and DNS is working properly.",
    "network is unreachable": "The network is unreachable. Please check your network connection and configuration.",
    "no route to host": "No route to the target host. Please check that the target host is online and the network is connected.",
    "connection reset": "The connection was reset by the target server. The target service may have crashed or rejected the connection. Please check the target service status.",
    "broken pipe": "The connection was unexpectedly closed by the target server. This may be caused by the target service restarting or network instability.",
    "ssl": "SSL/TLS handshake failed. Possible causes: 1) Certificate is invalid or expired; 2) Protocol version mismatch; 3) Insecure connection not allowed. Please check the certificate and security configuration.",
    "authentication failed": "Authentication failed. Please check that the username, password, or authentication key is correct.",
    "access denied": "Access denied. The target server rejected the connection. Please check authentication credentials and permissions.",
    "endpoint": "Failed to connect to the specified endpoint. Please check that the server address and port are correct, and that the target service is running.",
}


ERROR_MESSAGES_ZH = {
    "Device not found": "设备未找到，可能已被删除或ID不正确。请检查设备列表。",
    "Scenario not found": "场景未找到，可能已被删除。请检查场景列表。",
    "Template not found": "模板未找到。请从模板市场选择可用的模板。",
    "Protocol not found": "协议服务未找到。请先在协议服务页面启动对应的协议。",
    "Protocol already running": "协议已在运行中，无需重复启动。",
    "Protocol not running": "协议未运行。请先启动协议再操作设备。",
    "Device already exists": "设备ID已存在。请使用唯一的设备ID。",
    "Invalid credentials": "用户名或密码错误",
    "Username already exists": "用户名已被注册，请选择其他用户名。",
    "Password must be at least 6 characters": "密码不符合强度要求。请设置至少8位密码，包含大写、小写、数字、特殊字符中的至少3种。",
    "Cannot delete this user": "无法删除管理员账户。",
    "url is required": "请填写Webhook URL地址。",
    "No active recording": "没有正在进行的录制。请先开始录制。",
    "devices= cannot be None": "Modbus从站上下文初始化失败，请确保至少存在一个设备。",
    "address already in use": "端口已被占用，另一个服务正在使用该端口。请在系统设置中更改协议端口号，或停止占用该端口的进程。",
    "could not bind": "端口绑定失败，端口可能被其他服务占用。请在系统设置中更改协议端口号。",
    "could not start listen": "启动监听失败，端口可能被占用或权限不足。Linux下1024以下端口需要root权限。",
    "permission denied": "权限不足。Linux下绑定1024以下端口需要root权限。请在系统设置中更改为1024以上的端口。",
    "ERROR state after start": "协议启动失败，可能原因：端口冲突、权限不足或配置错误。请检查服务器日志或尝试更换端口号。",
    "connection refused": "无法连接到目标服务器。可能原因：1) 目标服务未运行；2) IP/端口不正确；3) 防火墙阻止了连接。请检查目标服务状态和网络配置。",
    "connection timed out": "连接超时。目标服务器未在预期时间内响应。可能原因：1) 目标服务负载过高；2) 网络延迟过大；3) 防火墙阻止了连接。请检查网络连通性。",
    "timed out": "操作超时。目标服务器未在预期时间内响应。请检查网络连通性或稍后重试。",
    "name or service not known": "无法解析目标主机名。请检查服务器地址是否正确以及DNS是否正常。",
    "network is unreachable": "网络不可达。请检查网络连接和配置。",
    "no route to host": "无法到达目标主机。请检查目标主机是否在线以及网络是否连通。",
    "connection reset": "连接被目标服务器重置。目标服务可能崩溃或拒绝了连接。请检查目标服务状态。",
    "broken pipe": "连接被目标服务器意外关闭。可能是目标服务重启或网络不稳定导致。",
    "ssl": "SSL/TLS握手失败。可能原因：1) 证书无效或过期；2) 协议版本不匹配；3) 不允许不安全连接。请检查证书和安全配置。",
    "authentication failed": "认证失败。请检查用户名、密码或认证密钥是否正确。",
    "access denied": "访问被拒绝。目标服务器拒绝了连接。请检查认证凭据和权限。",
    "endpoint": "无法连接到指定的端点。请检查服务器地址和端口是否正确，以及目标服务是否运行。",
}


def get_friendly_error(detail: str, lang: str = "zh") -> str:
    """Convert raw error messages to user-friendly messages.

    Args:
        detail: Raw error message string.
        lang: Language code ("zh" or "en"). Defaults to "zh".
    """
    messages = ERROR_MESSAGES_ZH if lang == "zh" else ERROR_MESSAGES
    for key, msg in messages.items():
        if key.lower() in detail.lower():
            return msg
    return detail


def get_protocol_defaults(protocol_name: str, lang: str = "zh") -> dict:
    try:
        from protoforge.config import get_protocol_port_map
        base = PROTOCOL_DEFAULTS.get(protocol_name, {"host": "0.0.0.0", "port": 8000})
        port_map = get_protocol_port_map()
    except Exception:
        base = PROTOCOL_DEFAULTS.get(protocol_name, {"host": "0.0.0.0", "port": 8000})
        port_map = {}
    if protocol_name in port_map:
        base = {**base, **port_map[protocol_name]}
    from protoforge.core.messages import desc
    base["display_name"] = desc(f"protocol.{protocol_name}", lang, base.get("display_name", protocol_name))
    base["description"] = desc(f"protocol.{protocol_name}.desc", lang, base.get("description", ""))
    # i18n化config字段的label和description
    if "config" in base:
        for field in base["config"]:
            field_key = field.get("key", "")
            if field_key:
                field["label"] = desc(f"protocol.{protocol_name}.config.{field_key}.label", lang, field.get("label", field_key))
                field["description"] = desc(f"protocol.{protocol_name}.config.{field_key}.desc", lang, field.get("description", ""))
    return base


def get_all_protocol_info(lang: str = "zh") -> list[dict]:
    try:
        from protoforge.config import get_protocol_port_map
        port_map = get_protocol_port_map()
    except Exception:
        port_map = {}
    from protoforge.core.messages import desc
    result = []
    for name, info in PROTOCOL_DEFAULTS.items():
        port_info = port_map.get(name, {})
        result.append({
            "name": name,
            "display_name": desc(f"protocol.{name}", lang, info.get("display_name", name)),
            "description": desc(f"protocol.{name}.desc", lang, info.get("description", "")),
            "default_port": port_info.get("port", info.get("port", 0)),
            "icon": info.get("icon", ""),
        })
    return result
