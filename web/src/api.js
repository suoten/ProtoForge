import axios from 'axios'

const API_TIMEOUT_MS = 30000  // FIXED: named constant for API request timeout
const TOKEN_REFRESH_THRESHOLD_SEC = 300  // FIXED: named constant for token refresh window (5 min)

const api = axios.create({
  baseURL: '/api/v1',
  timeout: API_TIMEOUT_MS,
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

function isLoginRequest(url) {
  return url && (url.includes('/auth/login') || url.includes('/auth/refresh') || url.includes('/auth/register'))
}

function extractErrorDetail(data) {
  if (!data) return ''
  if (typeof data.detail === 'string') return data.detail
  if (typeof data.message === 'string') return data.message
  if (typeof data.detail === 'object') {
    try { return JSON.stringify(data.detail) } catch { return String(data.detail) }
  }
  if (typeof data === 'string') return data
  try { return JSON.stringify(data) } catch { return String(data) }
}

let _notifyFn = null
let _tFn = null
function _notifyUser(type, key, params) {
  if (_notifyFn) {
    const msg = _tFn ? _tFn(key, params) : key
    _notifyFn(type, msg)
  }
}
export function setNotifyFunction(fn, tFn) {
  _notifyFn = fn
  _tFn = tFn || null
}

api.interceptors.response.use(
  response => {
    // FIXED: removed silent null→{} replacement that masked API errors
    if (response.data && response.data._persistence_warning) {
      _notifyUser('warning', 'common.persistenceWarning', { detail: response.data._persistence_warning })
      delete response.data._persistence_warning
    }
    if (Array.isArray(response.data)) {
      for (let i = response.data.length - 1; i >= 0; i--) {
        if (response.data[i] && response.data[i]._persistence_warning) {
          _notifyUser('warning', 'common.persistenceWarning', { detail: response.data[i]._persistence_warning })
          delete response.data[i]._persistence_warning
        }
      }
    }
    return response
  },
  async error => {
    const originalRequest = error?.config
    const status = error?.response?.status
    const detail = extractErrorDetail(error?.response?.data)

    if (status === 401 && !originalRequest._retry && !isLoginRequest(originalRequest.url)) {
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        if (isRefreshing) {
          return new Promise(resolve => {
            refreshSubscribers.push(newToken => {
              if (!newToken) {
                resolve(Promise.reject(error))
                return
              }
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
          const newToken = res.data?.access_token  // FIXED: 使用可选链防止undefined
          const newRefresh = res.data?.refresh_token
          if (newToken && typeof newToken === 'string') {  // FIXED: 校验token类型
            localStorage.setItem('token', newToken)
            if (newRefresh) localStorage.setItem('refresh_token', newRefresh)
            if (res.data.username) localStorage.setItem('username', res.data.username)
            if (res.data.role) localStorage.setItem('role', res.data.role)
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            onTokenRefreshed(newToken)
            return api(originalRequest)
          }
        } catch (e) {
          console.warn('Token refresh failed:', e.message)
          onTokenRefreshed(null)
        } finally {
          isRefreshing = false
          refreshSubscribers = []
        }
      }
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      _notifyUser('warning', 'common.apiSessionExpired')
      if (window.location.pathname !== '/') {
        window.location.href = '/'
      }
    } else if (status === 403) {
      console.error('Permission denied:', detail)
      _notifyUser('warning', 'common.apiPermissionDenied', { detail: detail || '' })
    } else if (status === 429) {
      const retryAfter = error?.response?.data?.retry_after
      const msg = retryAfter ? 'common.apiRateLimitedWithRetry' : 'common.apiRateLimited'
      const params = retryAfter ? { seconds: retryAfter } : {}
      console.warn('Rate limited:', msg)
      _notifyUser('warning', msg, params)
    } else if (status === 404) {
      console.error('Resource not found:', detail)
      _notifyUser('warning', 'common.apiResourceNotFound', { detail: detail || '' })
    } else if (status >= 500) {
      console.error('Server error:', detail)
      _notifyUser('error', 'common.apiServerError')
    } else if (!error.response) {
      console.error('Network error: Unable to connect to server')
      _notifyUser('error', 'common.apiNetworkError')
    }
    return Promise.reject(error)
  }
)

const d = (promise) => promise.then(r => r.data)

function normalizeList(data, ...keys) {
  if (Array.isArray(data)) return data
  if (data && typeof data === 'object') {
    for (const k of keys) {
      if (Array.isArray(data[k])) return data[k]
    }
    if (data.code === 0 && data.data !== undefined) {  // FIXED: handle APIResponse wrapper {code, data, message}
      if (Array.isArray(data.data)) return data.data
      if (data.data && typeof data.data === 'object') return normalizeList(data.data, ...keys)
    }
    const commonKeys = ['items', 'results', 'records', 'list', 'rows']  // FIXED: removed 'data' to avoid false match on APIResponse
    for (const k of commonKeys) {
      if (Array.isArray(data[k])) return data[k]
    }
  }
  console.error('[API] normalizeList: unexpected response format, keys tried:', keys, 'data:', data)
  return []  // FIXED: return empty array instead of null to prevent .forEach/.map crashes in callers
}

export default {
  login: (username, password) => d(api.post('/auth/login', { username, password })),
  refreshToken: (refresh_token) => d(api.post('/auth/refresh', { refresh_token })),
  register: (username, password) => d(api.post('/auth/register', { username, password })),
  listUsers: () => d(api.get('/auth/users')).then(r => normalizeList(r, 'users')),
  changePassword: (username, old_password, new_password) => d(api.post('/auth/change-password', { username, old_password, new_password })),
  adminResetPassword: (username, new_password) => d(api.post(`/auth/admin/reset-password`, { username, new_password })),
  adminUnlockUser: (username) => d(api.post(`/auth/admin/unlock/${username}`)),
  adminUpdateRole: (username, role) => d(api.put(`/auth/users/${username}/role`, { role })),
  deleteUser: (username) => d(api.delete(`/auth/users/${username}`)),

  getProtocols: () => d(api.get('/protocols')).then(r => normalizeList(r, 'protocols')),
  getProtocolInfo: () => d(api.get('/protocols/info')).then(r => {
    if (r && Array.isArray(r.protocols)) return r.protocols  // FIXED: removed dead Array.isArray(r) branch
    return []
  }),
  getProtocolConfig: (name) => d(api.get(`/protocols/${name}/config`)),
  getProtocolDeviceConfig: (name) => d(api.get(`/protocols/${name}/device-config`)),
  startProtocol: (name, config) => {
    const body = (config && Object.keys(config).length > 0) ? config : undefined  // FIXED: empty object {} now treated as no config
    return d(api.post(`/protocols/${name}/start`, body))
  },
  stopProtocol: (name) => d(api.post(`/protocols/${name}/stop`)),
  startAllProtocols: () => d(api.post('/protocols/start-all')),
  stopAllProtocols: () => d(api.post('/protocols/stop-all')),

  getDevices: (protocol) => d(api.get('/devices', { params: { protocol } })).then(r => normalizeList(r, 'devices')),
  getDevice: (id) => d(api.get(`/devices/${id}`)),
  createDevice: (config) => d(api.post('/devices', config)),
  quickCreateDevice: (templateId, name, id, protocolConfig) => d(api.post('/devices/quick-create', { template_id: templateId, name, id, protocol_config: protocolConfig || {} })),
  getDeviceConfig: (id) => d(api.get(`/devices/${id}/config`)),
  updateDevice: (id, config) => d(api.put(`/devices/${id}`, config)),
  deleteDevice: (id) => d(api.delete(`/devices/${id}`)),
  startDevice: (id) => d(api.post(`/devices/${id}/start`)),
  stopDevice: (id) => d(api.post(`/devices/${id}/stop`)),
  getDevicePoints: (id) => d(api.get(`/devices/${id}/points`)).then(r => normalizeList(r, 'points')),
  getDeviceConnectionGuide: (id) => d(api.get(`/devices/${id}/connection-guide`)),
  writeDevicePoint: (id, point, value) => d(api.put(`/devices/${id}/points/${point}`, { value })),
  batchCreateDevices: (configs) => d(api.post('/devices/batch', configs)),
  batchDeleteDevices: (ids) => d(api.post('/devices/batch/delete', { device_ids: ids })),  // FIXED: changed from DELETE to POST
  batchStartDevices: (ids) => d(api.post('/devices/batch/start', { device_ids: ids })),
  batchStopDevices: (ids) => d(api.post('/devices/batch/stop', { device_ids: ids })),

  getTemplates: (protocol) => d(api.get('/templates', { params: { protocol } })).then(r => normalizeList(r, 'templates')),
  getTemplate: (id) => d(api.get(`/templates/${id}`)),
  createTemplate: (template) => d(api.post('/templates', template)),
  deleteTemplate: (id) => d(api.delete(`/templates/${id}`)),
  updateTemplate: (id, data) => d(api.put(`/templates/${id}`, data)),
  searchTemplates: (params) => d(api.get('/templates/search', { params })).then(r => normalizeList(r, 'templates')),
  listTemplateTags: () => d(api.get('/templates/tags')).then(r => {
    if (r && Array.isArray(r.tags)) return r.tags  // FIXED: removed dead Array.isArray(r) branch
    return []
  }),
  instantiateTemplate: (id, params) => {
    const genId = () => 'dev-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    if (!params) return d(api.post(`/templates/${id}/instantiate`, null, { params: { device_id: genId(), device_name: 'Device' } }))
    const { device_id, device_name, protocol_config } = params
    return d(api.post(`/templates/${id}/instantiate`, protocol_config ? { protocol_config } : null, { params: { device_id: device_id || genId(), device_name: device_name || 'Device' } }))
  },

  getScenarios: () => d(api.get('/scenarios')).then(r => normalizeList(r, 'scenarios')),
  createScenario: (config) => d(api.post('/scenarios', config)),
  getScenario: (id) => d(api.get(`/scenarios/${id}`)),
  updateScenario: (id, config) => d(api.put(`/scenarios/${id}`, config)),
  deleteScenario: (id) => d(api.delete(`/scenarios/${id}`)),
  startScenario: (id) => d(api.post(`/scenarios/${id}/start`)),
  stopScenario: (id) => d(api.post(`/scenarios/${id}/stop`)),
  exportScenario: (id) => d(api.get(`/scenarios/${id}/export`)),
  importScenario: (config) => d(api.post('/scenarios/import', config)),
  getScenarioSnapshot: (id) => d(api.get(`/scenarios/${id}/snapshot`)),

  getLogs: (params) => d(api.get('/logs', { params })).then(r => normalizeList(r, 'entries')),
  clearLogs: () => d(api.delete('/logs')),

  createTestCase: (data) => d(api.post('/tests/cases', data)),
  listTestCases: (params) => d(api.get('/tests/cases', { params })).then(r => normalizeList(r, 'cases')),
  getTestCase: (id) => d(api.get(`/tests/cases/${id}`)),
  updateTestCase: (id, data) => d(api.put(`/tests/cases/${id}`, data)),
  deleteTestCase: (id) => d(api.delete(`/tests/cases/${id}`)),
  createTestSuite: (data) => d(api.post('/tests/suites', data)),
  listTestSuites: () => d(api.get('/tests/suites')).then(r => normalizeList(r, 'suites')),
  getTestSuite: (id) => d(api.get(`/tests/suites/${id}`)),
  deleteTestSuite: (id) => d(api.delete(`/tests/suites/${id}`)),
  runTests: (cases) => d(api.post('/tests/run', { test_cases: cases })),  // FIXED: wrap in object for explicit contract
  runTestCase: (id) => d(api.post(`/tests/run/case/${id}`)),
  runTestSuite: (id) => d(api.post(`/tests/run/suite/${id}`)),
  quickTest: (scope, targetId) => d(api.post('/tests/quick-test', null, { params: { scope, target_id: targetId || undefined } })),
  getTestSuggestions: () => d(api.get('/tests/suggestions')).then(r => normalizeList(r, 'suggestions')),
  getTestActionTypes: () => d(api.get('/tests/action-types')).then(r => normalizeList(r, 'action_types')),
  getTestAssertionTypes: () => d(api.get('/tests/assertion-types')).then(r => normalizeList(r, 'assertion_types')),
  listTestReports: () => d(api.get('/tests/reports')).then(r => normalizeList(r, 'reports')),
  getTestReport: (id) => d(api.get(`/tests/reports/${id}`)),
  getTestReportHtml: (id, token) => {
    const params = token ? { token } : {}  // FIXED: support token query param for browser access
    return api.get(`/tests/reports/${id}/html`, { params, transformResponse: [r => r] }).then(r => r.data)
  },
  getReportTrend: (params) => d(api.get('/tests/reports/trend', { params })).then(r => normalizeList(r, 'trends')),

  importEdgelite: (config) => d(api.post('/integration/edgelite', config)),
  importPygbsentry: (config) => d(api.post('/integration/pygbsentry', config)),
  pushToEdgelite: (deviceId) => d(api.post(`/integration/edgelite/push/${deviceId}`)),
  removeDeviceFromEdgelite: (deviceId) => d(api.delete(`/integration/edgelite/push/${deviceId}`)),
  getEdgeliteDeviceStatus: (deviceId) => d(api.get(`/integration/edgelite/status/${deviceId}`)),
  readEdgeliteDevicePoints: (deviceId) => d(api.get(`/integration/edgelite/points/${deviceId}`)).then(r => normalizeList(r, 'points')),
  verifyEdgelitePipeline: (deviceId) => d(api.get(`/integration/edgelite/pipeline/${deviceId}`)),
  testEdgeliteConnection: (config) => d(api.post('/integration/edgelite/test', config)),

  getIntegrationStatus: () => d(api.get('/integration/status')),
  getIntegrationMetrics: () => d(api.get('/integration/metrics')),
  getIntegrationProtocols: () => d(api.get('/integration/protocols')),
  validateDeviceCompatibility: (data) => d(api.post('/integration/validate', data)),  // FIXED: removed redundant config->driver_config remap, backend handles both
  batchPushDevices: (data) => d(api.post('/integration/batch-push', data)),
  startIntegrationDevice: (deviceId) => d(api.post(`/integration/device/${deviceId}/start`)),
  stopIntegrationDevice: (deviceId) => d(api.post(`/integration/device/${deviceId}/stop`)),
  getBackhaulData: (params) => d(api.get('/integration/backhaul-data', { params })),
  getDeviceStatusCache: () => d(api.get('/integration/device-status')),
  getAlarmRules: () => d(api.get('/integration/alarm-rules')).then(r => normalizeList(r, 'rules')),
  addAlarmRule: (data) => d(api.post('/integration/alarm-rules', data)),
  deleteAlarmRule: (ruleId) => d(api.delete(`/integration/alarm-rules/${ruleId}`)),
  sendIntegrationMessage: (type, payload) => d(api.post('/integration/message', { type, payload })),

  createDeviceWs: () => {
    try {  // FIXED: 添加try-catch防止WebSocket创建失败崩溃
      const token = localStorage.getItem('token')
      if (!token) { console.warn('No auth token available, WebSocket connection will be rejected by server'); return null }
      const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = window.location.host
      const url = `${wsProto}://${host}/api/v1/ws/devices?token=${encodeURIComponent(token)}`
      return new WebSocket(url)
    } catch (e) {
      console.error('Failed to create device WebSocket:', e)
      return null
    }
  },

  createLogWs: () => {
    try {  // FIXED: 添加try-catch防止WebSocket创建失败崩溃
      const token = localStorage.getItem('token')
      if (!token) { console.warn('No auth token available, WebSocket connection will be rejected by server'); return null }
      const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = window.location.host
      const url = `${wsProto}://${host}/api/v1/ws/logs?token=${encodeURIComponent(token)}`
      return new WebSocket(url)
    } catch (e) {
      console.error('Failed to create log WebSocket:', e)
      return null
    }
  },

  ensureValidToken: async () => {
    const token = localStorage.getItem('token')
    if (!token) return false
    try {
      const parts = token.split('.')
      if (parts.length === 3) {
        let payload
        try {
          const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
          payload = JSON.parse(decodeURIComponent(atob(base64).split('').map(c =>
            '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
          ).join('')))
        } catch {
          console.warn('JWT payload parse failed, treating token as invalid')
          return false
        }
        const exp = payload.exp || 0
        const now = Math.floor(Date.now() / 1000)
        if (exp - now < TOKEN_REFRESH_THRESHOLD_SEC) {  // FIXED: use named constant
          const refreshToken = localStorage.getItem('refresh_token')
          if (refreshToken) {
            const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
            if (res.data.access_token) {
              localStorage.setItem('token', res.data.access_token)
              if (res.data.refresh_token) localStorage.setItem('refresh_token', res.data.refresh_token)
              if (res.data.username) localStorage.setItem('username', res.data.username)
              if (res.data.role) localStorage.setItem('role', res.data.role)
              return true
            }
          }
          return false
        }
      }
      return true
    } catch {
      console.warn('Token validation failed, treating as invalid')
      return false
    }
  },

  listForwardTargets: () => d(api.get('/forward/targets')).then(r => normalizeList(r, 'targets')),
  addForwardTarget: (config) => d(api.post('/forward/targets', config)),
  removeForwardTarget: (name) => d(api.delete(`/forward/targets/${name}`)),
  startForward: () => d(api.post('/forward/start')),
  stopForward: () => d(api.post('/forward/stop')),
  getForwardStats: () => d(api.get('/forward/stats')),

  startRecording: (config) => d(api.post('/recorder/start', config)),
  stopRecording: () => d(api.post('/recorder/stop')),
  listRecordings: () => d(api.get('/recorder/recordings')).then(r => normalizeList(r, 'recordings')),
  getRecording: (id) => d(api.get(`/recorder/recordings/${id}`)),
  deleteRecording: (id) => d(api.delete(`/recorder/recordings/${id}`)),
  replayRecording: (id, config) => d(api.post(`/recorder/recordings/${id}/replay`, config)),
  exportRecording: (id) => d(api.get(`/recorder/recordings/${id}/export`)),
  getRecorderStats: () => d(api.get('/recorder/stats')),

  listWebhooks: () => d(api.get('/webhooks')).then(r => normalizeList(r, 'webhooks')),
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
  deleteAuditEntry: (id) => d(api.delete(`/audit/${Number(id)}`)),
  clearAuditLog: (before) => d(api.delete('/audit', { params: before ? { before } : {} })),

  exportBackup: () => api.get('/backup', { responseType: 'blob' }).then(r => {
    const disposition = r.headers['content-disposition']
    let filename = 'protoforge-backup.json'
    if (disposition) {
      const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
      if (match && match[1]) filename = match[1].replace(/['"]/g, '')
    }
    const url = URL.createObjectURL(r.data)
    try {  // FIXED: DOM operations wrapped in try-finally to ensure URL.revokeObjectURL always runs
      const a = document.createElement('a')
      a.href = url; a.download = filename; document.body.appendChild(a); a.click()
      document.body.removeChild(a)
    } finally {
      URL.revokeObjectURL(url)
    }
    return { downloaded: true, filename }
  }),
  importBackup: (backup) => d(api.post('/backup/restore', backup)),  // FIXED: renamed param from 'data' to 'backup' for clarity

  getHealth: () => api.get('/health').then(r => r.data).catch(() => null),
}
