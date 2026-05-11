<template>
  <div>
    <n-card size="small">
      <template #header>
        <n-space align="center" justify="space-between">
          <n-space align="center" size="small">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8"/></svg>
            <span style="font-weight:600">{{ t('audit.title') }}</span>
          </n-space>
          <n-space size="small">
            <n-button size="small" @click="loadData" :loading="loading">{{ t('audit.refresh') }}</n-button>
            <n-popconfirm @positive-click="handleClearAll">
              <template #trigger><n-button size="small" type="warning" :loading="clearing">{{ t('audit.clearLog') }}</n-button></template>
              {{ t('audit.confirmClear') }}
            </n-popconfirm>
          </n-space>
        </n-space>
      </template>
      <n-grid :cols="4" :x-gap="12" :y-gap="8" style="margin-bottom:12px" v-if="auditStats">
        <n-gi>
          <n-statistic :label="t('audit.totalRecords')" :value="auditStats.total_entries || 0" />
        </n-gi>
        <n-gi>
          <n-statistic :label="t('audit.todayOperations')" :value="auditStats.today_count || 0" />
        </n-gi>
        <n-gi>
          <n-statistic :label="t('audit.activeUsers')" :value="Array.isArray(auditStats.active_users) ? auditStats.active_users.length : (auditStats.active_users || 0)" />
        </n-gi>
        <n-gi>
          <n-statistic :label="t('audit.recentOperations')" :value="auditStats.last_action || '-'" />
        </n-gi>
      </n-grid>
      <n-space vertical size="small" style="margin-bottom:12px">
        <n-space size="small" align="center">
          <n-input v-model:value="filterUsername" :placeholder="t('common.username')" size="small" style="width:140px" clearable />
          <n-input v-model:value="filterAction" :placeholder="t('audit.actionType')" size="small" style="width:140px" clearable />
          <n-input v-model:value="filterResource" :placeholder="t('audit.resourceType')" size="small" style="width:140px" clearable />
          <n-button size="small" type="primary" @click="loadData">{{ t('common.search') }}</n-button>
        </n-space>
      </n-space>
      <n-data-table :columns="columns" :data="entries" :bordered="false" size="small"
        :loading="loading" />
      <n-space justify="end" style="margin-top:12px" v-if="totalEntries > 0">
        <n-pagination v-model:page="currentPage" v-model:page-size="pageSize"
          :item-count="totalEntries" :page-sizes="[20, 50, 100, 200]"
          show-size-picker @update:page="loadData" @update:page-size="onPageSizeChange" />
      </n-space>
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NCard, NSpace, NButton, NDataTable, NInput, NTag, NPopconfirm, NGrid, NGi, NStatistic, NPagination, useMessage } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const entries = ref([])
const loading = ref(false)
const clearing = ref(false)
const filterUsername = ref('')
const filterAction = ref('')
const filterResource = ref('')
const auditStats = ref(null)
const currentPage = ref(1)
const pageSize = ref(20)
const totalEntries = ref(0)

const columns = computed(() => [
  { title: t('common.time'), key: 'timestamp', width: 170, render: (row) => {
    if (!row.timestamp) return '-'
    const ts = row.timestamp > 1e12 ? row.timestamp : row.timestamp * 1000
    return new Date(ts).toLocaleString()
  }},
  { title: t('common.username'), key: 'username', width: 120 },
  { title: t('common.action'), key: 'action', width: 120, render: (row) => h(NTag, { size: 'tiny', type: (row.action || '').includes('delete') ? 'error' : (row.action || '').includes('create') ? 'success' : 'info', bordered: false }, () => row.action || '-') },
  { title: t('audit.resourceType'), key: 'resource_type', width: 100 },
  { title: t('audit.resourceId'), key: 'resource_id', width: 140, ellipsis: { tooltip: true } },
  { title: t('common.detail'), key: 'detail', ellipsis: { tooltip: true } },
  {
    title: t('common.action'), key: 'actions', width: 70,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => handleDelete(row.id) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error', tertiary: true }, () => t('common.delete')),
      default: () => t('common.confirmDelete')
    }),
  },
])

async function loadData() {
  loading.value = true
  try {
    const params = {
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
    }
    if (filterUsername.value) params.username = filterUsername.value
    if (filterAction.value) params.action = filterAction.value
    if (filterResource.value) params.resource_type = filterResource.value
    const res = await api.queryAuditLog(params)
    if (res && typeof res === 'object' && !Array.isArray(res)) {
      entries.value = res.entries || []
      totalEntries.value = res.total || 0
    } else if (Array.isArray(res)) {
      entries.value = res
      totalEntries.value = res.length
    } else {
      entries.value = []
      totalEntries.value = 0
    }
  } catch (e) {
    message.error(t('audit.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function onPageSizeChange() {
  currentPage.value = 1
  loadData()
}

async function loadAuditStats() {
  try {
    auditStats.value = await api.getAuditStats()
  } catch (e) {
    auditStats.value = null
    message.warning(t('audit.statsFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function handleDelete(id) {
  try {
    await api.deleteAuditEntry(id)
    message.success(t('common.deleted'))
    await loadData()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function handleClearAll() {
  clearing.value = true
  try {
    await api.clearAuditLog()
    message.success(t('audit.cleared'))
    await loadData()
  } catch (e) {
    message.error(t('audit.clearFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    clearing.value = false
  }
}

onMounted(() => {
  loadData()
  loadAuditStats()
})
</script>
