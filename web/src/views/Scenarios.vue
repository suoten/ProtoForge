<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('scenarios.title') }}</div>
        <div class="pf-section-desc">{{ t('scenarios.subtitle') }}</div>
      </div>
      <n-space>
        <n-button v-if="selectedIds.length > 0" type="primary" @click="batchStart" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          {{ t('scenarios.startSelected', { count: selectedIds.length }) }}
        </n-button>
        <n-button v-if="selectedIds.length > 0" type="warning" @click="batchStop" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          {{ t('scenarios.stopSelected', { count: selectedIds.length }) }}
        </n-button>
        <n-button @click="startAllScenes" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          {{ t('scenarios.startAll') }}
        </n-button>
        <n-button @click="stopAllScenes" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          {{ t('scenarios.stopAll') }}
        </n-button>
        <n-button tertiary @click="showImportModal = true">{{ t('scenarios.importScene') }}</n-button>
        <n-button type="primary" @click="showCreateModal = true">{{ t('scenarios.createScene') }}</n-button>
      </n-space>
    </n-space>

    <n-data-table v-if="scenarios.length > 0" :columns="columns" :data="scenarios" :bordered="false"
      :pagination="{ pageSize: 15 }" :row-key="row => row.id" :loading="dataLoading"
      v-model:checked-row-keys="selectedIds" :single-line="false" />

    <n-card v-else style="text-align:center;padding:40px">
      <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5" style="margin-bottom:16px"><path d="M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9"/></svg>
      <div class="pf-section-title" style="font-size:16px">{{ t('scenarios.noScenarios') }}</div>
      <div style="margin-top: 12px">
        <n-text depth="3">{{ t('scenarios.noScenariosDesc') }}</n-text>
      </div>
      <div style="margin-top: 16px">
        <n-space justify="center">
          <n-button type="primary" @click="showCreateModal = true">{{ t('scenarios.createScene') }}</n-button>
          <n-button @click="goDashboard">{{ t('scenarios.backToDashboard') }}</n-button>
        </n-space>
      </div>
    </n-card>

    <n-modal v-model:show="showCreateModal" preset="card" :title="t('scenarios.createScene')" style="width: 500px">
      <n-form :model="newScenario" label-placement="left" label-width="80">
        <n-form-item :label="t('scenarios.sceneId')">
          <n-input v-model:value="newScenario.id" :placeholder="t('scenarios.sceneIdPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarios.sceneName')">
          <n-input v-model:value="newScenario.name" :placeholder="t('scenarios.sceneNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('common.description')">
          <n-input v-model:value="newScenario.description" type="textarea" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="cancelCreateScenario">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="createScenario" :loading="creating">{{ t('common.create') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showImportModal" preset="card" :title="t('scenarios.importScene')" style="width: 500px">
      <n-space vertical>
        <n-alert type="info" :bordered="false">{{ t('scenarios.importHint') }}</n-alert>
        <n-input v-model:value="importJson" type="textarea" :rows="8" :placeholder="t('scenarios.importPlaceholder')" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="cancelImportScenario">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="importScenario" :loading="importing">{{ t('common.import') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showSnapshotModal" preset="card" :title="t('scenarios.snapshot')" style="width: 700px">
      <n-data-table :columns="snapshotColumns" :data="snapshotDevices" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" />
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NSpace, NButton, NDataTable, NModal, NForm, NFormItem, NInput, NTag, NAlert, NCard, NText, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

import { useRouter } from 'vue-router'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
const scenarios = ref([])
const dataLoading = ref(false)
const selectedIds = ref([])
const batchLoading = ref(false)
const showCreateModal = ref(false)
const showImportModal = ref(false)
const showSnapshotModal = ref(false)
const creating = ref(false)
const importing = ref(false)
const importJson = ref('')
const snapshotDevices = ref([])
const togglingIds = ref(new Set())
const deletingIds = ref(new Set())
const newScenario = ref({ id: '', name: '', description: '', devices: [], rules: [] })

const columns = computed(() => [
  { type: 'selection' },
  { title: 'ID', key: 'id', width: 150 },
  { title: t('common.name'), key: 'name', width: 180 },
  { title: t('scenarios.deviceCount'), key: 'device_count', width: 80, render: (row) => row.device_count ?? (row.devices || []).length },
  { title: t('scenarios.ruleCount'), key: 'rule_count', width: 80, render: (row) => row.rule_count ?? (row.rules || []).length },
  {
    title: t('common.status'), key: 'status', width: 100,
    render: (row) => {
      const map = { running: 'success', stopped: 'default', error: 'error' }
      const labels = { running: t('common.running'), stopped: t('common.stopped'), error: t('common.error') }
      return h(NTag, { type: map[row.status] || 'default', size: 'small' }, () => labels[row.status] || row.status)
    }
  },
  {
    title: t('common.action'), key: 'actions', width: 380,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      row.status !== 'running'
        ? h(NButton, { size: 'small', type: 'primary', loading: togglingIds.value.has(row.id), onClick: () => startScene(row.id) }, () => t('common.start'))
        : h(NButton, { size: 'small', type: 'warning', loading: togglingIds.value.has(row.id), onClick: () => stopScene(row.id) }, () => t('common.stop')),
      h(NButton, { size: 'small', onClick: () => editScene(row.id) }, () => t('common.edit')),
      h(NButton, { size: 'small', onClick: () => exportScene(row.id) }, () => t('common.export')),
      h(NButton, { size: 'small', onClick: () => viewSnapshot(row.id) }, () => t('scenarios.snapshot')),
      h(NButton, { size: 'small', type: 'error', onClick: () => confirmDelete(row) }, () => t('common.delete')),
    ])
  },
])

const snapshotColumns = computed(() => [
  { title: t('scenarios.deviceId'), key: 'id', width: 150 },
  { title: t('common.name'), key: 'name', width: 150 },
  { title: t('common.protocol'), key: 'protocol', width: 100 },
  { title: t('common.status'), key: 'status', width: 80 },
  { title: t('common.pointCount'), key: 'points', width: 80, render: (row) => row.points?.length || 0 },
])

function goDashboard() {
  router.push('/')
}

function editScene(id) {
  router.push(`/scenario/${id}`)
}

async function loadData() {
  dataLoading.value = true
  try {
    const res = await api.getScenarios()
    scenarios.value = res || []
  } catch (e) {
    message.error(t('scenarios.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { dataLoading.value = false }
}

async function batchStart() {
  if (!selectedIds.value.length) { message.info(t('scenarios.selectToStart')); return }
  dialog.info({
    title: t('scenarios.confirmBatchStart'),
    content: t('scenarios.confirmBatchStartDesc', { count: selectedIds.value.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      const results = await Promise.allSettled(selectedIds.value.map(id => api.startScenario(id)))
      let ok = 0, fail = 0
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') ok++
        else { fail++; message.warning(t('scenarios.sceneStartFailed', { id: selectedIds.value[i] }) + ': ' + (r.reason?.response?.data?.detail || r.reason?.message || t('common.error'))) }
      })
      batchLoading.value = false
      selectedIds.value = []
      const msg = t('scenarios.startedCount', { count: ok }) + (fail ? '，' + t('scenarios.failedCount', { count: fail }) : '')
      if (fail > 0 && ok === 0) message.error(msg)
      else if (fail > 0) message.warning(msg)
      else message.success(msg)
      loadData()
    }
  })
}

async function batchStop() {
  if (!selectedIds.value.length) { message.info(t('scenarios.selectToStop')); return }
  dialog.warning({
    title: t('scenarios.confirmBatchStop'),
    content: t('scenarios.confirmBatchStopDesc', { count: selectedIds.value.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      const results = await Promise.allSettled(selectedIds.value.map(id => api.stopScenario(id)))
      let ok = 0, fail = 0
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') ok++
        else { fail++; message.warning(t('scenarios.sceneStopFailed', { id: selectedIds.value[i] }) + ': ' + (r.reason?.response?.data?.detail || r.reason?.message || t('common.error'))) }
      })
      batchLoading.value = false
      selectedIds.value = []
      const msg = t('scenarios.stoppedCount', { count: ok }) + (fail ? '，' + t('scenarios.failedCount', { count: fail }) : '')
      if (fail > 0 && ok === 0) message.error(msg)
      else if (fail > 0) message.warning(msg)
      else message.success(msg)
      loadData()
    }
  })
}

async function startAllScenes() {
  const running = scenarios.value.filter(s => s.status !== 'running')
  if (!running.length) { message.info(t('scenarios.allRunning')); return }
  dialog.warning({
    title: t('scenarios.confirmStartAll'),
    content: t('scenarios.confirmStartAllDesc', { count: running.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      let ok = 0, fail = 0
      try {
      const results = await Promise.allSettled(running.map(sc => api.startScenario(sc.id)))
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') ok++
        else { fail++; message.warning(t('scenarios.sceneStartFailed', { id: running[i].name }) + ': ' + (r.reason?.response?.data?.detail || r.reason?.message || t('common.error'))) }
      })
      } finally {
        batchLoading.value = false
      }
      if (fail > 0) { message.warning(t('scenarios.startAllPartial', { success: ok, fail })) } else { message.success(t('scenarios.startedCount', { count: ok })) }
      loadData()
    }
  })
}

async function stopAllScenes() {
  const running = scenarios.value.filter(s => s.status === 'running')
  if (!running.length) { message.info(t('scenarios.noRunning')); return }
  dialog.warning({
    title: t('scenarios.confirmStopAll'),
    content: t('scenarios.confirmStopAllDesc', { count: running.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      let ok = 0, fail = 0
      try {
      const results = await Promise.allSettled(running.map(sc => api.stopScenario(sc.id)))
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') ok++
        else { fail++; message.warning(t('scenarios.sceneStopFailed', { id: running[i].name }) + ': ' + (r.reason?.response?.data?.detail || r.reason?.message || t('common.error'))) }
      })
      } finally {
        batchLoading.value = false
      }
      if (fail > 0) { message.warning(t('scenarios.stopAllPartial', { success: ok, fail })) } else { message.success(t('scenarios.stoppedCount', { count: ok })) }
      loadData()
    }
  })
}

function cancelCreateScenario() {
  showCreateModal.value = false
  newScenario.value = { id: '', name: '', description: '', devices: [], rules: [] }
}

async function createScenario() {
  if (!newScenario.value.id || !newScenario.value.name) {
    message.warning(t('scenarios.idNameRequired'))
    return
  }
  creating.value = true
  try {
    await api.createScenario(newScenario.value)
    showCreateModal.value = false
    newScenario.value = { id: '', name: '', description: '', devices: [], rules: [] }
    message.success(t('scenarios.createSuccess'))
    await loadData()
  } catch (e) {
    message.error(t('scenarios.createFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

function cancelImportScenario() {
  showImportModal.value = false
  importJson.value = ''
}

async function importScenario() {
  if (!importJson.value.trim()) {
    message.warning(t('scenarios.importJsonRequired'))
    return
  }
  importing.value = true
  try {
    const config = JSON.parse(importJson.value)
    if (!config || typeof config !== 'object') {
      message.error(t('scenarios.jsonFormatError') + ': expected object')
      return
    }
    if (!config.id || !config.name) {
      message.error(t('scenarios.jsonFormatError') + ': missing required fields (id, name)')
      return
    }
    await api.importScenario(config)
    showImportModal.value = false
    importJson.value = ''
    message.success(t('scenarios.importSuccess'))
    await loadData()
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error(t('scenarios.jsonFormatError') + ': ' + e.message)
    } else {
      message.error(t('scenarios.importFailed') + ': ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    importing.value = false
  }
}

async function startScene(id) {
  dialog.info({
    title: t('scenarios.confirmStart'),
    content: t('scenarios.confirmStartDesc'),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      togglingIds.value.add(id)
      try {
        await api.startScenario(id)
        message.success(t('scenarios.sceneStarted'))
        await loadData()
      } catch (e) {
        message.error(t('scenarios.startFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { togglingIds.value.delete(id) }
    },
  })
}

async function stopScene(id) {
  dialog.warning({
    title: t('scenarios.confirmStopScene'),
    content: t('scenarios.confirmStopSceneDesc'),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      togglingIds.value.add(id)
      try {
        await api.stopScenario(id)
        message.success(t('scenarios.sceneStopped'))
        await loadData()
      } catch (e) {
        message.error(t('scenarios.stopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { togglingIds.value.delete(id) }
    },
  })
}

async function exportScene(id) {
  try {
    const res = await api.exportScenario(id)
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `scenario_${id}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('scenarios.exportSuccess'))
  } catch (e) {
    message.error(t('scenarios.exportFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function viewSnapshot(id) {
  try {
    const res = await api.getScenarioSnapshot(id)
    snapshotDevices.value = res.devices || []
    showSnapshotModal.value = true
  } catch (e) {
    message.error(t('scenarios.snapshotFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

function confirmDelete(row) {
  dialog.warning({
    title: t('common.delete'),
    content: t('scenarios.confirmDelete', { name: row.name, id: row.id }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => deleteScenario(row.id),
  })
}

async function deleteScenario(id) {
  dialog.warning({
    title: t('common.confirmDelete'),
    content: t('scenarios.confirmDeleteDesc'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      deletingIds.value.add(id)
      try {
        await api.deleteScenario(id)
        message.success(t('scenarios.sceneDeleted'))
        await loadData()
      } catch (e) {
        message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { deletingIds.value.delete(id) }
    }
  })
}

onMounted(loadData)
</script>
