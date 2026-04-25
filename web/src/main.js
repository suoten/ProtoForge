import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import naive from 'naive-ui'
import App from './App.vue'

const NotFound = () => import('./views/NotFound.vue')

const routes = [
  { path: '/', component: () => import('./views/Dashboard.vue') },
  { path: '/devices', component: () => import('./views/Devices.vue') },
  { path: '/protocols', component: () => import('./views/Protocols.vue') },
  { path: '/templates', component: () => import('./views/Templates.vue') },
  { path: '/scenarios', component: () => import('./views/Scenarios.vue') },
  { path: '/scenario-editor', component: () => import('./views/ScenarioEditor.vue') },
  { path: '/marketplace', component: () => import('./views/Marketplace.vue') },
  { path: '/logs', component: () => import('./views/Logs.vue') },
  { path: '/testing', component: () => import('./views/Testing.vue') },
  { path: '/integration', component: () => import('./views/Integration.vue') },
  { path: '/settings', component: () => import('./views/Settings.vue') },
  { path: '/:pathMatch(.*)*', component: NotFound },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const app = createApp(App)
app.use(router)
app.use(naive)
app.mount('#app')
