import { useI18n } from './i18n.js'

const { t } = useI18n()

export const protocolLabels = {
  modbus_tcp: 'Modbus TCP',
  modbus_rtu: 'Modbus RTU',
  opcua: 'OPC-UA',
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

export const deviceStatusMap = {
  online: ['success', 'Online'],
  running: ['success', 'Running'],
  error: ['error', 'Error'],
  stopped: ['default', 'Stopped'],
  offline: ['default', 'Offline'],
  disabled: ['default', 'Disabled'],
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
  in: '\u2190Recv', out: 'Send\u2192', system: 'System', write: '\u270eWrite',
  recv: '\u2190Recv', send: 'Send\u2192', inbound: '\u2190In', outbound: 'Out\u2192',
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

export const dataTypeOptions = [
  { label: 'BOOL', value: 'bool' },
  { label: 'INT16', value: 'int16' },
  { label: 'INT32', value: 'int32' },
  { label: 'UINT16', value: 'uint16' },
  { label: 'UINT32', value: 'uint32' },
  { label: 'FLOAT32', value: 'float32' },
  { label: 'FLOAT64', value: 'float64' },
  { label: 'STRING', value: 'string' },
]

export const generatorTypeOptions = [
  { label: 'Fixed', value: 'fixed' },
  { label: 'Random', value: 'random' },
  { label: 'Sine', value: 'sine' },
  { label: 'Triangle', value: 'triangle' },
  { label: 'Sawtooth', value: 'sawtooth' },
  { label: 'Square', value: 'square' },
  { label: 'Increment', value: 'increment' },
  { label: 'Script', value: 'script' },
]
