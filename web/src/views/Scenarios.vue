<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">仿真场景</div>
        <div class="pf-section-desc">组合多个设备并定义联动规则</div>
      </div>
      <n-space>
        <n-button v-if="selectedIds.length > 0" type="primary" @click="batchStart" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          启动选中({{ selectedIds.length }})
        </n-button>
        <n-button v-if="selectedIds.length > 0" type="warning" @click="batchStop" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          停止选中({{ selectedIds.length }})
        </n-button>
        <n-button @click="startAllScenes" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          全部启动
        </n-button>
        <n-button @click="stopAllScenes" :loading="batchLoading">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          全部停止
        </n-button>
        <n-button tertiary @click="showImportModal = true">导入场景</n-button>
        <n-button type="primary" @click="showCreateModal = true">创建场景</n-button>
      </n-space>
    </n-space>

    <n-data-table v-if="scenarios.length > 0" :columns="columns" :data="scenarios" :bordered="false"
      :pagination="{ pageSize: 15 }" :row-key="row => row.id"
      v-model:checked-row-keys="selectedIds" :single-line="false" />

    <n-card v-else style="text-align:center;padding:40px">
      <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5" style="margin-bottom:16px"><path d="M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9"/></svg>
      <div class="pf-section-title" style="font-size:16px">还没有仿真场景</div>
      <div style="margin-top: 12px">
        <n-text depth="3">场景可以组合多个设备并定义联动规则</n-text>
      </div>
      <div style="margin-top: 16px">
        <n-space justify="center">
          <n-button type="primary" @click="showCreateModal = true">创建场景</n-button>
          <n-button @click="goDashboard">返回仪表盘快速创建</n-button>
        </n-space>
      </div>
    </n-card>

    <n-modal v-model:show="showCreateModal" preset="card" title="创建场景" style="width: 500px">
      <n-form :model="newScenario" label-placement="left" label-width="80">
        <n-form-item label="场景ID">
          <n-input v-model:value="newScenario.id" placeholder="如: factory-001" />
        </n-form-item>
        <n-form-item label="场景名称">
          <n-input v-model:value="newScenario.name" placeholder="如: 智慧工厂" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="newScenario.description" type="textarea" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showCreateModal = false">取消</n-button>
          <n-button type="primary" @click="createScenario" :loading="creating">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showImportModal" preset="card" title="导入场景" style="width: 500px">
      <n-space vertical>
        <n-alert type="info" :bordered="false">粘贴场景配置 JSON 进行导入</n-alert>
        <n-input v-model:value="importJson" type="textarea" :rows="8" placeholder="粘贴场景 JSON..." />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showImportModal = false">取消</n-button>
          <n-button type="primary" @click="importScenario" :loading="importing">导入</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showSnapshotModal" preset="card" title="场景快照" style="width: 700px">
      <n-data-table :columns="snapshotColumns" :data="snapshotDevices" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" />
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NSpace, NButton, NDataTable, NModal, NForm, NFormItem, NInput, NTag, NAlert, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'

import { useRouter } from 'vue-router'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const scenarios = ref([])
const selectedIds = ref([])
const batchLoading = ref(false)
const showCreateModal = ref(false)
const showImportModal = ref(false)
const showSnapshotModal = ref(false)
const creating = ref(false)
const importing = ref(false)
const importJson = ref('')
const snapshotDevices = ref([])
const newScenario = ref({ id: '', name: '', description: '', devices: [], rules: [] })

const columns = [
  { type: 'selection' },
  { title: 'ID', key: 'id', width: 150 },
  { title: '名称', key: 'name', width: 180 },
  { title: '设备数', key: 'device_count', width: 80, render: (row) => row.device_count ?? (row.devices || []).length },
  { title: '规则数', key: 'rule_count', width: 80, render: (row) => row.rule_count ?? (row.rules || []).length },
  {
    title: '状态', key: 'status', width: 100,
    render: (row) => {
      const map = { running: 'success', stopped: 'default', error: 'error' }
      const labels = { running: '运行中', stopped: '已停止', error: '错误' }
      return h(NTag, { type: map[row.status] || 'default', size: 'small' }, () => labels[row.status] || row.status)
    }
  },
  {
    title: '操作', key: 'actions', width: 380,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      row.status !== 'running'
        ? h(NButton, { size: 'small', type: 'primary', onClick: () => startScene(row.id) }, () => '启动')
        : h(NButton, { size: 'small', type: 'warning', onClick: () => stopScene(row.id) }, () => '停止'),
      h(NButton, { size: 'small', onClick: () => editScene(row.id) }, () => '编辑'),
      h(NButton, { size: 'small', onClick: () => exportScene(row.id) }, () => '导出'),
      h(NButton, { size: 'small', onClick: () => viewSnapshot(row.id) }, () => '快照'),
      h(NButton, { size: 'small', type: 'error', onClick: () => confirmDelete(row) }, () => '删除'),
    ])
  },
]

const snapshotColumns = [
  { title: '设备ID', key: 'id', width: 150 },
  { title: '名称', key: 'name', width: 150 },
  { title: '协议', key: 'protocol', width: 100 },
  { title: '状态', key: 'status', width: 80 },
  { title: '测点数', key: 'points', width: 80, render: (row) => row.points?.length || 0 },
]

function goDashboard() {
  router.push('/')
}

function editScene(id) {
  router.push(`/scenario/${id}`)
}

async function loadData() {
  try {
    const res = await api.getScenarios()
    scenarios.value = res
  } catch (e) {
    message.error('加载场景失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function batchStart() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const id of selectedIds.value) {
    try { await api.startScenario(id); ok++ } catch (e) { fail++; console.warn('启动场景失败:', id, e) }
  }
  batchLoading.value = false
  selectedIds.value = []
  const msg = `已启动 ${ok} 个场景` + (fail ? `，${fail} 个失败` : '')
  if (fail > 0 && ok === 0) message.error(msg)
  else if (fail > 0) message.warning(msg)
  else message.success(msg)
  loadData()
}

async function batchStop() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const id of selectedIds.value) {
    try { await api.stopScenario(id); ok++ } catch (e) { fail++; console.warn('停止场景失败:', id, e) }
  }
  batchLoading.value = false
  selectedIds.value = []
  const msg = `已停止 ${ok} 个场景` + (fail ? `，${fail} 个失败` : '')
  if (fail > 0 && ok === 0) message.error(msg)
  else if (fail > 0) message.warning(msg)
  else message.success(msg)
  loadData()
}

async function startAllScenes() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const sc of scenarios.value) {
    try { await api.startScenario(sc.id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  message.success(`已启动 ${ok} 个场景` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function stopAllScenes() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const sc of scenarios.value) {
    try { await api.stopScenario(sc.id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  message.success(`已停止 ${ok} 个场景` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function createScenario() {
  creating.value = true
  try {
    await api.createScenario(newScenario.value)
    showCreateModal.value = false
    newScenario.value = { id: '', name: '', description: '', devices: [], rules: [] }
    message.success('场景创建成功')
    await loadData()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

async function importScenario() {
  importing.value = true
  try {
    const config = JSON.parse(importJson.value)
    await api.importScenario(config)
    showImportModal.value = false
    importJson.value = ''
    message.success('场景导入成功')
    await loadData()
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error('JSON 格式错误: ' + e.message)
    } else {
      message.error('导入失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    importing.value = false
  }
}

async function startScene(id) {
  try {
    await api.startScenario(id)
    message.success('场景已启动')
    await loadData()
  } catch (e) {
    message.error('启动失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function stopScene(id) {
  try {
    await api.stopScenario(id)
    message.success('场景已停止')
    await loadData()
  } catch (e) {
    message.error('停止失败: ' + (e.response?.data?.detail || e.message))
  }
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
    message.success('场景已导出')
  } catch (e) {
    message.error('导出失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function viewSnapshot(id) {
  try {
    const res = await api.getScenarioSnapshot(id)
    snapshotDevices.value = res.devices || []
    showSnapshotModal.value = true
  } catch (e) {
    message.error('获取快照失败: ' + (e.response?.data?.detail || e.message))
  }
}

function confirmDelete(row) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除场景 "${row.name}" (${row.id}) 吗？此操作不可撤销。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteScenario(row.id),
  })
}

async function deleteScenario(id) {
  try {
    await api.deleteScenario(id)
    message.success('场景已删除')
    await loadData()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadData)
</script>
