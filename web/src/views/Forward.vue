<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('forward.title') }}</div>
        <div class="pf-section-desc">{{ t('forward.subtitle') }}</div>
      </div>
      <n-space>
        <n-button v-if="forwardRunning" type="warning" @click="stopForward" :loading="stopping">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          {{ t('forward.stopForward') }}
        </n-button>
        <n-button v-else type="primary" @click="startForward" :loading="starting">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          {{ t('forward.startForward') }}
        </n-button>
        <n-button type="primary" @click="showAddModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
          {{ t('forward.addTarget') }}
        </n-button>
      </n-space>
    </n-space>

    <n-alert v-if="forwardRunning" type="success" :bordered="false">
      {{ t('forward.forwardRunning', { sent: stats.sent_count || 0, dropped: stats.dropped_count || 0, rate: stats.rate || 0 }) }}
    </n-alert>
    <n-alert v-else type="info" :bordered="false">
      {{ t('forward.forwardStopped') }}
    </n-alert>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ targets.length }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('forward.targetList') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-green' : ''">
          <div class="pf-stat-value">{{ stats.sent_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">{{ t('forward.sent') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-orange' : ''">
          <div class="pf-stat-value">{{ stats.dropped_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">{{ t('forward.dropped') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-rose' : ''">
          <div class="pf-stat-value">{{ stats.error_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">{{ t('forward.errorCount') }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" :title="t('forward.targetList')">
      <template #header-extra>
        <n-button size="small" @click="loadTargets" :loading="loadingTargets">{{ t('common.refresh') }}</n-button>
      </template>
      <n-data-table v-if="targets.length > 0" :columns="targetColumns" :data="targets" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.name" />
      <n-empty v-else :description="t('forward.noTargets')">
        <template #extra>
          <n-button @click="showAddModal = true">{{ t('forward.addTarget') }}</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showAddModal" preset="card" :title="t('forward.addTargetTitle')" style="width:560px">
      <n-form :model="addForm" label-placement="left" label-width="100">
        <n-form-item :label="t('forward.targetName')">
          <n-input v-model:value="addForm.name" :placeholder="t('forward.namePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('forward.targetType')">
          <n-select v-model:value="addForm.type" :options="typeOptions" />
        </n-form-item>
        <template v-if="addForm.type === 'influxdb'">
          <n-form-item :label="t('forward.hostAddress')">
            <n-input v-model:value="addForm.host" :placeholder="t('forward.hostPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('common.port')">
            <n-input-number v-model:value="addForm.port" :min="1" :max="65535" :placeholder="t('forward.portPlaceholder')" style="width:100%" />
          </n-form-item>
          <n-form-item :label="t('forward.database')">
            <n-input v-model:value="addForm.database" :placeholder="t('forward.databasePlaceholder')" />
          </n-form-item>
        </template>
        <template v-else-if="addForm.type === 'http'">
          <n-form-item :label="t('forward.targetUrl')">
            <n-input v-model:value="addForm.url" :placeholder="t('forward.urlPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('forward.headers')">
            <n-input v-model:value="addForm.headers_json" type="textarea" :rows="3" :placeholder="t('forward.headersPlaceholder')" />
          </n-form-item>
        </template>
        <template v-else-if="addForm.type === 'file'">
          <n-form-item :label="t('forward.filePath')">
            <n-input v-model:value="addForm.path" :placeholder="t('forward.pathPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('forward.fileFormat')">
            <n-select v-model:value="addForm.format" :options="[{label: t('forward.jsonl'), value: 'jsonl'}, {label: t('forward.csv'), value: 'csv'}]" />
          </n-form-item>
        </template>
        <n-form-item :label="t('forward.protocolFilter')">
          <n-input v-model:value="addForm.protocol" :placeholder="t('forward.protocolPlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="addTarget" :loading="adding">{{ t('common.add') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NButton, NAlert, NCard, NDataTable, NModal, NForm, NFormItem,
  NInput, NInputNumber, NSelect, NGrid, NGi, NTag, NEmpty, NPopconfirm, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()

const targets = ref([])
const stats = ref({})
const forwardRunning = ref(false)
const loadingTargets = ref(false)
const starting = ref(false)
const stopping = ref(false)
const showAddModal = ref(false)
const adding = ref(false)
const removingTarget = ref(null)

const addForm = ref({
  name: '', type: 'influxdb', host: 'localhost', port: 8086,
  database: 'protoforge', url: '', path: 'data/forward_output.log',
  format: 'jsonl', headers_json: '', protocol: '',
})

const typeOptions = computed(() => [
  { label: t('forward.influxdb'), value: 'influxdb' },
  { label: t('forward.http'), value: 'http' },
  { label: t('forward.file'), value: 'file' },
])

const targetColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 160 },
  { title: t('common.type'), key: 'type', width: 100, render: (row) => {
    const labels = { influxdb: t('forward.influxdb'), http: t('forward.http'), file: t('forward.file') }
    return h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => labels[row.type] || row.type)
  }},
  { title: t('forward.targetUrl'), key: 'display_url', width: 260, ellipsis: { tooltip: true } },
  { title: t('forward.protocolFilter'), key: 'protocol', width: 100, render: (row) => row.protocol || t('forward.all') },
  {
    title: t('common.action'), key: 'actions', width: 100,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => removeTarget(row.name) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => t('common.delete')),
      default: () => t('forward.confirmDelete', { name: row.name }),
    })
  },
])

async function loadTargets() {
  loadingTargets.value = true
  try {
    const res = await api.listForwardTargets()
    targets.value = (res || []).map(item => ({
      ...item,
      display_url: item.url || item.path || (item.host ? `${item.host}:${item.port}` : ''),
    }))
  } catch (e) {
    message.error(t('forward.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loadingTargets.value = false }
}

async function loadStats() {
  try {
    const res = await api.getForwardStats()
    stats.value = res
    forwardRunning.value = res.running || false
  } catch (e) {
    stats.value = stats.value || {}
    message.warning(t('forward.loadStatsFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function addTarget() {
  if (!addForm.value.name?.trim()) { message.warning(t('forward.nameRequired')); return }
  if (addForm.value.type === 'influxdb') {
    if (!addForm.value.host?.trim()) { message.warning(t('forward.influxdbHostRequired')); return }
    if (!addForm.value.port) { message.warning(t('forward.influxdbPortRequired')); return }
    if (!addForm.value.database?.trim()) { message.warning(t('forward.influxdbDbRequired')); return }
  } else if (addForm.value.type === 'http') {
    if (!addForm.value.url?.trim()) { message.warning(t('forward.httpUrlRequired')); return }
  } else if (addForm.value.type === 'file') {
    if (!addForm.value.path?.trim()) { message.warning(t('forward.filePathRequired')); return }
  }
  adding.value = true
  try {
    const cfg = { name: addForm.value.name, type: addForm.value.type }
    if (addForm.value.protocol) cfg.protocol = addForm.value.protocol
    if (addForm.value.type === 'influxdb') {
      cfg.host = addForm.value.host
      cfg.port = addForm.value.port
      cfg.database = addForm.value.database
    } else if (addForm.value.type === 'http') {
      cfg.url = addForm.value.url
      if (addForm.value.headers_json) {
        try { cfg.headers = JSON.parse(addForm.value.headers_json) }
        catch { message.warning(t('forward.headersJsonError')); adding.value = false; return }
      }
    } else if (addForm.value.type === 'file') {
      cfg.path = addForm.value.path
      cfg.format = addForm.value.format
    }
    await api.addForwardTarget(cfg)
    showAddModal.value = false
    addForm.value = { name: '', type: 'influxdb', host: 'localhost', port: 8086, database: 'protoforge', url: '', path: 'data/forward_output.log', format: 'jsonl', headers_json: '', protocol: '' }
    message.success(t('forward.added'))
    await loadTargets()
  } catch (e) {
    message.error(t('forward.addFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { adding.value = false }
}

async function removeTarget(name) {
  try {
    await api.removeForwardTarget(name)
    message.success(t('common.deleted'))
    await loadTargets()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function startForward() {
  starting.value = true
  try {
    await api.startForward()
    forwardRunning.value = true
    message.success(t('forward.started'))
    loadStats()
  } catch (e) {
    message.error(t('forward.startFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { starting.value = false }
}

async function stopForward() {
  dialog.warning({
    title: t('forward.confirmStop'),
    content: t('forward.confirmStopDesc'),
    positiveText: t('forward.confirmStopButton'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      stopping.value = true
      try {
        await api.stopForward()
        forwardRunning.value = false
        message.success(t('forward.stopped'))
      } catch (e) {
        message.error(t('forward.stopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { stopping.value = false }
    }
  })
}

onMounted(() => {
  loadTargets()
  loadStats()
})
</script>
