<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">协议调试日志</div>
        <div class="pf-section-desc">实时查看协议通信全链路日志，快速定位开发问题</div>
      </div>
      <n-space>
        <n-tag :type="wsConnected ? 'success' : 'error'" size="small" round>
          {{ wsConnected ? '实时连接' : '连接断开' }}
        </n-tag>
      </n-space>
    </n-space>

    <n-space align="center">
      <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width: 150px" />
      <n-select v-model:value="filterDirection" :options="directionOptions" placeholder="按方向筛选" clearable style="width: 130px" />
      <n-input v-model:value="searchText" placeholder="搜索日志内容..." clearable style="width: 200px" />
      <n-button @click="togglePause" :type="paused ? 'warning' : 'default'" size="small">
        {{ paused ? '继续' : '暂停' }}
      </n-button>
      <n-button @click="clearAllLogs" type="error" size="small" ghost>清空</n-button>
      <n-button @click="exportLogs" size="small" ghost>导出</n-button>
      <span style="color: #999; font-size: 12px">共 {{ filteredLogs.length }} 条</span>
    </n-space>

    <div ref="logContainer" style="height: calc(100vh - 240px); overflow-y: auto; border: 1px solid #333; border-radius: 8px; background: #1a1a2e; font-family: 'Consolas', 'Monaco', monospace; font-size: 12px;">
      <div v-if="filteredLogs.length === 0" style="padding: 40px; text-align: center; color: #666">
        暂无日志，启动协议并创建设备后将自动记录通信过程
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
          {{ log.device_id.substring(0, 8) }}
        </span>
        <n-tag v-if="log.message_type" :type="getTypeColor(log.message_type)" size="tiny" round style="flex-shrink: 0;">
          {{ log.message_type }}
        </n-tag>
        <span style="color: #ccc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">
          {{ log.summary }}
        </span>
      </div>
    </div>

    <n-modal v-model:show="detailVisible" preset="card" title="日志详情" style="width: 700px;">
      <n-descriptions v-if="selectedLog" bordered :column="1" label-placement="left" size="small">
        <n-descriptions-item label="时间">{{ new Date(selectedLog.timestamp * 1000).toLocaleString() }}</n-descriptions-item>
        <n-descriptions-item label="协议">{{ selectedLog.protocol }}</n-descriptions-item>
        <n-descriptions-item label="方向">
          <n-tag :type="getDirectionColor(selectedLog.direction)" size="small">
            {{ getDirectionLabel(selectedLog.direction) }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="设备ID">{{ selectedLog.device_id || '-' }}</n-descriptions-item>
        <n-descriptions-item label="消息类型">{{ selectedLog.message_type }}</n-descriptions-item>
        <n-descriptions-item label="摘要">{{ selectedLog.summary }}</n-descriptions-item>
        <n-descriptions-item label="详细信息" v-if="selectedLog.detail && Object.keys(selectedLog.detail).length > 0">
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
import { directionTagTypeMap, directionLabelMap } from '../constants.js'

const message = useMessage()
const dialog = useDialog()

const logs = ref([])
const protocols = ref([])
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
  { label: '全部协议', value: null },
  ...protocols.value.map(p => ({ label: p.display_name || p.name, value: p.name })),
])

const directionOptions = [
  { label: '全部方向', value: null },
  { label: '← 接收', value: 'in' },
  { label: '→ 发送', value: 'out' },
  { label: '⚡ 系统', value: 'system' },
  { label: '✎ 写入', value: 'write' },
  { label: '← 入站', value: 'inbound' },
  { label: '→ 出站', value: 'outbound' },
]

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

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

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
    title: '确认清空日志',
    content: '清空后所有日志将永久删除，此操作不可恢复。确定继续？',
    positiveText: '清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      logs.value = []
      try {
        await api.clearLogs()
        message.success('日志已清空')
      } catch (e) {
        console.warn('清空日志失败:', e)
        message.error('清空日志失败')
      }
    }
  })
}

function exportLogs() {
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
}

function scrollToBottom() {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

async function connectWebSocket() {
  await api.ensureValidToken()
  ws = api.createLogWs()

  ws.onopen = () => {
    wsConnected.value = true
    reconnectAttempts = 0
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
      console.warn('WebSocket日志消息解析失败:', e)
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
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return
  const delay = Math.min(5000 * Math.pow(1.5, reconnectAttempts), 60000)
  reconnectAttempts++
  reconnectTimer = setTimeout(() => {
    connectWebSocket()
  }, delay)
}

async function loadProtocols() {
  try {
    const res = await api.getProtocols()
    protocols.value = res
  } catch (e) {
    console.warn('加载协议列表失败:', e)
    message.error('加载协议列表失败')
  }
}

async function loadHistory() {
  try {
    const res = await api.getLogs({ count: 200 })
    logs.value = Array.isArray(res) ? res : (res.logs || res.entries || [])
  } catch (e) {
    console.warn('加载历史日志失败:', e)
    message.error('加载历史日志失败')
  }
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
