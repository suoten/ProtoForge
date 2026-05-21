<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('logs.title') }}</div>
        <div class="pf-section-desc">{{ t('logs.subtitle') }}</div>
      </div>
      <n-space>
        <n-tag :type="wsConnected ? 'success' : 'error'" size="small" round>
          {{ wsConnected ? t('logs.realtimeConnected') : t('logs.disconnected') }}
        </n-tag>
      </n-space>
    </n-space>

    <n-space align="center">
      <n-select v-model:value="filterProtocol" :options="protocolOptions" :placeholder="t('logs.filterByProtocol')" clearable style="width: 150px" />
      <n-select v-model:value="filterDirection" :options="directionOptions" :placeholder="t('logs.filterByDirection')" clearable style="width: 130px" />
      <n-input v-model:value="searchText" :placeholder="t('logs.searchPlaceholder')" clearable style="width: 200px" />
      <n-button @click="togglePause" :type="paused ? 'warning' : 'default'" size="small">
        {{ paused ? t('logs.resume') : t('logs.pause') }}
      </n-button>
      <n-button @click="clearAllLogs" type="error" size="small" ghost>{{ t('logs.clear') }}</n-button>
      <n-button @click="exportLogs" size="small" ghost>{{ t('common.export') }}</n-button>
      <span style="color: #999; font-size: 12px">{{ t('common.total', { n: filteredLogs.length }) }}</span>
    </n-space>

    <div ref="logContainer" style="height: calc(100vh - 240px); overflow-y: auto; border: 1px solid #333; border-radius: 8px; background: #1a1a2e; font-family: 'Consolas', 'Monaco', monospace; font-size: 12px;">
      <div v-if="historyLoading" style="padding: 40px; text-align: center; color: #666">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="filteredLogs.length === 0" style="padding: 40px; text-align: center; color: #666">
        {{ t('logs.noLogs') }}
      </div>
      <div v-for="(log, idx) in filteredLogs" :key="idx"
           @click="showDetail(log)"
           style="padding: 4px 12px; border-bottom: 1px solid #252540; cursor: pointer; display: flex; align-items: center; gap: 8px;"
           :style="{ background: idx % 2 === 0 ? '#1a1a2e' : '#1e1e36' }">
        <span style="color: #666; min-width: 75px; flex-shrink: 0;">{{ formatTime(log.timestamp) }}</span>
        <n-tag :type="getDirectionColor(log.direction)" size="tiny" round style="min-width: 50px; justify-content: center;">
          {{ getDirectionLabel(log.direction) }}
        </n-tag>
        <n-tag size="tiny" :bordered="false" style="min-width: 70px; justify-content: center;">
          {{ log.protocol }}
        </n-tag>
        <span v-if="log.device_id" style="color: #8b8bcd; min-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0;">
          {{ (log.device_id || '').substring(0, 8) }}
        </span>
        <n-tag v-if="log.message_type" :type="getTypeColor(log.message_type)" size="tiny" round style="flex-shrink: 0;">
          {{ log.message_type }}
        </n-tag>
        <span style="color: #ccc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">
          {{ log.summary }}
        </span>
      </div>
    </div>

    <n-modal v-model:show="detailVisible" preset="card" :title="t('logs.detailTitle')" style="width: 700px;">
      <n-descriptions v-if="selectedLog" bordered :column="1" label-placement="left" size="small">
        <n-descriptions-item :label="t('logs.time')">{{ new Date(selectedLog.timestamp * 1000).toLocaleString() }}</n-descriptions-item>
        <n-descriptions-item :label="t('common.protocol')">{{ selectedLog.protocol }}</n-descriptions-item>
        <n-descriptions-item :label="t('logs.direction')">
          <n-tag :type="getDirectionColor(selectedLog.direction)" size="small">
            {{ getDirectionLabel(selectedLog.direction) }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('logs.deviceId')">{{ selectedLog.device_id || '-' }}</n-descriptions-item>
        <n-descriptions-item :label="t('logs.messageType')">{{ selectedLog.message_type }}</n-descriptions-item>
        <n-descriptions-item :label="t('logs.summary')">{{ selectedLog.summary }}</n-descriptions-item>
        <n-descriptions-item :label="t('logs.detailInfo')" v-if="selectedLog.detail && typeof selectedLog.detail === 'object' && Object.keys(selectedLog.detail).length > 0">
          <pre style="margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 12px; color: #aaa; background: #1a1a2e; padding: 8px; border-radius: 4px;">{{ JSON.stringify(selectedLog.detail, null, 2) }}</pre>
        </n-descriptions-item>
      </n-descriptions>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { NSpace, NSelect, NButton, NTag, NInput, NModal, NDescriptions, NDescriptionsItem, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { directionTagTypeMap, directionLabelMap } from '../constants.js'
import { formatTime as _formatTime } from '../utils.js'  // FIXED: 重复定义的格式化函数提取到utils.js

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()

const logs = ref([])
const protocols = ref([])
const historyLoading = ref(false)
const filterProtocol = ref(null)
const filterDirection = ref(null)
const searchText = ref('')
const wsConnected = ref(false)
const paused = ref(false)
const detailVisible = ref(false)
const selectedLog = ref(null)
const logContainer = ref(null)
let ws = null
let reconnectTimer = null
let reconnectAttempts = 0
let manualClose = false
const MAX_RECONNECT_ATTEMPTS = 10
const MAX_LOGS = 2000

const protocolOptions = computed(() => [
  { label: t('logs.allProtocols'), value: null },
  ...protocols.value.map(p => ({ label: p.display_name || p.name, value: p.name })),
])

const directionOptions = computed(() => [
  { label: t('logs.allDirections'), value: null },
  { label: t('logs.receive'), value: 'in' },
  { label: t('logs.send'), value: 'out' },
  { label: t('logs.system'), value: 'system' },
  { label: t('logs.write'), value: 'write' },
  { label: t('logs.inbound'), value: 'inbound' },
  { label: t('logs.outbound'), value: 'outbound' },
])

const filteredLogs = computed(() => {
  let result = logs.value
  if (filterProtocol.value) {
    result = result.filter(l => l.protocol === filterProtocol.value)
  }
  if (filterDirection.value) {
    result = result.filter(l => l.direction === filterDirection.value)
  }
  if (searchText.value) {
    const s = searchText.value.toLowerCase()
    result = result.filter(l =>
      (l.summary && l.summary.toLowerCase().includes(s)) ||
      (l.message_type && l.message_type.toLowerCase().includes(s)) ||
      (l.device_id && l.device_id.toLowerCase().includes(s)) ||
      (l.detail && JSON.stringify(l.detail).toLowerCase().includes(s))
    )
  }
  return result
})

// FIXED: 重复定义的格式化函数 — 委托到utils.js统一实现
function formatTime(ts) { return _formatTime(ts) }

function getDirectionColor(dir) {
  return directionTagTypeMap[dir] || 'default'
}

function getDirectionLabel(dir) {
  return directionLabelMap[dir] || dir
}

function getTypeColor(type) {
  if (!type) return 'default'
  if (type.includes('error') || type.includes('fail')) return 'error'
  if (type.includes('register') || type.includes('start')) return 'success'
  if (type.includes('invite') || type.includes('rtp')) return 'info'
  if (type.includes('warning')) return 'warning'
  return 'default'
}

function showDetail(log) {
  selectedLog.value = log
  detailVisible.value = true
}

function togglePause() {
  paused.value = !paused.value
}

async function clearAllLogs() {
  dialog.warning({
    title: t('logs.confirmClear'),
    content: t('logs.confirmClearDesc'),
    positiveText: t('logs.clear'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.clearLogs()
        logs.value = []
        message.success(t('logs.logsCleared'))
      } catch (e) {
        message.error(t('logs.clearFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

function exportLogs() {
  try {
    const data = filteredLogs.value.map(l => ({
      time: new Date(l.timestamp * 1000).toISOString(),
      protocol: l.protocol,
      direction: l.direction,
      device_id: l.device_id,
      type: l.message_type,
      summary: l.summary,
      detail: l.detail,
    }))
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `protoforge-debug-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('logs.exported', { count: data.length }))
  } catch (e) {
    message.error(t('common.exportFailed') + ': ' + (e.message || t('common.unknownError')))
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

async function connectWebSocket() {
  try {
    await api.ensureValidToken()
  } catch (e) {
    console.warn('Token validation failed, attempting WebSocket anyway:', e.message)
    message.warning(t('logs.tokenExpired'))
  }
  try {
    ws = api.createLogWs()
    if (!ws) { message.warning(t('logs.notLoggedIn')); return }
  } catch (e) {
    console.error('Failed to create log WebSocket:', e.message)
    message.warning(t('logs.wsConnectFailed'))
    setTimeout(connectWebSocket, 5000)
    return
  }

  // FIXED: WebSocket重连后不补充断线期间状态快照 — onopen时主动请求一次完整日志
  ws.onopen = () => {
    wsConnected.value = true
    reconnectAttempts = 0
    api.getLogs({ limit: 200 }).then(data => {
      if (Array.isArray(data) && data.length > 0) {
        logs.value = data.slice(-MAX_LOGS)
        scrollToBottom()
      }
    }).catch(() => {})
  }

  ws.onmessage = (event) => {
    if (paused.value) return
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'log' && msg.data) {
        logs.value.push(msg.data)
        if (logs.value.length > MAX_LOGS) {
          logs.value = logs.value.slice(-MAX_LOGS)
        }
        scrollToBottom()
      }
      } catch (e) {
        // Silently ignore non-log WebSocket messages (ping, etc.)
      }
  }

  ws.onclose = () => {
    wsConnected.value = false
    if (!manualClose) {
      scheduleReconnect()
    }
  }

  ws.onerror = () => {
    wsConnected.value = false
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    message.error(t('logs.reconnectFailed'))
    return
  }
  const delay = Math.min(5000 * Math.pow(1.5, reconnectAttempts), 60000)
  reconnectAttempts++
  reconnectTimer = setTimeout(() => {
    connectWebSocket()
  }, delay)
}

async function loadProtocols() {
  try {
    const res = await api.getProtocols()
    protocols.value = res || []  // FIXED: API返回null时map()崩溃
  } catch (e) {
    message.error(t('logs.loadProtocolsFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await api.getLogs({ count: 200 })
    logs.value = res || []
  } catch (e) {
    message.error(t('logs.loadHistoryFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { historyLoading.value = false }
}

onMounted(() => {
  loadProtocols()
  loadHistory()
  connectWebSocket()
})

onUnmounted(() => {
  manualClose = true
  if (ws) {
    ws.close()
    ws = null
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
})
</script>
