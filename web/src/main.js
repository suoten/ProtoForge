import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
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

router.beforeEach((to, from, next) => {
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

  try {
    const parts = token.split('.')
    if (parts.length !== 3) throw new Error('invalid JWT format')
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(decodeURIComponent(atob(base64).split('').map(c =>
      '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
    ).join('')))  // FIXED: proper Base64url decoding with Unicode support
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      next('/')
      return
    }
  } catch {
    localStorage.removeItem('token')
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
