import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let isRefreshing = false
let refreshSubscribers = []

function onTokenRefreshed(newToken) {
  refreshSubscribers.forEach(cb => cb(newToken))
  refreshSubscribers = []
}

api.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        if (isRefreshing) {
          return new Promise(resolve => {
            refreshSubscribers.push(newToken => {
              originalRequest.headers.Authorization = `Bearer ${newToken}`
              originalRequest._retry = true
              resolve(api(originalRequest))
            })
          })
        }
        isRefreshing = true
        originalRequest._retry = true
        try {
          const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
          const newToken = res.data.access_token
          if (newToken) {
            localStorage.setItem('token', newToken)
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            onTokenRefreshed(newToken)
            return api(originalRequest)
          }
        } catch (e) { /* refresh failed */ } finally {
          isRefreshing = false
        }
      }
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      window.location.reload()
    }
    return Promise.reject(error)
  }
)

const d = (promise) => promise.then(r => r.data)

export default {
  login: (username, password) => d(api.post('/auth/login', { username, password })),
  refreshToken: (refresh_token) => d(api.post('/auth/refresh', { refresh_token })),
  register: (username, password) => d(api.post('/auth/register', { username, password })),
  listUsers: () => d(api.get('/auth/users')),
  changePassword: (username, old_password, new_password) => d(api.post('/auth/change-password', { username, old_password, new_password })),
  adminResetPassword: (username, new_password) => d(api.post(`/auth/admin/reset-password`, { username, new_password })),
  adminUnlockUser: (username) => d(api.post(`/auth/admin/unlock/${username}`)),
  adminUpdateRole: (username, role) => d(api.put(`/auth/users/${username}/role`, { role })),
  deleteUser: (username) => d(api.delete(`/auth/users/${username}`)),

  getProtocols: () => d(api.get('/protocols')),
  getProtocolInfo: () => d(api.get('/protocols/info')),
  getProtocolConfig: (name) => d(api.get(`/protocols/${name}/config`)),
  getProtocolDeviceConfig: (name) => d(api.get(`/protocols/${name}/device-config`)),
  startProtocol: (name, config) => d(api.post(`/protocols/${name}/start`, config)),
  stopProtocol: (name) => d(api.post(`/protocols/${name}/stop`)),

  getDevices: (protocol) => d(api.get('/devices', { params: { protocol } })),
  createDevice: (config) => d(api.post('/devices', config)),
  quickCreateDevice: (templateId, name, id, protocolConfig) => d(api.post('/devices/quick-create', { template_id: templateId, name, id, protocol_config: protocolConfig || {} })),
  getDevice: (id) => d(api.get(`/devices/${id}`)),
  getDeviceConfig: (id) => d(api.get(`/devices/${id}/config`)),
  updateDevice: (id, config) => d(api.put(`/devices/${id}`, config)),
  deleteDevice: (id) => d(api.delete(`/devices/${id}`)),
  startDevice: (id) => d(api.post(`/devices/${id}/start`)),
  stopDevice: (id) => d(api.post(`/devices/${id}/stop`)),
  getDevicePoints: (id) => d(api.get(`/devices/${id}/points`)),
  getDeviceConnectionGuide: (id) => d(api.get(`/devices/${id}/connection-guide`)),
  writeDevicePoint: (id, point, value) => d(api.put(`/devices/${id}/points/${point}`, { value })),
  batchCreateDevices: (configs) => d(api.post('/devices/batch', configs)),
  batchDeleteDevices: (ids) => d(api.request({ method: 'DELETE', url: '/devices/batch', data: ids })),
  batchStartDevices: (ids) => d(api.post('/devices/batch/start', ids)),
  batchStopDevices: (ids) => d(api.post('/devices/batch/stop', ids)),

  getTemplates: (protocol) => d(api.get('/templates', { params: { protocol } })),
  getTemplate: (id) => d(api.get(`/templates/${id}`)),
  createTemplate: (template) => d(api.post('/templates', template)),
  deleteTemplate: (id) => d(api.delete(`/templates/${id}`)),
  searchTemplates: (params) => d(api.get('/templates/search', { params })),
  listTemplateTags: () => d(api.get('/templates/tags')),
  instantiateTemplate: (id, params) => {
    const { device_id, device_name, protocol_config, ...rest } = params || {}
    return d(api.post(`/templates/${id}/instantiate`, protocol_config ? { protocol_config } : null, { params: { device_id, device_name, ...rest } }))
  },

  getScenarios: () => d(api.get('/scenarios')),
  createScenario: (config) => d(api.post('/scenarios', config)),
  getScenario: (id) => d(api.get(`/scenarios/${id}`)),
  updateScenario: (id, config) => d(api.put(`/scenarios/${id}`, config)),
  deleteScenario: (id) => d(api.delete(`/scenarios/${id}`)),
  startScenario: (id) => d(api.post(`/scenarios/${id}/start`)),
  stopScenario: (id) => d(api.post(`/scenarios/${id}/stop`)),
  exportScenario: (id) => d(api.get(`/scenarios/${id}/export`)),
  importScenario: (config) => d(api.post('/scenarios/import', config)),
  getScenarioSnapshot: (id) => d(api.get(`/scenarios/${id}/snapshot`)),

  getLogs: (params) => d(api.get('/logs', { params })),
  clearLogs: () => d(api.delete('/logs')),

  createTestCase: (data) => d(api.post('/tests/cases', data)),
  listTestCases: (params) => d(api.get('/tests/cases', { params })),
  getTestCase: (id) => d(api.get(`/tests/cases/${id}`)),
  updateTestCase: (id, data) => d(api.put(`/tests/cases/${id}`, data)),
  deleteTestCase: (id) => d(api.delete(`/tests/cases/${id}`)),
  createTestSuite: (data) => d(api.post('/tests/suites', data)),
  listTestSuites: () => d(api.get('/tests/suites')),
  getTestSuite: (id) => d(api.get(`/tests/suites/${id}`)),
  deleteTestSuite: (id) => d(api.delete(`/tests/suites/${id}`)),
  runTests: (cases) => d(api.post('/tests/run', cases)),
  runTestCase: (id) => d(api.post(`/tests/run/case/${id}`)),
  runTestSuite: (id) => d(api.post(`/tests/run/suite/${id}`)),
  quickTest: (scope, targetId) => d(api.post('/tests/quick-test', null, { params: { scope, target_id: targetId || undefined } })),
  getTestSuggestions: () => d(api.get('/tests/suggestions')),
  getTestActionTypes: () => d(api.get('/tests/action-types')),
  getTestAssertionTypes: () => d(api.get('/tests/assertion-types')),
  listTestReports: () => d(api.get('/tests/reports')),
  getTestReport: (id) => d(api.get(`/tests/reports/${id}`)),
  getTestReportHtml: (id) => d(api.get(`/tests/reports/${id}/html`)),
  getReportTrend: (params) => d(api.get('/tests/reports/trend', { params })),

  importEdgelite: (config) => d(api.post('/integration/edgelite', config)),
  importPygbsentry: (config) => d(api.post('/integration/pygbsentry', config)),
  pushToEdgelite: (deviceId) => d(api.post(`/integration/edgelite/push/${deviceId}`)),
  removeDeviceFromEdgelite: (deviceId) => d(api.delete(`/integration/edgelite/push/${deviceId}`)),
  getEdgeliteDeviceStatus: (deviceId) => d(api.get(`/integration/edgelite/status/${deviceId}`)),
  readEdgeliteDevicePoints: (deviceId) => d(api.get(`/integration/edgelite/points/${deviceId}`)),
  verifyEdgelitePipeline: (deviceId) => d(api.get(`/integration/edgelite/pipeline/${deviceId}`)),
  testEdgeliteConnection: (config) => d(api.post('/integration/edgelite/test', config)),

  getIntegrationStatus: () => d(api.get('/integration/status')),
  getIntegrationMetrics: () => d(api.get('/integration/metrics')),
  getIntegrationProtocols: () => d(api.get('/integration/protocols')),
  validateDeviceCompatibility: (data) => d(api.post('/integration/validate', data)),
  batchPushDevices: (data) => d(api.post('/integration/batch-push', data)),
  startIntegrationDevice: (deviceId) => d(api.post(`/integration/device/${deviceId}/start`)),
  stopIntegrationDevice: (deviceId) => d(api.post(`/integration/device/${deviceId}/stop`)),
  getBackhaulData: (params) => d(api.get('/integration/backhaul-data', { params })),
  getDeviceStatusCache: () => d(api.get('/integration/device-status')),
  getAlarmRules: () => d(api.get('/integration/alarm-rules')),
  addAlarmRule: (data) => d(api.post('/integration/alarm-rules', data)),
  deleteAlarmRule: (ruleId) => d(api.delete(`/integration/alarm-rules/${ruleId}`)),

  createDeviceWs: () => {
    const token = localStorage.getItem('token')
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/api/v1/ws/devices${token ? '?token=' + token : ''}`
    return new WebSocket(url)
  },

  createLogWs: () => {
    const token = localStorage.getItem('token')
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/api/v1/ws/logs${token ? '?token=' + token : ''}`
    return new WebSocket(url)
  },

  listForwardTargets: () => d(api.get('/forward/targets')),
  addForwardTarget: (config) => d(api.post('/forward/targets', config)),
  removeForwardTarget: (name) => d(api.delete(`/forward/targets/${name}`)),
  startForward: () => d(api.post('/forward/start')),
  stopForward: () => d(api.post('/forward/stop')),
  getForwardStats: () => d(api.get('/forward/stats')),

  startRecording: (config) => d(api.post('/recorder/start', config)),
  stopRecording: () => d(api.post('/recorder/stop')),
  listRecordings: () => d(api.get('/recorder/recordings')),
  getRecording: (id) => d(api.get(`/recorder/recordings/${id}`)),
  deleteRecording: (id) => d(api.delete(`/recorder/recordings/${id}`)),
  replayRecording: (id, config) => d(api.post(`/recorder/recordings/${id}/replay`, config)),
  exportRecording: (id) => d(api.get(`/recorder/recordings/${id}/export`)),
  getRecorderStats: () => d(api.get('/recorder/stats')),

  listWebhooks: () => d(api.get('/webhooks')),
  addWebhook: (config) => d(api.post('/webhooks', config)),
  updateWebhook: (id, config) => d(api.put(`/webhooks/${id}`, config)),
  deleteWebhook: (id) => d(api.delete(`/webhooks/${id}`)),
  testWebhook: (id) => d(api.post(`/webhooks/${id}/test`)),
  getWebhookStats: () => d(api.get('/webhooks/stats')),

  setupDemo: () => d(api.post('/setup/demo')),
  getSetupStatus: () => d(api.get('/setup/status')),

  getSettings: () => d(api.get('/settings')),
  updateSettings: (updates) => d(api.put('/settings', updates)),

  queryAuditLog: (params) => d(api.get('/audit', { params })),
  getAuditStats: () => d(api.get('/audit/stats')),
  deleteAuditEntry: (id) => d(api.delete(`/audit/${id}`)),
  clearAuditLog: (params) => d(api.delete('/audit', { params })),

  exportBackup: () => d(api.get('/backup')),
  importBackup: (data) => d(api.post('/backup/restore', data)),
}
