<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">录制回放</div>
        <div class="pf-section-desc">录制协议交互数据，支持回放复现和导出分析</div>
      </div>
      <n-space>
        <n-button v-if="activeRecording" type="warning" @click="stopRecording" :loading="stopping">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          停止录制
        </n-button>
        <n-button v-else type="primary" @click="showStartModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg></template>
          开始录制
        </n-button>
        <n-button @click="loadRecordings" :loading="loading">刷新</n-button>
      </n-space>
    </n-space>

    <n-alert v-if="activeRecording" type="warning" :bordered="false">
      正在录制 — {{ activeRecording.name }} | 已录制 {{ activeRecording.event_count || 0 }} 个事件 | 耗时 {{ formatDuration(recordingDuration) }}
    </n-alert>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ recordings.length }}</div>
          <div style="font-size:13px;opacity:0.9">录制数</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="activeRecording ? 'pf-gradient-card-green' : ''">
          <div class="pf-stat-value">{{ recorderStats.total_events || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: activeRecording ? 0.9 : 0.6 }">总事件</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="activeRecording ? 'pf-gradient-card-orange' : ''">
          <div class="pf-stat-value">{{ recorderStats.total_bytes ? formatBytes(recorderStats.total_bytes) : '0 B' }}</div>
          <div style="font-size:13px" :style="{ opacity: activeRecording ? 0.9 : 0.6 }">数据量</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-rose">
          <div class="pf-stat-value">{{ recorderStats.avg_events_per_recording || '0' }}</div>
          <div style="font-size:13px;opacity:0.9">平均事件</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" title="录制列表">
      <n-data-table v-if="recordings.length > 0" :columns="columns" :data="recordings" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
      <n-empty v-else description="暂无录制记录，点击「开始录制」创建">
        <template #extra>
          <n-button @click="showStartModal = true">开始录制</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showStartModal" preset="card" title="开始录制" style="width:480px">
      <n-form :model="startForm" label-placement="left" label-width="100">
        <n-form-item label="录制名称">
          <n-input v-model:value="startForm.name" placeholder="如 压力测试录制" />
        </n-form-item>
        <n-form-item label="协议筛选">
          <n-input v-model:value="startForm.protocol" placeholder="留空则录制全部协议" />
        </n-form-item>
        <n-form-item label="设备筛选">
          <n-input v-model:value="startForm.device_id" placeholder="留空则录制全部设备" />
        </n-form-item>
        <n-form-item label="备注">
          <n-input v-model:value="startForm.note" type="textarea" :rows="2" placeholder="录制说明（可选）" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showStartModal = false">取消</n-button>
          <n-button type="primary" @click="doStartRecording" :loading="starting">开始</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showDetailModal" preset="card" title="录制详情" style="width:720px">
      <n-spin :show="loadingDetail">
        <n-space v-if="detailRec" vertical size="large">
          <n-descriptions label-placement="left" :column="2" bordered size="small">
            <n-descriptions-item label="名称">{{ detailRec.name }}</n-descriptions-item>
            <n-descriptions-item label="ID">{{ detailRec.id }}</n-descriptions-item>
            <n-descriptions-item label="协议">{{ detailRec.protocol || '全部' }}</n-descriptions-item>
            <n-descriptions-item label="事件数">{{ detailRec.event_count || 0 }}</n-descriptions-item>
            <n-descriptions-item label="开始时间">{{ formatTime(detailRec.started_at) }}</n-descriptions-item>
            <n-descriptions-item label="结束时间">{{ formatTime(detailRec.stopped_at) }}</n-descriptions-item>
            <n-descriptions-item label="耗时">{{ formatDuration(detailRec.duration_seconds) }}</n-descriptions-item>
            <n-descriptions-item label="备注">{{ detailRec.metadata?.note || '-' }}</n-descriptions-item>
          </n-descriptions>
          <n-data-table v-if="detailRec.events && detailRec.events.length > 0" :columns="eventColumns" :data="detailRec.events"
            :bordered="false" size="small" :max-height="400" />
        </n-space>
        <n-empty v-else description="加载中..." />
      </n-spin>
      <template #action>
        <n-button @click="showDetailModal = false">关闭</n-button>
        <n-button type="primary" @click="replayRecording(detailRec.id)" :loading="replaying">回放</n-button>
        <n-button @click="exportRecordingFile(detailRec.id)">导出</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="showReplayModal" preset="card" title="回放进度" style="width:500px">
      <n-space v-if="replayResult" vertical>
        <n-descriptions label-placement="left" :column="1" bordered size="small">
          <n-descriptions-item label="状态">{{ replayResult.status || '完成' }}</n-descriptions-item>
          <n-descriptions-item label="回放事件">{{ replayResult.replayed_events || 0 }} / {{ replayResult.total_events || 0 }}</n-descriptions-item>
          <n-descriptions-item label="成功">{{ replayResult.success_count || 0 }}</n-descriptions-item>
          <n-descriptions-item label="失败">{{ replayResult.error_count || 0 }}</n-descriptions-item>
          <n-descriptions-item label="耗时">{{ formatDuration(replayResult.duration_seconds) }}</n-descriptions-item>
        </n-descriptions>
      </n-space>
      <template #action>
        <n-button @click="showReplayModal = false">关闭</n-button>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, onMounted, onUnmounted, h } from 'vue'
import { NSpace, NButton, NAlert, NCard, NDataTable, NModal, NForm, NFormItem,
  NInput, NSelect, NGrid, NGi, NText, NTag, NEmpty, NDescriptions, NDescriptionsItem,
  NSpin, NPopconfirm, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const dialog = useDialog()

const recordings = ref([])
const recorderStats = ref({})
const activeRecording = ref(null)
const loading = ref(false)
const starting = ref(false)
const stopping = ref(false)
const showStartModal = ref(false)
const showDetailModal = ref(false)
const showReplayModal = ref(false)
const loadingDetail = ref(false)
const detailRec = ref(null)
const replaying = ref(false)
const replayResult = ref(null)

const startForm = ref({ name: '', protocol: '', device_id: '', note: '' })
const recordingDuration = ref(0)
let durationTimer = null

const columns = [
  { title: '名称', key: 'name', width: 180, ellipsis: { tooltip: true } },
  { title: '协议', key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => row.protocol || '全部') },
  { title: '事件数', key: 'event_count', width: 80 },
  { title: '开始时间', key: 'started_at', width: 170, render: (row) => formatTime(row.started_at) },
  { title: '耗时', key: 'duration_seconds', width: 100, render: (row) => formatDuration(row.duration_seconds) },
  {
    title: '状态', key: 'is_active', width: 80,
    render: (row) => row.is_active
      ? h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => '录制中')
      : h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => '已完成')
  },
  {
    title: '操作', key: 'actions', width: 180,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => viewDetail(row.id) }, () => '详情'),
      h(NButton, { size: 'tiny', type: 'primary', secondary: true, onClick: () => replayRecording(row.id) }, () => '回放'),
      h(NButton, { size: 'tiny', onClick: () => exportRecordingFile(row.id) }, () => '导出'),
      h(NPopconfirm, { onPositiveClick: () => deleteRec(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
        default: () => `确定删除录制 "${row.name}" 吗？`,
      })
    ])
  },
]

const eventColumns = [
  { title: '#', key: 'index', width: 50, render: (_, idx) => idx + 1 },
  { title: '时间', key: 'timestamp', width: 100, render: (row) => formatTime(row.timestamp) },
  { title: '类型', key: 'message_type', width: 120 },
  { title: '方向', key: 'direction', width: 60 },
  { title: '摘要', key: 'summary', width: 200, ellipsis: { tooltip: true } },
]

async function loadRecordings() {
  loading.value = true
  try {
    const res = await api.getRecordings()
    recordings.value = res || []
  } catch (e) {
    message.error('加载录制列表失败: ' + (e.response?.data?.detail || e.message))
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    recorderStats.value = await api.getRecorderStats()
  } catch (e) { console.warn('加载录制统计失败:', e) }
}

async function doStartRecording() {
  if (!startForm.value.name) { message.warning('请输入录制名称'); return }
  starting.value = true
  try {
    const cfg = { name: startForm.value.name }
    if (startForm.value.protocol) cfg.protocol = startForm.value.protocol
    if (startForm.value.device_id) cfg.device_id = startForm.value.device_id
    if (startForm.value.note) cfg.metadata = { note: startForm.value.note }
    activeRecording.value = await api.startRecording(cfg)
    showStartModal.value = false
    startForm.value = { name: '', protocol: '', device_id: '', note: '' }
    recordingDuration.value = 0
    durationTimer = setInterval(() => { recordingDuration.value++ }, 1000)
    message.success('录制已开始')
  } catch (e) {
    message.error('开始录制失败: ' + (e.response?.data?.detail || e.message))
  } finally { starting.value = false }
}

async function stopRecording() {
  stopping.value = true
  try {
    const res = await api.stopRecording()
    activeRecording.value = null
    if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
    message.success('录制已停止，共 ' + (res.event_count || 0) + ' 个事件')
    await loadRecordings()
  } catch (e) {
    message.error('停止录制失败: ' + (e.response?.data?.detail || e.message))
  } finally { stopping.value = false }
}

async function viewDetail(id) {
  showDetailModal.value = true
  loadingDetail.value = true
  detailRec.value = null
  try {
    detailRec.value = await api.getRecording(id)
  } catch (e) {
    message.error('加载录制详情失败: ' + (e.response?.data?.detail || e.message))
    showDetailModal.value = false
  } finally { loadingDetail.value = false }
}

async function replayRecording(id) {
  replaying.value = true
  try {
    const res = await api.replayRecording(id, { speed: 1.0 })
    replayResult.value = res
    showReplayModal.value = true
  } catch (e) {
    message.error('回放失败: ' + (e.response?.data?.detail || e.message))
  } finally { replaying.value = false }
}

async function exportRecordingFile(id) {
  try {
    const res = await api.exportRecording(id)
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `recording-${id}.json`; a.click()
    URL.revokeObjectURL(url)
    message.success('已导出')
  } catch (e) {
    message.error('导出失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteRec(id) {
  try {
    await api.deleteRecording(id)
    message.success('已删除')
    await loadRecordings()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

function formatTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

function formatDuration(seconds) {
  if (seconds == null) return '-'
  const s = Number(seconds)
  if (s < 60) return s + '秒'
  if (s < 3600) return Math.floor(s / 60) + '分' + (s % 60) + '秒'
  return Math.floor(s / 3600) + '时' + Math.floor((s % 3600) / 60) + '分'
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + ' ' + units[i]
}

onMounted(() => {
  loadRecordings()
  loadStats()
})

onUnmounted(() => {
  if (durationTimer) { clearInterval(durationTimer) }
})
</script>
