<template>
  <div>
    <n-card size="small">
      <template #header>
        <n-space align="center" justify="space-between">
          <n-space align="center" size="small">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8"/></svg>
            <span style="font-weight:600">审计日志</span>
          </n-space>
          <n-space size="small">
            <n-button size="small" @click="loadData" :loading="loading">刷新</n-button>
            <n-popconfirm @positive-click="handleClearAll">
              <template #trigger><n-button size="small" type="warning">清空日志</n-button></template>
              确定要清空所有审计日志吗？此操作不可恢复。
            </n-popconfirm>
          </n-space>
        </n-space>
      </template>
      <n-space vertical size="small" style="margin-bottom:12px">
        <n-space size="small" align="center">
          <n-input v-model:value="filterUsername" placeholder="用户名" size="small" style="width:140px" clearable />
          <n-input v-model:value="filterAction" placeholder="操作类型" size="small" style="width:140px" clearable />
          <n-input v-model:value="filterResource" placeholder="资源类型" size="small" style="width:140px" clearable />
          <n-button size="small" type="primary" @click="loadData">筛选</n-button>
        </n-space>
      </n-space>
      <n-data-table :columns="columns" :data="entries" :bordered="false" size="small"
        :pagination="{ pageSize: 20 }" :loading="loading" />
    </n-card>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NCard, NSpace, NButton, NDataTable, NInput, NTag, NPopconfirm, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const entries = ref([])
const loading = ref(false)
const filterUsername = ref('')
const filterAction = ref('')
const filterResource = ref('')

const columns = [
  { title: '时间', key: 'timestamp', width: 170, render: (row) => row.timestamp ? new Date(row.timestamp * 1000).toLocaleString() : '-' },
  { title: '用户', key: 'username', width: 120 },
  { title: '操作', key: 'action', width: 120, render: (row) => h(NTag, { size: 'tiny', type: row.action?.includes('delete') ? 'error' : row.action?.includes('create') ? 'success' : 'info', bordered: false }, () => row.action) },
  { title: '资源类型', key: 'resource_type', width: 100 },
  { title: '资源ID', key: 'resource_id', width: 140, ellipsis: { tooltip: true } },
  { title: '详情', key: 'detail', ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 70,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => handleDelete(row.id) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error', tertiary: true }, () => '删除'),
      default: () => '确定删除此条记录？'
    }),
  },
]

async function loadData() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (filterUsername.value) params.username = filterUsername.value
    if (filterAction.value) params.action = filterAction.value
    if (filterResource.value) params.resource_type = filterResource.value
    entries.value = await api.queryAuditLog(params)
  } catch (e) {
    message.error('加载审计日志失败')
  } finally {
    loading.value = false
  }
}

async function handleDelete(id) {
  try {
    await api.deleteAuditEntry(id)
    message.success('已删除')
    await loadData()
  } catch (e) {
    message.error('删除失败')
  }
}

async function handleClearAll() {
  try {
    await api.clearAuditLog()
    message.success('已清空')
    await loadData()
  } catch (e) {
    message.error('清空失败')
  }
}

onMounted(loadData)
</script>
