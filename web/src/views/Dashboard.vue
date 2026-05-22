<template>
  <div>
    <n-spin :show="loading">
      <n-space vertical size="large">

        <n-grid :cols="4" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card class="pf-gradient-card" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">{{ t('dashboard.totalDevices') }}</div>
                  <div class="pf-stat-value">{{ devices.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ onlineDevices }} {{ t('dashboard.onlineDevices') }}</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-green" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">{{ t('dashboard.runningProtocols') }}</div>
                  <div class="pf-stat-value">{{ runningProtocols }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ t('dashboard.totalProtocols', { n: protocols.length }) }}</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-orange" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">{{ t('dashboard.simulationScenarios') }}</div>
                  <div class="pf-stat-value">{{ scenarios.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ runningScenarios }} {{ t('dashboard.runningScenarios') }}</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-rose" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">{{ t('dashboard.deviceTemplates') }}</div>
                  <div class="pf-stat-value">{{ templates.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ t('dashboard.coverProtocols', { n: protocols.length }) }}</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-grid :cols="2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                  <span class="pf-section-title" style="font-size:16px">{{ t('dashboard.quickActions') }}</span>
                </n-space>
              </template>
              <n-space vertical size="small">
                <n-button type="primary" block size="large" @click="startAllProtocols" :loading="startingAll">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
                  {{ t('dashboard.startAllProtocols') }}
                </n-button>
                <n-button block size="large" @click="$router.push('/marketplace')">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></template>
                  {{ t('dashboard.createFromTemplate') }}
                </n-button>
                <n-button block size="large" @click="$router.push('/testing')">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></template>
                  {{ t('dashboard.quickSimTest') }}
                </n-button>
              </n-space>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8"/></svg>
                  <span class="pf-section-title" style="font-size:16px">{{ t('dashboard.recentLogs') }}</span>
                </n-space>
              </template>
              <n-space vertical size="small" style="max-height:200px;overflow-y:auto">
                <div v-for="log in recentLogs.slice(0, 8)" :key="log.timestamp"
                  style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f1f5f9">
                  <div :style="{ width:'6px',height:'6px',borderRadius:'50%',background: directionColorMap[log.direction]||'#94a3b8',flexShrink:0 }"></div>
                <span style="font-size:11px;color:#94a3b8;min-width:60px">{{ formatTime(log.timestamp) }}</span>
                <n-tag size="tiny" :type="directionTagTypeMap[log.direction]||'default'" :bordered="false">{{ log.protocol }}</n-tag>
                  <span style="font-size:12px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ log.summary }}</span>
                </div>
                <n-text v-if="!recentLogs.length" depth="3" style="font-size:12px">{{ t('dashboard.noLogs') }}</n-text>
              </n-space>
            </n-card>
          </n-gi>
        </n-grid>

        <n-alert v-if="loadError" type="error" style="margin-bottom:12px">
          {{ t('dashboard.loadFailed') }}: {{ loadError }}
          <n-button size="tiny" @click="loadData" style="margin-left:8px">{{ t('common.retry') }}</n-button>
        </n-alert>

        <n-card size="small" v-if="healthInfo">
          <template #header>
            <n-space align="center" size="small">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
              <span class="pf-section-title" style="font-size:16px">{{ t('dashboard.deviceOverview') }}</span>
            </n-space>
          </template>
          <n-space size="large" align="center">
            <n-tag :type="healthInfo.status === 'ok' ? 'success' : 'warning'" size="small" :bordered="false">
              {{ healthInfo.status === 'ok' ? t('common.running') : t('common.warning') }}
            </n-tag>
            <n-text depth="3" style="font-size:12px">
              {{ t('settings.database') }}: <n-tag :type="healthInfo.database ? 'success' : 'error'" size="tiny" :bordered="false">{{ healthInfo.database ? t('common.running') : t('common.abnormal') }}</n-tag>
            </n-text>
            <n-text depth="3" style="font-size:12px">
              Engine: <n-tag :type="healthInfo.engine ? 'success' : 'error'" size="tiny" :bordered="false">{{ healthInfo.engine ? t('common.running') : t('common.abnormal') }}</n-tag>
            </n-text>
            <n-text depth="3" style="font-size:12px" v-if="healthInfo.protocols">
              {{ t('common.protocol') }}: {{ healthInfo.protocols.running || 0 }}/{{ healthInfo.protocols.total || 0 }} {{ t('common.running') }}
            </n-text>
            <n-button size="tiny" quaternary @click="openMetrics">
              <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14L21 3"/></svg></template>
              Prometheus
            </n-button>
          </n-space>
        </n-card>

        <n-card v-if="devices.length === 0 && !loading" size="small">
          <n-space vertical align="center" style="padding:32px 0">
            <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <div class="pf-section-title" style="font-size:16px">{{ t('dashboard.noDevices') }}</div>
            <div class="pf-section-desc">{{ t('dashboard.quickStart') }}</div>
            <n-button type="primary" @click="$router.push('/marketplace')">{{ t('dashboard.goToMarketplace') }}</n-button>
          </n-space>
        </n-card>

        <n-card v-else-if="devices.length > 0" size="small">
          <template #header>
            <n-space align="center" size="small">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              <span class="pf-section-title" style="font-size:16px">{{ t('dashboard.deviceOverview') }}</span>
            </n-space>
          </template>
          <n-data-table :columns="deviceColumns" :data="devices" :bordered="false" size="small"
            :pagination="devices.length > 10 ? { pageSize: 10 } : false" />
        </n-card>

      </n-space>
    </n-spin>

    <!-- Start Progress Modal -->
    <n-modal v-model:show="showProgressModal" :mask-closable="false" :close-on-esc="false" preset="card"
      :title="progressDone ? t('protocols.batchSuccessTitle') : t('protocols.batchStartingTitle')" style="width: 520px">
      <div style="min-height: 120px">
        <div style="margin-bottom:12px">
          <n-progress :percentage="batchPercentage" :show-indicator="true"
            :status="batchHasError ? 'warning' : 'success'"
            :height="8" :border-radius="4" />
          <div style="text-align:center;margin-top:8px;font-size:13px;color:#64748b">
            {{ t('protocols.batchProgress', { current: batchCurrent, total: batchTotal }) }}
          </div>
        </div>
        <div style="max-height:240px;overflow-y:auto">
          <div v-for="item in batchItems" :key="item.name"
            :style="{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'8px 12px', borderRadius:'8px', marginBottom:'4px', background: item.status === 'active' ? '#f0f9ff' : item.status === 'success' ? '#f0fdf4' : item.status === 'error' ? '#fef2f2' : 'transparent', transition: 'all 0.3s ease' }">
            <div style="display:flex;align-items:center;gap:8px">
              <div :style="{ width:'8px',height:'8px',borderRadius:'50%',background: item.status === 'success' ? '#18a058' : item.status === 'error' ? '#d03050' : item.status === 'active' ? '#2080f0' : '#c0c4cc', transition: 'all 0.3s ease' }">
                <div v-if="item.status === 'active'" style="width:8px;height:8px;border-radius:50%;background:#2080f0;animation:pulse 1.5s ease-in-out infinite"></div>
              </div>
              <span style="font-size:13px;font-weight:500">{{ item.displayName || item.name }}</span>
            </div>
            <n-tag :type="item.status === 'success' ? 'success' : item.status === 'error' ? 'error' : item.status === 'active' ? 'info' : 'default'"
              size="tiny" :bordered="false">
              {{ item.status === 'success' ? t('protocols.batchItemSuccess')
                : item.status === 'error' ? t('protocols.batchItemFailed')
                : item.status === 'active' ? t('protocols.batchItemStarting')
                : t('protocols.batchItemPending') }}
            </n-tag>
          </div>
        </div>
      </div>
      <template #action>
        <n-button v-if="progressDone" type="primary" @click="closeProgressModal">{{ t('common.close') }}</n-button>
        <n-button v-else disabled>{{ t('protocols.batchItemStarting') }}</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { NGrid, NGi, NCard, NSpace, NButton, NDataTable, NTag, NText, NSpin, NAlert, NModal, NProgress, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { protocolLabels, deviceStatusMap, directionColorMap, directionTagTypeMap } from '../constants.js'
import { useI18n } from '../i18n.js'
import { formatTime as _formatTime } from '../utils.js'  // FIXED: 重复定义的格式化函数提取到utils.js

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()
const devices = ref([])
const protocols = ref([])
const templates = ref([])
const scenarios = ref([])
const recentLogs = ref([])
const healthInfo = ref(null)
const loading = ref(true)
const loadError = ref('')
const startingAll = ref(false)

// Progress modal state
const showProgressModal = ref(false)
const progressDone = ref(false)
const batchItems = ref([])
const batchCurrent = ref(0)
const batchTotal = ref(0)
const batchHasError = ref(false)

const batchPercentage = computed(() => {
  if (batchTotal.value === 0) return 0
  return Math.round((batchCurrent.value / batchTotal.value) * 100)
})

function closeProgressModal() {
  showProgressModal.value = false
  progressDone.value = false
  batchItems.value = []
  batchCurrent.value = 0
  batchTotal.value = 0
  batchHasError.value = false
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

let deviceWs = null
let logWs = null
let devWsReconnectTimer = null
let logWsReconnectTimer = null
let devWsReconnectDelay = 1000
let devWsReconnectAttempts = 0
let logWsReconnectDelay = 1000
let logWsReconnectAttempts = 0
let manualClose = false
const WS_MAX_RECONNECT_DELAY = 30000
const WS_MAX_RECONNECT_ATTEMPTS = 20

const onlineDevices = computed(() => devices.value.filter(d => d.status === 'online' || d.status === 'running').length)
const runningProtocols = computed(() => protocols.value.filter(p => p.status === 'running').length)
const runningScenarios = computed(() => scenarios.value.filter(s => s.status === 'running').length)

const deviceColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 160, render: (row) => h('span', { style: 'font-weight:500' }, row.name || row.id) },
  { title: t('common.protocol'), key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => protocolLabels[row.protocol] || row.protocol) },
  {
    title: t('common.status'), key: 'status', width: 100,
    render: (row) => {
      const [type, labelKey] = deviceStatusMap[row.status] || ['default', 'common.offline']  // FIXED: deviceStatusMap标签改用i18n key
      return h(NTag, { size: 'tiny', type, bordered: false }, () => t(labelKey))  // FIXED: deviceStatusMap标签改用i18n key
    }
  },
  { title: t('common.pointCount'), key: 'points', width: 80, render: (row) => row.point_count || (row.points || []).length },
])

// FIXED: 重复定义的格式化函数 — 委托到utils.js统一实现
function formatTime(ts) { return _formatTime(ts) }

async function startAllProtocols() {
  const stopped = protocols.value.filter(p => p.status !== 'running')
  if (!stopped.length) { message.info(t('dashboard.allProtocolsRunning')); return }
  dialog.warning({
    title: t('dashboard.confirmStartAll'),
    content: t('dashboard.startAllWarning', { n: stopped.length }),
    positiveText: t('dashboard.startButton'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      doStartAllProtocols(stopped)
    }
  })
}

async function doStartAllProtocols(stopped) {
  startingAll.value = true
  batchTotal.value = stopped.length
  batchCurrent.value = 0
  batchHasError.value = false
  batchItems.value = stopped.map(p => ({
    name: p.name,
    displayName: p.display_name || p.name,
    status: 'pending'
  }))
  showProgressModal.value = true
  progressDone.value = false

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < stopped.length; i++) {
    const p = stopped[i]
    batchItems.value[i].status = 'active'
    batchCurrent.value = i + 1

    try {
      await api.startProtocol(p.name, null)
      batchItems.value[i].status = 'success'
      successCount++
    } catch (e) {
      batchItems.value[i].status = 'error'
      failCount++
      batchHasError.value = true
    }

    if (i < stopped.length - 1) await delay(200)
  }

  progressDone.value = true
  startingAll.value = false

  if (failCount > 0 && successCount > 0) {
    message.warning(t('dashboard.startedWithFail', { ok: successCount, fail: failCount }))
  } else if (successCount > 0) {
    message.success(t('dashboard.startedCount', { n: successCount }))
  }

  await loadData()
}

async function loadData() {
  loading.value = true
  loadError.value = ''
  try {
    const results = await Promise.allSettled([
    api.getDevices(), api.getProtocols(), api.getTemplates(), api.getScenarios(), api.getLogs({ count: 20 }),
  ])
  devices.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
  protocols.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
  templates.value = results[2].status === 'fulfilled' ? (results[2].value || []) : []
  scenarios.value = results[3].status === 'fulfilled' ? (results[3].value || []) : []
  recentLogs.value = results[4].status === 'fulfilled' ? (results[4].value || []) : []
  const errors = results.filter(r => r.status === 'rejected')
  if (errors.length > 0) message.warning(`${errors.length} ${t('common.loadFailed')}`)
  } catch (e) {
    loadError.value = e.response?.data?.detail || e.message || 'Error'
  } finally {
    loading.value = false
  }
  try {
    const res = await api.getHealth()
    if (res) healthInfo.value = res
  } catch (e) {
    console.debug('Health endpoint unavailable:', e.message)
  }
}

function connectDeviceWs() {
  if (manualClose) return
  try {
    deviceWs = api.createDeviceWs()
    if (!deviceWs) return
  } catch (e) {
    console.error('Failed to create device WebSocket:', e.message)
    devWsReconnectAttempts++
    if (devWsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      setTimeout(connectDeviceWs, 5000)
    }
    return
  }
  // FIXED: WebSocket重连后不补充断线期间状态快照 — onopen时主动请求一次完整数据
  deviceWs.onopen = () => {
    devWsReconnectDelay = 1000; devWsReconnectAttempts = 0
    api.getDevices().then(data => { if (Array.isArray(data)) devices.value = data }).catch(() => {})
  }
  deviceWs.onerror = () => { devWsReconnectDelay = Math.min(devWsReconnectDelay * 2, WS_MAX_RECONNECT_DELAY) }
  deviceWs.onclose = () => {
    if (manualClose) return
    devWsReconnectAttempts++
    if (devWsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      devWsReconnectTimer = setTimeout(connectDeviceWs, devWsReconnectDelay)
      devWsReconnectDelay = Math.min(devWsReconnectDelay * 2, WS_MAX_RECONNECT_DELAY)
    }
  }
  deviceWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'devices' && Array.isArray(msg.data)) {
        devices.value = msg.data
      }
    } catch (e) {
      if (event.data !== 'ping') console.debug('Device WS non-JSON message:', event.data)
    }
  }
}

function connectLogWs() {
  if (manualClose) return
  try {
    logWs = api.createLogWs()
    if (!logWs) return
  } catch (e) {
    console.error('Failed to create log WebSocket:', e.message)
    logWsReconnectAttempts++
    if (logWsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      setTimeout(connectLogWs, 5000)
    }
    return
  }
  // FIXED: WebSocket重连后不补充断线期间状态快照 — onopen时主动请求一次完整日志
  logWs.onopen = () => {
    logWsReconnectDelay = 1000; logWsReconnectAttempts = 0
    api.getLogs({ limit: 100 }).then(data => { if (Array.isArray(data)) recentLogs.value = data.slice(-50) }).catch(() => {})
  }
  logWs.onerror = () => {
    console.debug('Log WebSocket error, will auto-reconnect')
  }
  logWs.onclose = () => {
    if (manualClose || !logWs) return
    logWsReconnectAttempts++
    if (logWsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      logWsReconnectTimer = setTimeout(connectLogWs, Math.min(5000 * Math.pow(1.5, Math.min(logWsReconnectAttempts, 5)), 60000))
    }
  }
  logWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'log' && msg.data && typeof msg.data === 'object') {
        recentLogs.value.unshift(msg.data)
        if (recentLogs.value.length > 500) recentLogs.value = recentLogs.value.slice(0, 500)
      }
    } catch {
      if (event.data !== 'ping') console.debug('Log WS: non-JSON message ignored')
    }
  }
}

function openMetrics() {
  window.open('/api/v1/metrics', '_blank')
}

onMounted(() => {
  loadData()
  connectDeviceWs()
  connectLogWs()
})

onUnmounted(() => {
  manualClose = true
  if (devWsReconnectTimer) { clearTimeout(devWsReconnectTimer); devWsReconnectTimer = null }
  if (logWsReconnectTimer) { clearTimeout(logWsReconnectTimer); logWsReconnectTimer = null }
  if (deviceWs) { deviceWs.close(); deviceWs = null }
  if (logWs) { logWs.close(); logWs = null }
})
</script>

<style scoped>
@keyframes pulse {
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
  100% { opacity: 1; transform: scale(1); }
}
</style>
