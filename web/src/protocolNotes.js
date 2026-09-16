/**
 * 各协议客户端连接注意事项（醒目标注）
 *
 * FIXED-F4: 由 MQTT 3.1.1 协议版本坑（用户 MQTTX 默认 5.0 连不上）推广而来。
 * key = 协议名（与 PROTOCOL_REGISTRY 一致），items = [zh, en] 双语数组。
 * 设备弹窗（快速创建/高级创建/编辑）在选中协议后立即展示对应条目。
 *
 * 注意：数值类内容（默认 rack/slot、端口）须与各协议 server 实现一致，改动协议默认值时同步更新。
 */
export const PROTOCOL_NOTES = {
  mqtt: {
    items: {
      zh: [
        '内置 MQTT Broker 仅支持 MQTT 3.1.1 协议，不支持 MQTT 5.0 —— MQTTX 等客户端连接时，请在连接设置中手动将 Protocol Version 选为 3.1.1（默认 5.0 会连接失败）',
        '设备默认上报到内置 Broker；如需上报到自己的 MQTT 服务器（EMQX/Mosquitto/阿里云 IoT 等），在下方协议配置中填写“自定义 MQTT 服务器”地址即可，设备将以客户端身份连接并上报',
      ],
      en: [
        'The built-in MQTT Broker only supports MQTT 3.1.1 (NOT 5.0). In MQTTX or other clients, manually set Protocol Version to 3.1.1 in connection settings (the default 5.0 will fail to connect)',
        'Devices report to the built-in broker by default; to report to your own MQTT server (EMQX/Mosquitto/Aliyun IoT etc.), fill in the Custom MQTT Server address below and the device will connect and report as an MQTT client',
      ],
    },
  },
  modbus_tcp: {
    items: {
      zh: [
        '请求中的 Unit ID 必须与从站地址配置一致（0 或 255 通常按广播处理）',
        '502 是特权端口，直连映射时注意容器端口映射与防火墙放行',
        '布尔量（bool）点位存储在线圈区（0xxxxx）：用功能码 01 读、05 写；读保持寄存器（03）看不到它们，数值型点位才在保持寄存器区（4xxxxx）',
      ],
      en: [
        'The Unit ID in requests must match the configured slave address (0 / 255 are usually treated as broadcast)',
        'Port 502 is privileged — check container port mapping and firewall rules when connecting directly',
        'Boolean (bool) points live in the coil area (0xxxxx): read with FC 01 and write with FC 05; they are invisible to FC 03 (holding registers). Numeric points use the holding-register area (4xxxxx)',
      ],
    },
  },
  modbus_rtu: {
    items: {
      zh: [
        '波特率 / 校验位 / 停止位三项必须与主站完全一致，任一不匹配将导致帧错误',
        '串口链路上从站地址必须唯一，重复地址会引起响应冲突',
      ],
      en: [
        'Baudrate / parity / stopbits must exactly match the master, any mismatch causes frame errors',
        'Slave addresses must be unique on the serial link, duplicated addresses cause response collisions',
      ],
    },
  },
  s7: {
    items: {
      zh: [
        '本平台默认 Rack=0 / Slot=1（S7-1200/1500 语义），客户端连接参数需一致，可在协议配置中修改',
        '连接真机 S7-1200/1500 时需在 TIA Portal 中勾选“允许来自远程对象的 PUT/GET 通信访问”，否则连接被拒',
      ],
      en: [
        'Default Rack=0 / Slot=1 (S7-1200/1500 semantics) — client connection parameters must match, configurable in protocol settings',
        'For real S7-1200/1500 CPUs, enable "Permit access with PUT/GET" in TIA Portal, otherwise connections are rejected',
      ],
    },
  },
  opcua: {
    items: {
      zh: [
        '仿真服务器默认无加密：客户端安全策略需选 None、身份验证选 Anonymous，否则握手失败',
        '端点 URL 以服务器实际监听地址为准（可通过协议配置修改端口）',
      ],
      en: [
        'The simulated server runs without encryption: set client Security Policy to None and Authentication to Anonymous, otherwise the handshake fails',
        'Use the actual listening address for the endpoint URL (port configurable in protocol settings)',
      ],
    },
  },
  iec104: {
    items: {
      zh: [
        '标准端口 2404，主站侧遥测/遥信的公共地址（CA）与信息对象地址（IOA）需与点位配置一致',
        '主站的 k/w 等链路参数过大时注意与服务器参数匹配，避免测试窗流量差异',
      ],
      en: [
        'Standard port 2404; the common address (CA) and information object address (IOA) on the master side must match point configuration',
        'Match link parameters (k/w) between master and server to avoid test-window mismatches',
      ],
    },
  },
  dlt645: {
    items: {
      zh: [
        '请求中的表地址（12 位 BCD）必须与设备配置一致，也可以用通配地址 0xAAAAAAAAAAAA',
        '数据标识的 0x33 加解密由协议自动处理，客户端无需手工偏移',
      ],
      en: [
        'The meter address (12-digit BCD) in requests must match the device configuration; wildcard address 0xAAAAAAAAAAAA is also accepted',
        'The 0x33 offset for data identifiers is handled automatically by the protocol, no manual shifting needed',
      ],
    },
  },
  cjt188: {
    items: {
      zh: [
        '表地址（BCD 编码）必须与设备配置一致，地址类型（表号/用户号等）按需选择',
        '数据标识需符合 CJ/T 188-2004 附录定义，否则返回错误',
      ],
      en: [
        'The meter address (BCD encoded) must match the device configuration; choose the address type (meter No. / user No. etc.) as needed',
        'Data identifiers must follow CJ/T 188-2004 appendix definitions, otherwise errors are returned',
      ],
    },
  },
  fins: {
    items: {
      zh: [
        'UDP（9602）与 TCP（9600）默认端口不同，客户端需使用与服务端一致的模式和端口',
        'FINS 帧头中的节点地址需与实际网络配置对应',
      ],
      en: [
        'UDP (9602) and TCP (9600) use different default ports — use the same mode and port as the server side',
        'Node addresses in the FINS header must match the actual network configuration',
      ],
    },
  },
  mc: {
    items: {
      zh: [
        '帧格式（3E/4E）与访问目标（CPU 类型）需与客户端设置一致，默认 3E 帧',
        '软元件编号按十进制/十六进制的差异（QnA/ACPU）是常见错误源，注意与协议配置匹配',
      ],
      en: [
        'Frame format (3E/4E) and access target (CPU type) must match client settings, default is 3E frame',
        'Decimal vs hexadecimal device numbering (QnA/ACPU) is a common error source, align it with protocol configuration',
      ],
    },
  },
  bacnet: {
    items: {
      zh: [
        '标准端口 UDP 47808（0xBAC0），本机防火墙需放行',
        '跨网段访问需要配置 BBMD 或使用全局广播，单播跨路由默认不可达',
      ],
      en: [
        'Standard port is UDP 47808 (0xBAC0), local firewall must allow it',
        'Cross-subnet access requires BBMD configuration or global broadcast, plain unicast does not cross routers by default',
      ],
    },
  },
  fanuc: {
    items: {
      zh: [
        'FOCAS 以太网端口默认 8192，需在机床侧开启“嵌入式以太网”并允许 FOCAS 访问',
        '焦点通路（路径号）与实际机床多路径配置需一致',
      ],
      en: [
        'FOCAS Ethernet port defaults to 8192 — enable "Embedded Ethernet" on the machine and allow FOCAS access',
        'The path number must match the actual multi-path configuration of the machine',
      ],
    },
  },
  opcda: {
    items: {
      zh: [
        'OPC DA 基于 Windows DCOM：客户端与服务器两侧都需正确配置 DCOM 权限（身份验证/访问权限），这是最常见的连接失败原因',
        'ProgID 与服务器注册名必须一致，浏览服务器列表需要 DCOM 浏览权限',
      ],
      en: [
        'OPC DA is built on Windows DCOM: DCOM permissions (authentication / access rights) must be configured on BOTH sides, the most common cause of connection failures',
        'The ProgID must match the server registration name; browsing the server list requires DCOM browsing permissions',
      ],
    },
  },
  ab: {
    items: {
      zh: [
        'CIP 路径（槽号）必须与实际机型一致：ControlLogix 需指定 CPU 所在背板槽号',
        'MicroLogix/SLC-500 与 Logix 系列的地址寻址方式不同，注意区分',
      ],
      en: [
        'The CIP path (slot) must match the actual hardware: ControlLogix requires the CPU backplane slot number',
        'MicroLogix/SLC-500 and Logix families use different addressing schemes, keep them apart',
      ],
    },
  },
  gb28181: {
    items: {
      zh: [
        '仿真设备会主动向你配置的 SIP 平台发起 REGISTER 注册：平台国标编号、域、SIP 密码三项必须与平台侧完全一致',
      ],
      en: [
        'The simulated device actively sends REGISTER to your configured SIP platform: the platform GB ID, domain and SIP password must exactly match the platform side',
      ],
    },
  },
  custom_tcp: {
    items: {
      zh: [
        '客户端发送的帧格式（长度域/校验算法/字节序）需与模板定义完全一致，否则校验失败被丢弃',
      ],
      en: [
        'The client frame format (length field / checksum algorithm / byte order) must exactly match the template definition, otherwise frames fail checksum and are dropped',
      ],
    },
  },
  custom_udp: {
    items: {
      zh: [
        'UDP 无连接：客户端需向服务器实际监听的地址端口发送，响应地址以请求来源为准',
        '帧格式（长度域/校验算法/字节序）需与模板定义完全一致',
      ],
      en: [
        'UDP is connectionless: send to the actual listening address/port, replies go to the request source',
        'The frame format (length field / checksum algorithm / byte order) must exactly match the template definition',
      ],
    },
  },
}

/** 设备数据外送（协议外）通用提示：连接引导中说明转发能力 */
export const DATA_FORWARD_NOTE = {
  zh: '以上协议中仿真设备均为“被访问的服务端”模型（由你的主站/网关连接设备）。若需要把设备数据主动推送到你自己的 HTTP 服务器，可使用平台的数据转发功能；MQTT 设备则可直接在协议配置中填写自定义 MQTT 服务器。',
  en: 'In the protocols above the simulated devices are server-side models (your master/gateway connects to the device). To push device data to your own HTTP server, use the platform data-forwarding feature; MQTT devices can report directly to a custom MQTT server via protocol config.',
}
