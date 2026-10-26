import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import axios from 'axios'
import naive from 'naive-ui'
import App from './App.vue'

const NotFound = () => import('./views/NotFound.vue')

const routes = [
  { path: '/', component: () => import('./views/Dashboard.vue'), meta: { public: true } },
  { path: '/welcome', component: () => import('./views/Welcome.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/devices', component: () => import('./views/Devices.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/protocols', component: () => import('./views/Protocols.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/templates', component: () => import('./views/Templates.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/scenarios', component: () => import('./views/Scenarios.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/scenario-editor', component: () => import('./views/ScenarioEditor.vue'), meta: { roles: ['admin', 'operator', 'user'] } },
  { path: '/scenario/:id', component: () => import('./views/ScenarioEditor.vue'), meta: { roles: ['admin', 'operator', 'user'] } },
  { path: '/marketplace', component: () => import('./views/Marketplace.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/logs', component: () => import('./views/Logs.vue'), meta: { roles: ['admin', 'operator', 'user', 'viewer'] } },
  { path: '/testing', component: () => import('./views/Testing.vue'), meta: { roles: ['admin', 'operator', 'user'] } },
  { path: '/test-plans', component: () => import('./views/TestPlans.vue'), meta: { roles: ['admin', 'operator', 'user'] } },
  { path: '/compliance', component: () => import('./views/Compliance.vue'), meta: { roles: ['admin', 'operator', 'user'] } },
  { path: '/integration', component: () => import('./views/Integration.vue'), meta: { roles: ['admin', 'operator'] } },
  { path: '/settings', component: () => import('./views/Settings.vue'), meta: { roles: ['admin'] } },
  { path: '/audit', component: () => import('./views/Audit.vue'), meta: { roles: ['admin'] } },
  { path: '/backup', component: () => import('./views/Backup.vue'), meta: { roles: ['admin'] } },
  { path: '/forward', component: () => import('./views/Forward.vue'), meta: { roles: ['admin', 'operator'] } },
  { path: '/recorder', component: () => import('./views/Recorder.vue'), meta: { roles: ['admin', 'operator'] } },
  { path: '/webhook', component: () => import('./views/Webhook.vue'), meta: { roles: ['admin', 'operator'] } },
  { path: '/:pathMatch(.*)*', component: NotFound },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// FIXED(IKQA71): 访问端与服务器时钟不一致（本机比服务器快 ≥ token 有效期）时，
// 刚签发的 token 在浏览器侧已 "过期"。原实现在此处直接清空 token，导致
// "登录后点任何页面都被踢回登录页"（Gitee issue IKQA71）。现在先尝试用
// refresh_token 静默续期（服务端校验与时钟无关），续期失败才清空，
// 并输出自解释日志帮助定位时钟偏差。
function _clearAuthStorage() {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('username')
  localStorage.removeItem('role')
}

function _decodeJwtPayload(token) {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('invalid JWT format')
  const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
  return JSON.parse(decodeURIComponent(atob(base64).split('').map(c =>
    '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
  ).join('')))
}

async function _tryRefreshSession() {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return false
  try {
    const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
    if (res.data?.access_token && typeof res.data.access_token === 'string') {
      localStorage.setItem('token', res.data.access_token)
      if (res.data.refresh_token) localStorage.setItem('refresh_token', res.data.refresh_token)
      if (res.data.username) localStorage.setItem('username', res.data.username)
      if (res.data.role) localStorage.setItem('role', res.data.role)
      return true
    }
  } catch (e) {
    console.warn('[auth] refresh_token 续期失败：', e?.response?.status || e?.message)
  }
  return false
}

router.beforeEach(async (to, from, next) => {
  const token = localStorage.getItem('token')
  const userRole = localStorage.getItem('role') || 'viewer'

  if (to.meta?.public) {
    next()
    return
  }

  if (!token) {
    next('/')
    return
  }

  let payload = null
  try {
    payload = _decodeJwtPayload(token)
  } catch (e) {
    console.warn('[auth] token 解析失败，清除登录态：', e?.message)
    _clearAuthStorage()
    next('/')
    return
  }

  const nowSec = Date.now() / 1000
  if (payload.exp && payload.exp < nowSec) {
    const skewMin = Math.round((nowSec - payload.exp) / 6) / 10
    console.warn(
      `[auth] token 在本机侧判定为已过期：exp=${payload.exp}，本机时间=${Math.floor(nowSec)}，` +
      `本机比服务器快约 ${skewMin} 分钟。若刚登录就出现此提示，说明两端时钟不一致，` +
      `请校准系统时间。正在尝试用 refresh_token 续期…`)
    if (await _tryRefreshSession()) {
      next()
      return
    }
    _clearAuthStorage()
    next('/')
    return
  }

  if (to.meta?.roles && !to.meta.roles.includes(userRole)) {
    console.warn(`Access to ${to.path} requires role: ${to.meta.roles.join(', ')}, current role: ${userRole}`)  // FIXED: Chinese log→English
    next('/')
    return
  }

  next()
})

const app = createApp(App)
app.config.errorHandler = (err, instance, info) => {
  console.error('Vue error:', err, info)
}
app.use(router)
app.use(naive)
app.mount('#app')
