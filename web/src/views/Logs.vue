<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">实时日志</div>
        <div class="pf-section-desc">查看协议通信日志，支持按协议和设备筛选</div>
      </div>
    </n-space>
    <n-space>
      <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width: 160px" />
      <n-select v-model:value="filterDirection" :options="directionOptions" placeholder="按方向筛选" clearable style="width: 120px" />
      <n-button @click="clearLogs">清空</n-button>
      <n-tag :type="wsConnected ? 'success' : 'error'" size="small">
        {{ wsConnected ? 'WebSocket 已连接' : 'WebSocket 已断开' }}
      </n-tag>
    </n-space>

    <n-data-table :columns="columns" :data="filteredLogs" :bordered="false" size="small"
      :pagination="{ pageSize: 30 }" :row-key="(row, i) => i" />
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { NSpace, NSelect, NButton, NDataTable, NTag } from 'naive-ui'
import api from '../api.js'

const logs = ref([])
const protocols = ref([])
const filterProtocol = ref(null)
const filterDirection = ref(null)
const wsConnected = ref(false)
let ws = null
let reconnectTimer = null
const MAX_LOGS = 500

const protocolOptions = computed(() => [
  { label: '全部协议', value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const directionOptions = [
  { label: '全部方向', value: null },
  { label: '接收', value: 'recv' },
  { label: '发送', value: 'send' },
  { label: '系统', value: 'system' },
  { label: '写入', value: 'write' },
]

const filteredLogs = computed(() => {
  let result = logs.value
  if (filterProtocol.value) {
    result = result.filter(l => l.protocol === filterProtocol.value)
  }
  if (filterDirection.value) {
    result = result.filter(l => l.direction === filterDirection.value)
  }
  return result
})

const columns = [
  { title: '时间', key: 'timestamp', width: 180, render: (row) => new Date(row.timestamp * 1000).toLocaleTimeString() },
  { title: '协议', key: 'protocol', width: 100 },
  {
    title: '方向', key: 'direction', width: 80,
    render: (row) => {
      const colors = { recv: 'info', send: 'success', system: 'warning', write: 'error' }
      return h(NTag, { type: colors[row.direction] || 'default', size: 'tiny' }, () => row.direction)
    }
  },
  { title: '设备', key: 'device_id', width: 120 },
  { title: '类型', key: 'message_type', width: 120 },
  { title: '摘要', key: 'summary' },
]

function clearLogs() {
  logs.value = []
}

function connectWebSocket() {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/ws/logs`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    wsConnected.value = true
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'log' && msg.data) {
        logs.value.push(msg.data)
        if (logs.value.length > MAX_LOGS) {
          logs.value = logs.value.slice(-MAX_LOGS)
        }
      }
    } catch (e) {
      console.error('Failed to parse log message:', e)
    }
  }

  ws.onclose = () => {
    wsConnected.value = false
    scheduleReconnect()
  }

  ws.onerror = () => {
    wsConnected.value = false
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    connectWebSocket()
  }, 5000)
}

async function loadProtocols() {
  try {
    const res = await api.getProtocols()
    protocols.value = res
  } catch (e) {
    console.error('Failed to load protocols:', e)
  }
}

onMounted(() => {
  loadProtocols()
  connectWebSocket()
})

onUnmounted(() => {
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
