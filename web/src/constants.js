export const protocolLabels = {
  modbus_tcp: 'Modbus TCP',
  modbus_rtu: 'Modbus RTU',
  opcua: 'OPC-UA',
  opcua_client: 'OPC-UA Client',
  mqtt: 'MQTT',
  http: 'HTTP REST',
  gb28181: 'GB28181',
  bacnet: 'BACnet',
  s7: 'Siemens S7',
  mc: 'Mitsubishi MC',
  fins: 'Omron FINS',
  ab: 'Rockwell AB',
  opcda: 'OPC-DA',
  fanuc: 'FANUC FOCAS',
  mtconnect: 'MTConnect',
  toledo: 'Mettler-Toledo',
  profinet: 'PROFINET IO',
  ethercat: 'EtherCAT',
}

export const protocolColors = {
  modbus_tcp: '#4f46e5',
  modbus_rtu: '#6366f1',
  opcua: '#059669',
  opcua_client: '#0d9488',
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
  modbus_tcp: 'info',
  modbus_rtu: 'info',
  opcua: 'success',
  opcua_client: 'success',
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
  modbus_tcp: 'TCP',
  modbus_rtu: 'RTU',
  opcua: 'Server',
  opcua_client: 'Client',
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
  modbus_tcp: 5020,
  modbus_rtu: '/dev/ttyUSB0',
  opcua: 4840,
  opcua_client: 4840,
  mqtt: 1883,
  http: 8080,
  gb28181: 5060,
  bacnet: 47808,
  s7: 102,
  mc: 5000,
  fins: 9600,
  ab: 44818,
  opcda: 51340,
  fanuc: 8193,
  mtconnect: 7878,
  toledo: 1701,
  profinet: 34964,
  ethercat: 34980,
}

export async function fetchDefaultPorts() {
  try {
    const api = (await import('./api.js')).default
    const info = await api.getProtocolInfo()
    if (info && Array.isArray(info)) {
      const ports = {}
      for (const p of info) {
        if (p.name && p.default_port !== undefined) {
          ports[p.name] = p.default_port
        }
      }
      return ports
    }
  } catch (e) {
    // fallback to static defaults
  }
  return { ...defaultPorts }
}

export const deviceStatusMap = {  // FIXED: 硬编码英文标签改为i18n key
  online: ['success', 'common.online'],
  running: ['success', 'common.running'],
  error: ['error', 'common.error'],
  stopped: ['default', 'common.stopped'],
  offline: ['default', 'common.offline'],
  disabled: ['default', 'common.disabled'],
}

export const directionColorMap = {
  in: '#6366f1', out: '#10b981', system: '#f59e0b', write: '#ec4899',
  recv: '#10b981', send: '#6366f1', inbound: '#6366f1', outbound: '#10b981',
}

export const directionTagTypeMap = {
  in: 'info', out: 'success', system: 'warning', write: 'error',
  recv: 'success', send: 'info', inbound: 'info', outbound: 'success',
}

export const directionLabelMap = {  // FIXED: 硬编码英文标签改为i18n key
  in: 'logs.directionLabels.in', out: 'logs.directionLabels.out', system: 'logs.directionLabels.system', write: 'logs.directionLabels.write',
  recv: 'logs.directionLabels.recv', send: 'logs.directionLabels.send', inbound: 'logs.directionLabels.inbound', outbound: 'logs.directionLabels.outbound',
}

export function getProtocolLabel(name) {
  return protocolLabels[name] || name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export function getProtocolColor(name) {
  const palette = ['#4f46e5', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#be185d', '#9333ea', '#c2410c', '#15803d', '#e11d48', '#0d9488', '#a16207', '#2563eb', '#7c2d12']
  if (protocolColors[name]) return protocolColors[name]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return palette[Math.abs(hash) % palette.length]
}

export const defaultPointConfig = {
  name: 'value',
  address: '0',
  data_type: 'float32',
  generator_type: 'random',
  min_value: 0,
  max_value: 100,
}

export const popularTemplateIds = [
  'modbus_temperature_sensor', 'siemens_s7_1200', 'smart_lock', 'flow_meter',
  'modbus_mitsubishi_fx5u', 'modbus_fanuc_cnc', 'ab_controllogix', 'fins_cp1h',
  'toledo_scale', 'opcda_scada_server', 'mtconnect_mill', 'gb28181_ptz_camera',
]

export const defaultProtocol = 'modbus_tcp'

export const PASSWORD_MASK = '***'

export const dataTypeOptions = [  // FIXED: 硬编码英文标签改为i18n key
  { label: 'points.dataTypes.bool', value: 'bool' },
  { label: 'points.dataTypes.int16', value: 'int16' },
  { label: 'points.dataTypes.int32', value: 'int32' },
  { label: 'points.dataTypes.uint16', value: 'uint16' },
  { label: 'points.dataTypes.uint32', value: 'uint32' },
  { label: 'points.dataTypes.float32', value: 'float32' },
  { label: 'points.dataTypes.float64', value: 'float64' },
  { label: 'points.dataTypes.string', value: 'string' },
]

export const generatorTypeOptions = [  // FIXED: 硬编码英文标签改为i18n key
  { label: 'points.generatorTypes.fixed', value: 'fixed' },
  { label: 'points.generatorTypes.random', value: 'random' },
  { label: 'points.generatorTypes.random_walk', value: 'random_walk' },  // FIXED-P1: 补充random_walk
  { label: 'points.generatorTypes.sine', value: 'sine' },
  { label: 'points.generatorTypes.triangle', value: 'triangle' },
  { label: 'points.generatorTypes.sawtooth', value: 'sawtooth' },
  { label: 'points.generatorTypes.square', value: 'square' },
  { label: 'points.generatorTypes.increment', value: 'increment' },
  { label: 'points.generatorTypes.script', value: 'script' },
]
