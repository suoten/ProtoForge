import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import naive from 'naive-ui'
import App from './App.vue'

const NotFound = () => import('./views/NotFound.vue')

const routes = [
  { path: '/', component: () => import('./views/Dashboard.vue'), meta: { public: true } },
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
  history: createWebHistory(),
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

  if (to.meta?.roles && !to.meta.roles.includes(userRole)) {
    next('/')
    return
  }

  next()
})

const app = createApp(App)
app.use(router)
app.use(naive)
app.mount('#app')
