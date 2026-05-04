<template>
  <n-message-provider>
    <n-dialog-provider>
      <div v-if="!loggedIn" class="login-wrapper">
        <Login @login-success="onLogin" />
      </div>
      <n-layout v-else has-sider class="app-layout">
        <n-layout-sider
          bordered
          :width="220"
          :collapsed-width="64"
          collapse-mode="width"
          :collapsed="collapsed"
          show-trigger
          @collapse="collapsed = true"
          @expand="collapsed = false"
          :native-scrollbar="false"
          class="app-sider"
        >
          <div class="sider-logo" @click="$router.push('/')">
            <svg v-if="!collapsed" viewBox="0 0 512 512" width="28" height="28">
              <defs><linearGradient id="logoBg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f46e5"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs>
              <rect width="512" height="512" rx="96" fill="url(#logoBg)"/>
              <g transform="translate(256,256)" fill="none" stroke="white" stroke-width="12">
                <polygon points="0,-130 112.6,-65 112.6,65 0,130 -112.6,65 -112.6,-65" opacity="0.3"/>
                <polygon points="0,-85 73.6,-42.5 73.6,42.5 0,85 -73.6,42.5 -73.6,-42.5" opacity="0.5"/>
              </g>
              <g transform="translate(256,256)">
                <circle r="24" fill="white" opacity="0.9"/>
                <circle r="14" fill="#fbbf24"/>
              </g>
            </svg>
            <span v-if="!collapsed" class="logo-text">ProtoForge</span>
            <svg v-else viewBox="0 0 512 512" width="28" height="28">
              <defs><linearGradient id="logoBg2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f46e5"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs>
              <rect width="512" height="512" rx="96" fill="url(#logoBg2)"/>
              <g transform="translate(256,256)">
                <circle r="24" fill="white" opacity="0.9"/>
                <circle r="14" fill="#fbbf24"/>
              </g>
            </svg>
          </div>
          <n-menu
            :value="currentRoute"
            :collapsed="collapsed"
            :collapsed-width="64"
            :collapsed-icon-size="20"
            :options="menuOptions"
            @update:value="navigate"
          />
        </n-layout-sider>
        <n-layout>
          <n-layout-header bordered class="app-header">
            <n-space align="center" size="small">
              <n-auto-complete
                v-model:value="searchQuery"
                :options="searchResults"
                :placeholder="t('header.searchPlaceholder')"
                clearable
                size="small"
                style="width: 280px"
                @select="onSearchSelect"
                @update:value="onSearchInput"
              >
                <template #prefix>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#999" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                </template>
              </n-auto-complete>
            </n-space>
            <n-space align="center" size="medium">
              <n-tag v-if="wsConnected" size="small" :bordered="false" type="success">
                <template #icon><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg></template>
                {{ t('common.online') }}
              </n-tag>
              <n-dropdown :options="langMenuOptions" @select="onLangMenuSelect">
                <n-button quaternary size="small" round>
                  <template #icon>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                  </template>
                  {{ locale === 'zh' ? '中文' : 'EN' }}
                </n-button>
              </n-dropdown>
              <n-dropdown :options="userMenuOptions" @select="onUserMenuSelect">
                <n-button quaternary size="small" round>
                  <template #icon>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                  </template>
                  {{ username }}
                </n-button>
              </n-dropdown>
            </n-space>
          </n-layout-header>
          <n-layout-content class="app-content">
            <router-view />
            <Welcome />
          </n-layout-content>
        </n-layout>
      </n-layout>

      <n-modal
    v-model:show="showChangePassword"
    :title="t('password.title')"
    preset="card"
    style="width: 420px"
    :mask-closable="false"
  >
    <n-space vertical>
      <n-input
        v-model:value="oldPassword"
        type="password"
        :placeholder="t('password.oldPassword')"
        show-password-on="click"
      />
      <n-input
        v-model:value="newPassword"
        type="password"
        :placeholder="t('password.newPassword')"
        show-password-on="click"
      />
      <n-input
        v-model:value="confirmPassword"
        type="password"
        :placeholder="t('password.confirmPassword')"
        show-password-on="click"
      />
    </n-space>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showChangePassword = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="changePasswordLoading" @click="handleChangePassword">{{ t('password.submit') }}</n-button>
      </n-space>
    </template>
  </n-modal>
    </n-dialog-provider>
  </n-message-provider>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NSpace, NAutoComplete, NTag, NButton, NDropdown, NModal, NInput } from 'naive-ui'
import { useI18n } from './i18n.js'
import { createDiscreteApi } from 'naive-ui'
import api from './api.js'
import Login from './views/Login.vue'
import Welcome from './views/Welcome.vue'

const router = useRouter()
const route = useRoute()
const message = createDiscreteApi(['message']).message
const { t, locale, setLocale } = useI18n()
const loggedIn = ref(!!localStorage.getItem('token'))
const collapsed = ref(false)
const username = ref(localStorage.getItem('username') || 'admin')
const searchQuery = ref('')
const searchResults = ref([])
const searchData = ref({ devices: [], templates: [], scenarios: [] })
const wsConnected = ref(false)
const logMessages = ref([])
let ws = null

const currentRoute = computed(() => route.path)

function svgIcon(pathD, color = 'currentColor') {
  return () => h('svg', { viewBox: '0 0 24 24', width: '18', height: '18', fill: 'none', stroke: color, 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
    h('path', { d: pathD })
  ])
}

const menuOptions = computed(() => [
  { label: t('nav.dashboard'), key: '/', icon: svgIcon('M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M9 22V12h6v10') },
  { label: t('nav.devices'), key: '/devices', icon: svgIcon('M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z') },
  { label: t('nav.protocols'), key: '/protocols', icon: svgIcon('M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5') },
  { label: t('nav.scenarios'), key: '/scenarios', icon: svgIcon('M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9') },
  { label: t('nav.scenarioEditor'), key: '/scenario-editor', icon: svgIcon('M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7 M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z') },
  { label: t('nav.marketplace'), key: '/marketplace', icon: svgIcon('M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z M3.27 6.96L12 12.01l8.73-5.05 M12 22.08V12') },
  { label: t('nav.testing'), key: '/testing', icon: svgIcon('M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11') },
  { label: t('nav.logs'), key: '/logs', icon: svgIcon('M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8') },
  { label: t('nav.integration'), key: '/integration', icon: svgIcon('M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14L21 3') },
  { label: t('nav.settings'), key: '/settings', icon: svgIcon('M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z') },
  { label: t('nav.forward'), key: '/forward', icon: svgIcon('M22 12h-4l-3 9L9 3l-3 9H2') },
  { label: t('nav.recorder'), key: '/recorder', icon: svgIcon('M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 6v6l4 2') },
  { label: t('nav.webhook'), key: '/webhook', icon: svgIcon('M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14L21 3') },
  { label: t('nav.audit'), key: '/audit', icon: svgIcon('M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z') },
  { label: t('nav.backup'), key: '/backup', icon: svgIcon('M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3') },
])

const userMenuOptions = computed(() => [
  { label: t('header.changePassword'), key: 'change-password' },
  { label: t('header.logout'), key: 'logout' },
])

const langMenuOptions = [
  { label: '中文', key: 'zh' },
  { label: 'English', key: 'en' },
]

function onLangMenuSelect(key) {
  setLocale(key)
}

function navigate(key) {
  router.push(key)
}

function onLogin() {
  loggedIn.value = true
  username.value = localStorage.getItem('username') || 'admin'
}

const showChangePassword = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changePasswordLoading = ref(false)

function onUserMenuSelect(key) {
  if (key === 'logout') {
    if (ws) { ws.close(); ws = null }
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('username')
    localStorage.removeItem('role')
    loggedIn.value = false
  } else if (key === 'change-password') {
    showChangePassword.value = true
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  }
}

onMounted(() => {
  if (loggedIn.value) {
    loadSearchData()
    connectWebSocket()
  }
})

onUnmounted(() => {
  if (ws) { ws.close(); ws = null }
})

async function handleChangePassword() {
  if (!oldPassword.value || !newPassword.value || !confirmPassword.value) {
    message.error(t('password.allRequired'))
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    message.error(t('password.mismatch'))
    return
  }
  if (newPassword.value.length < 6) {
    message.error(t('password.tooShort'))
    return
  }
  changePasswordLoading.value = true
  try {
    const currentUser = localStorage.getItem('username') || 'admin'
    await api.changePassword(currentUser, oldPassword.value, newPassword.value)
    message.success(t('password.success'))
    showChangePassword.value = false
    setTimeout(() => {
      if (ws) { ws.close(); ws = null }
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      loggedIn.value = false
    }, 1500)
  } catch (e) {
    message.error(e.response?.data?.detail || t('password.failed'))
  } finally {
    changePasswordLoading.value = false
  }
}

function onSearchInput(query) {
  if (!query) { searchResults.value = []; return }
  const q = query.toLowerCase()
  const results = []
  for (const d of searchData.value.devices) {
    if ((d.name || '').toLowerCase().includes(q) || (d.id || '').toLowerCase().includes(q))
      results.push({ label: `[设备] ${d.name || d.id}`, value: `/devices` })
  }
  for (const tmpl of searchData.value.templates) {
    if ((tmpl.name || '').toLowerCase().includes(q))
      results.push({ label: `[模板] ${tmpl.name}`, value: `/marketplace` })
  }
  for (const s of searchData.value.scenarios) {
    if ((s.name || '').toLowerCase().includes(q))
      results.push({ label: `[场景] ${s.name}`, value: `/scenarios` })
  }
  searchResults.value = results.slice(0, 10)
}

function onSearchSelect(val) {
  router.push(val)
  searchQuery.value = ''
}

let wsReconnectDelay = 1000
const WS_MAX_RECONNECT_DELAY = 30000

function connectWebSocket() {
  if (!loggedIn.value) return
  ws = api.createLogWs()
  ws.onopen = () => { wsConnected.value = true; wsReconnectDelay = 1000 }
  ws.onclose = () => {
    wsConnected.value = false
    if (loggedIn.value) {
      setTimeout(connectWebSocket, wsReconnectDelay)
      wsReconnectDelay = Math.min(wsReconnectDelay * 2, WS_MAX_RECONNECT_DELAY)
    }
  }
  ws.onerror = () => { wsConnected.value = false }
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'log') {
        logMessages.value.push(msg.data)
        if (logMessages.value.length > 500) logMessages.value = logMessages.value.slice(-500)
      }
    } catch (e) { console.warn('WebSocket日志消息解析失败:', e) }
  }
}

async function loadSearchData() {
  try {
    const [devRes, tmplRes, scRes] = await Promise.all([
      api.getDevices(), api.getTemplates(), api.getScenarios(),
    ])
    searchData.value = {
      devices: devRes || [],
      templates: tmplRes || [],
      scenarios: scRes || [],
    }
  } catch (e) { console.warn('加载搜索数据失败:', e) }
}
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
  --pf-primary: #6366f1;
  --pf-primary-light: #818cf8;
  --pf-accent: #8b5cf6;
  --pf-success: #10b981;
  --pf-warning: #f59e0b;
  --pf-danger: #ef4444;
  --pf-bg: #f8fafc;
  --pf-sider-bg: #ffffff;
  --pf-header-bg: #ffffff;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--pf-bg);
  -webkit-font-smoothing: antialiased;
}

.app-layout { height: 100vh; }

.app-sider {
  background: var(--pf-sider-bg) !important;
  box-shadow: 2px 0 8px rgba(0,0,0,0.04);
}

.sider-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.sider-logo:hover { opacity: 0.8; }

.logo-text {
  font-size: 18px;
  font-weight: 700;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.5px;
}

.app-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--pf-header-bg) !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}

.app-content {
  padding: 24px;
  background: var(--pf-bg) !important;
  min-height: calc(100vh - 56px);
}

.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.n-menu .n-menu-item-content::before {
  border-radius: 8px !important;
  margin: 2px 8px !important;
}

.n-card {
  border-radius: 12px !important;
  border: 1px solid rgba(0,0,0,0.06) !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
  transition: all 0.2s ease;
}

.n-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08) !important;
}

.n-button--primary-type {
  background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
  border: none !important;
  font-weight: 500 !important;
}

.n-button--success-type {
  background: linear-gradient(135deg, #10b981, #059669) !important;
  border: none !important;
}

.n-tag--success-type {
  background: rgba(16,185,129,0.1) !important;
  color: #059669 !important;
  border-color: rgba(16,185,129,0.2) !important;
}

.n-tag--error-type {
  background: rgba(239,68,68,0.1) !important;
  color: #dc2626 !important;
  border-color: rgba(239,68,68,0.2) !important;
}

.n-tag--warning-type {
  background: rgba(245,158,11,0.1) !important;
  color: #d97706 !important;
  border-color: rgba(245,158,11,0.2) !important;
}

.n-tag--info-type {
  background: rgba(99,102,241,0.1) !important;
  color: #6366f1 !important;
  border-color: rgba(99,102,241,0.2) !important;
}

.n-data-table .n-data-table-th {
  font-weight: 600 !important;
  font-size: 12px !important;
  text-transform: uppercase !important;
  letter-spacing: 0.5px !important;
  color: #64748b !important;
}

.n-input, .n-select {
  border-radius: 8px !important;
}

.n-modal .n-card {
  border-radius: 16px !important;
}

.n-tabs .n-tabs-tab {
  font-weight: 500 !important;
}

.pf-gradient-card {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
  color: white !important;
  border: none !important;
}

.pf-gradient-card-green {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
  color: white !important;
  border: none !important;
}

.pf-gradient-card-orange {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%) !important;
  color: white !important;
  border: none !important;
}

.pf-gradient-card-rose {
  background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%) !important;
  color: white !important;
  border: none !important;
}

.pf-stat-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -1px;
}

.pf-section-title {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  letter-spacing: -0.3px;
}

.pf-section-desc {
  font-size: 13px;
  color: #94a3b8;
  margin-top: 2px;
}
</style>
