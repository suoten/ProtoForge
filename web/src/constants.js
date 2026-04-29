export const protocolLabels = {
  modbus: 'Modbus TCP',
  'modbus-rtu': 'Modbus RTU',
  opcua: 'OPC-UA',
  mqtt: 'MQTT',
  http: 'HTTP',
  gb28181: 'GB28181',
  bacnet: 'BACnet',
  s7: 'S7',
  mc: 'MC Protocol',
  fins: 'FINS',
  ab: 'AB EtherNet/IP',
  opcda: 'OPC-DA',
  fanuc: 'FANUC FOCAS',
  mtconnect: 'MTConnect',
  toledo: 'Mettler-Toledo',
  profinet: 'PROFINET IO',
  ethercat: 'EtherCAT',
}

export const protocolColors = {
  modbus: '#4f46e5',
  'modbus-rtu': '#6366f1',
  opcua: '#059669',
  mqtt: '#d97706',
  http: '#dc2626',
  gb28181: '#7c3aed',
  bacnet: '#0891b2',
  s7: '#be185d',
  mc: '#9333ea',
  fins: '#c2410c',
  ab: '#15803d',
  opcda: '#475569',
  fanuc: '#e11d48',
  mtconnect: '#0d9488',
  toledo: '#a16207',
  profinet: '#2563eb',
  ethercat: '#7c2d12',
}

export const protocolTagTypes = {
  modbus: 'info',
  'modbus-rtu': 'info',
  opcua: 'success',
  mqtt: 'warning',
  http: 'error',
  gb28181: 'info',
  bacnet: 'info',
  s7: 'error',
  mc: 'info',
  fins: 'warning',
  ab: 'success',
  opcda: 'default',
  fanuc: 'error',
  mtconnect: 'success',
  toledo: 'warning',
  profinet: 'info',
  ethercat: 'warning',
}

export const protocolModes = {
  modbus: 'TCP',
  'modbus-rtu': 'RTU',
  opcua: 'Server',
  mqtt: 'Broker',
  http: 'Server',
  gb28181: 'SIP',
  bacnet: 'Server',
  s7: 'Server',
  mc: 'Server',
  fins: 'Server',
  ab: 'Server',
  opcda: 'Server',
  fanuc: 'Server',
  mtconnect: 'Agent',
  toledo: 'Server',
  profinet: 'IO Device',
  ethercat: 'Slave',
}

export const defaultPorts = {
  modbus: 502,
  'modbus-rtu': '/dev/ttyUSB0',
  opcua: 4840,
  mqtt: 1883,
  http: 8080,
  gb28181: 5060,
  bacnet: 47808,
  s7: 102,
  mc: 5007,
  fins: 9600,
  ab: 44818,
  opcda: 135,
  fanuc: 8193,
  mtconnect: 5000,
  toledo: 1701,
  profinet: 30000,
  ethercat: 34980,
}

export const deviceStatusMap = {
  online: ['success', '在线'],
  running: ['success', '运行中'],
  error: ['error', '错误'],
  stopped: ['default', '已停止'],
  offline: ['default', '离线'],
  disabled: ['default', '已禁用'],
}

export const directionColorMap = {
  in: '#6366f1', out: '#10b981', system: '#f59e0b', write: '#ec4899',
  recv: '#10b981', send: '#6366f1', inbound: '#6366f1', outbound: '#10b981',
}

export const directionTagTypeMap = {
  in: 'info', out: 'success', system: 'warning', write: 'error',
  recv: 'success', send: 'info', inbound: 'info', outbound: 'success',
}

export const directionLabelMap = {
  in: '← 收', out: '→ 发', system: '系统', write: '✎ 写',
  recv: '← 收', send: '→ 发', inbound: '← 入', outbound: '→ 出',
}
