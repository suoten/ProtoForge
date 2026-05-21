<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('recorder.title') }}</div>
        <div class="pf-section-desc">{{ t('recorder.subtitle') }}</div>
      </div>
      <n-space>
        <n-button v-if="activeRecording" type="warning" @click="stopRecording" :loading="stopping">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          {{ t('recorder.stopRecording') }}
        </n-button>
        <n-button v-else type="primary" @click="showStartModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg></template>
          {{ t('recorder.startRecording') }}
        </n-button>
        <n-button @click="loadRecordings" :loading="loading">{{ t('common.refresh') }}</n-button>
      </n-space>
    </n-space>

    <n-alert v-if="activeRecording" type="warning" :bordered="false">
      {{ t('recorder.recording') }} — {{ activeRecording.name }} | {{ t('recorder.recordedCount', { n: activeRecording.event_count || 0 }) }} | {{ t('common.duration') }}: {{ formatDuration(recordingDuration) }}
    </n-alert>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ recordings.length }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('recorder.recordingList') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="activeRecording ? 'pf-gradient-card-green' : ''">
          <div class="pf-stat-value">{{ recorderStats.total_events || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: activeRecording ? 0.9 : 0.6 }">{{ t('recorder.totalEvents') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="activeRecording ? 'pf-gradient-card-orange' : ''">
          <div class="pf-stat-value">{{ recorderStats.total_bytes ? formatBytes(recorderStats.total_bytes) : '0 B' }}</div>
          <div style="font-size:13px" :style="{ opacity: activeRecording ? 0.9 : 0.6 }">{{ t('recorder.dataSize') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-rose">
          <div class="pf-stat-value">{{ recorderStats.avg_events_per_recording || '0' }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('recorder.avgEvents') }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" :title="t('recorder.recordingList')">
      <n-data-table v-if="recordings.length > 0" :columns="columns" :data="recordings" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
      <n-empty v-else :description="t('common.noRecords')">
        <template #extra>
          <n-button @click="showStartModal = true">{{ t('recorder.startRecording') }}</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showStartModal" preset="card" :title="t('recorder.startRecording')" style="width:480px">
      <n-form :model="startForm" label-placement="left" label-width="100">
        <n-form-item :label="t('common.name')">
          <n-input v-model:value="startForm.name" :placeholder="t('recorder.namePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('common.protocol')">
          <n-select v-model:value="startForm.protocol" :options="protocolOptions" :placeholder="t('recorder.protocolPlaceholder')" clearable />
        </n-form-item>
        <n-form-item :label="t('common.deviceId')">
          <n-select v-model:value="startForm.device_id" :options="deviceOptions" :placeholder="t('recorder.devicePlaceholder')" clearable filterable />
        </n-form-item>
        <n-form-item :label="t('common.description')">
          <n-input v-model:value="startForm.note" type="textarea" :rows="2" :placeholder="t('recorder.notePlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showStartModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="doStartRecording" :loading="starting">{{ t('common.start') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showDetailModal" preset="card" :title="t('common.detail')" style="width:720px">
      <n-spin :show="loadingDetail">
        <n-space v-if="detailRec" vertical size="large">
          <n-descriptions label-placement="left" :column="2" bordered size="small">
            <n-descriptions-item :label="t('common.name')">{{ detailRec.name }}</n-descriptions-item>
            <n-descriptions-item label="ID">{{ detailRec.id }}</n-descriptions-item>
            <n-descriptions-item :label="t('common.protocol')">{{ detailRec.protocol || t('common.all') }}</n-descriptions-item>
            <n-descriptions-item :label="t('recorder.totalEvents')">{{ detailRec.event_count || 0 }}</n-descriptions-item>
            <n-descriptions-item :label="t('recorder.startTime')">{{ formatTime(detailRec.started_at) }}</n-descriptions-item>
            <n-descriptions-item :label="t('recorder.endTime')">{{ formatTime(detailRec.stopped_at) }}</n-descriptions-item>
            <n-descriptions-item :label="t('common.duration')">{{ formatDuration(detailRec.duration_seconds) }}</n-descriptions-item>
            <n-descriptions-item :label="t('common.description')">{{ detailRec.metadata?.note || '-' }}</n-descriptions-item>
          </n-descriptions>
          <n-data-table v-if="detailRec.events && detailRec.events.length > 0" :columns="eventColumns" :data="detailRec.events"
            :bordered="false" size="small" :max-height="400" />
        </n-space>
        <n-empty v-else :description="t('common.loading')" />
      </n-spin>
      <template #action>
        <n-button @click="showDetailModal = false">{{ t('common.close') }}</n-button>
        <n-button type="primary" @click="detailRec && replayRecording(detailRec.id)" :loading="replaying" :disabled="!detailRec">{{ t('recorder.replay') }}</n-button>
        <n-button @click="detailRec && exportRecordingFile(detailRec.id)" :disabled="!detailRec">{{ t('common.export') }}</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="showReplayModal" preset="card" :title="t('recorder.replayProgress')" style="width:500px">
      <n-space v-if="replayResult" vertical>
        <n-descriptions label-placement="left" :column="1" bordered size="small">
          <n-descriptions-item :label="t('common.status')">{{ replayResult.status || t('common.finish') }}</n-descriptions-item>
          <n-descriptions-item :label="t('recorder.replayEvents')">{{ replayResult.replayed_events || 0 }} / {{ replayResult.total_events || 0 }}</n-descriptions-item>
          <n-descriptions-item :label="t('common.success')">{{ replayResult.success_count || 0 }}</n-descriptions-item>
          <n-descriptions-item :label="t('common.failed')">{{ replayResult.error_count || 0 }}</n-descriptions-item>
          <n-descriptions-item :label="t('common.duration')">{{ formatDuration(replayResult.duration_seconds) }}</n-descriptions-item>
        </n-descriptions>
      </n-space>
      <template #action>
        <n-button @click="showReplayModal = false">{{ t('common.close') }}</n-button>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h, watch } from 'vue'
import { NSpace, NButton, NAlert, NCard, NDataTable, NModal, NForm, NFormItem,
  NInput, NSelect, NGrid, NGi, NText, NTag, NEmpty, NDescriptions, NDescriptionsItem,
  NSpin, NPopconfirm, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { protocolLabels } from '../constants.js'
import { formatTime as _formatTime, formatBytes as _formatBytes, formatDuration as _formatDuration } from '../utils.js'  // FIXED: 重复定义的格式化函数提取到utils.js

const message = useMessage()
const { t } = useI18n()
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
const recorderProtocols = ref([])
const recorderDevices = ref([])

watch(() => startForm.value.protocol, async (val) => {
  startForm.value.device_id = ''
  if (!val) { recorderDevices.value = []; return }
  try {
    const res = await api.getDevices(val)
    recorderDevices.value = (res || []).map(d => ({ label: `${d.name} (${d.id})`, value: d.id }))
  } catch { recorderDevices.value = []; message.warning(t('common.loadFailed')) }  // FIXED: catch为空函数无错误提示
})

const protocolOptions = computed(() => {
  const all = [{ label: t('common.all'), value: '' }]
  recorderProtocols.value.forEach(p => {
    all.push({ label: p.display_name || protocolLabels[p.name] || p.name, value: p.name })
  })
  return all
})

const deviceOptions = computed(() => {
  const all = [{ label: t('common.all'), value: '' }]
  return all.concat(recorderDevices.value)
})
const recordingDuration = ref(0)
let durationTimer = null

const columns = computed(() => [
  { title: t('common.name'), key: 'name', width: 180, ellipsis: { tooltip: true } },
  { title: t('common.protocol'), key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => row.protocol || t('common.all')) },
  { title: t('recorder.totalEvents'), key: 'event_count', width: 80 },
  { title: t('recorder.startTime'), key: 'started_at', width: 170, render: (row) => formatTime(row.started_at) },
  { title: t('common.duration'), key: 'duration_seconds', width: 100, render: (row) => formatDuration(row.duration_seconds) },
  {
    title: t('common.status'), key: 'is_active', width: 80,
    render: (row) => row.is_active
      ? h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => t('recorder.recording'))
      : h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => t('common.finish'))
  },
  {
    title: t('common.action'), key: 'actions', width: 180,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => viewDetail(row.id) }, () => t('common.detail')),
      h(NButton, { size: 'tiny', type: 'primary', secondary: true, onClick: () => replayRecording(row.id) }, () => t('recorder.replay')),
      h(NButton, { size: 'tiny', onClick: () => exportRecordingFile(row.id) }, () => t('common.export')),
      h(NPopconfirm, { onPositiveClick: () => deleteRec(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => t('common.delete')),
        default: () => t('common.confirmDelete'),
      })
    ])
  },
])

const eventColumns = computed(() => [
  { title: '#', key: 'index', width: 50, render: (_, idx) => idx + 1 },
  { title: t('common.time'), key: 'timestamp', width: 100, render: (row) => formatTime(row.timestamp) },
  { title: t('common.type'), key: 'message_type', width: 120 },
  { title: t('common.status'), key: 'direction', width: 60 },
  { title: t('common.detail'), key: 'summary', width: 200, ellipsis: { tooltip: true } },
])

async function loadRecordings() {
  loading.value = true
  try {
    const res = await api.listRecordings()
    recordings.value = res || []
  } catch (e) {
    message.error(t('recorder.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    const res = await api.getRecorderStats()
    recorderStats.value = res
    if (res.is_recording) {
      activeRecording.value = { name: res.active_name || t('recorder.recording'), event_count: res.frames_captured || 0 }
      if (!durationTimer) {
        recordingDuration.value = Math.round(res.duration_seconds || 0)
        durationTimer = setInterval(() => { recordingDuration.value++ }, 1000)
      }
    } else {
      activeRecording.value = null
      if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
    }
  } catch (e) {
    recorderStats.value = recorderStats.value || {}
    message.warning(t('recorder.statsFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function doStartRecording() {
  if (!startForm.value.name) { message.warning(t('recorder.nameRequired')); return }
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
    if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
    durationTimer = setInterval(() => { recordingDuration.value++ }, 1000)
    message.success(t('recorder.started'))
    await loadRecordings()
  } catch (e) {
    activeRecording.value = null
    message.error(t('recorder.startFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { starting.value = false }
}

function stopRecording() {
  dialog.warning({
    title: t('recorder.confirmStop'),
    content: t('recorder.confirmStopDesc'),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      stopping.value = true
      try {
        const res = await api.stopRecording()
        activeRecording.value = null
        if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
        message.success(t('recorder.stopped', { n: res.event_count || 0 }))
        await loadRecordings()
        await loadStats()  // FIXED: refresh stats after stopRecording succeeds
      } catch (e) {
        message.error(t('recorder.stopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { stopping.value = false }
    }
  })
}

async function viewDetail(id) {
  showDetailModal.value = true
  loadingDetail.value = true
  detailRec.value = null
  try {
    detailRec.value = await api.getRecording(id)
  } catch (e) {
    message.error(t('recorder.detailFailed') + ': ' + (e.response?.data?.detail || e.message))
    showDetailModal.value = false
  } finally { loadingDetail.value = false }
}

async function replayRecording(id) {
  dialog.info({
    title: t('recorder.confirmReplay'),
    content: t('recorder.confirmReplayDesc'),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      replaying.value = true
      try {
        const res = await api.replayRecording(id, { speed: 1.0 })
        replayResult.value = res
        showReplayModal.value = true
        message.success(t('recorder.replayStarted'))
      } catch (e) {
        message.error(t('recorder.replayFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { replaying.value = false }
    }
  })
}

async function exportRecordingFile(id) {
  try {
    const res = await api.exportRecording(id)
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `recording-${id}.json`; a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.export') + ' OK')
  } catch (e) {
    message.error(t('common.export') + ' ' + t('common.error') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteRec(id) {
  try {
    await api.deleteRecording(id)
    message.success(t('common.deleted'))
    await loadRecordings()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

// FIXED: 重复定义的格式化函数 — 委托到utils.js统一实现
function formatTime(ts) { return _formatTime(ts) }
function formatDuration(seconds) { return _formatDuration(seconds) }
function formatBytes(bytes) { return _formatBytes(bytes) }

onMounted(() => {
  loadRecordings()
  loadStats()
  api.getProtocols().then(res => { recorderProtocols.value = res || [] }).catch(() => { message.warning(t('common.loadFailed')) })  // FIXED: 静默失败无用户提示
})

onUnmounted(() => {
  if (durationTimer) { clearInterval(durationTimer) }
})
</script>
