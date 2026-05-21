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
            <n-popconfirm @positive-click="handleClearAll" :positive-text="t('common.confirm')" :negative-text="t('common.cancel')">
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
          <n-statistic :label="t('audit.recentOperations')" :value="auditStats.last_action ? getActionLabel(auditStats.last_action) : '-'" />
        </n-gi>
      </n-grid>
      <n-space vertical size="small" style="margin-bottom:12px">
        <n-space size="small" align="center">
          <n-select v-model:value="filterUsername" :placeholder="t('common.username')" size="small" style="width:150px" clearable filterable :options="usernameOptions" />
          <n-select v-model:value="filterAction" :placeholder="t('audit.actionType')" size="small" style="width:180px" clearable filterable :options="actionOptions" />
          <n-select v-model:value="filterResource" :placeholder="t('audit.resourceType')" size="small" style="width:150px" clearable :options="resourceOptions" />
          <n-button size="small" type="primary" @click="loadData">{{ t('common.search') }}</n-button>
        </n-space>
      </n-space>
      <n-data-table :columns="columns" :data="entries" :bordered="true" size="small"
        :loading="loading" :scroll-x="900" />
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
import { NCard, NSpace, NButton, NDataTable, NInput, NTag, NPopconfirm, NGrid, NGi, NStatistic, NPagination, NSelect, useMessage } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const entries = ref([])
const loading = ref(false)
const clearing = ref(false)
const filterUsername = ref(null)
const filterAction = ref(null)
const filterResource = ref(null)
const auditStats = ref(null)
const currentPage = ref(1)
const pageSize = ref(20)
const totalEntries = ref(0)

// FIXED: 搜索项从文本输入改为下拉选择，提升用户体验
const usernameOptions = ref([])
const actionOptions = computed(() => [
  { label: t('audit.action.create_device'), value: 'create_device' },
  { label: t('audit.action.delete_device'), value: 'delete_device' },
  { label: t('audit.action.update_device'), value: 'update_device' },
  { label: t('audit.action.create_scenario'), value: 'create_scenario' },
  { label: t('audit.action.delete_scenario'), value: 'delete_scenario' },
  { label: t('audit.action.update_scenario'), value: 'update_scenario' },
  { label: t('audit.action.create_template'), value: 'create_template' },
  { label: t('audit.action.delete_template'), value: 'delete_template' },
  { label: t('audit.action.update_template'), value: 'update_template' },
  { label: t('audit.action.start_protocol'), value: 'start_protocol' },
  { label: t('audit.action.stop_protocol'), value: 'stop_protocol' },
  { label: t('audit.action.run_test'), value: 'run_test' },
  { label: t('audit.action.login'), value: 'login' },
  { label: t('audit.action.register'), value: 'register' },
  { label: t('audit.action.change_password'), value: 'change_password' },
  { label: t('audit.action.delete_user'), value: 'delete_user' },
  { label: t('audit.action.update_user_role'), value: 'update_user_role' },
  { label: t('audit.action.import_backup'), value: 'import_backup' },
  { label: t('audit.action.create_webhook'), value: 'create_webhook' },
  { label: t('audit.action.delete_webhook'), value: 'delete_webhook' },
  { label: t('audit.action.update_webhook'), value: 'update_webhook' },
  { label: t('audit.action.create_forward'), value: 'create_forward' },
  { label: t('audit.action.delete_forward'), value: 'delete_forward' },
])
const resourceOptions = computed(() => [
  { label: t('audit.resource.device'), value: 'device' },
  { label: t('audit.resource.scenario'), value: 'scenario' },
  { label: t('audit.resource.template'), value: 'template' },
  { label: t('audit.resource.protocol'), value: 'protocol' },
  { label: t('audit.resource.test'), value: 'test' },
  { label: t('audit.resource.auth'), value: 'auth' },
  { label: t('audit.resource.system'), value: 'system' },
  { label: t('audit.resource.webhook'), value: 'webhook' },
  { label: t('audit.resource.forward'), value: 'forward' },
])

// Action i18n mapping
function getActionLabel(action) {
  if (!action) return '-'
  // Try exact match first
  const exactKey = `audit.action.${action}`
  const exact = t(exactKey)
  if (exact !== exactKey) return exact
  // Fallback: try with underscores instead of hyphens
  const normalized = action.replace(/-/g, '_')
  const normKey = `audit.action.${normalized}`
  const norm = t(normKey)
  if (norm !== normKey) return norm
  // Fallback to raw action
  return action
}

// Get tag type based on action name
function getActionTagType(action) {
  if (!action) return 'default'
  if (action.includes('delete')) return 'error'
  if (action.includes('create') || action.includes('register') || action.includes('login')) return 'success'
  if (action.includes('start')) return 'info'
  if (action.includes('stop')) return 'warning'
  return 'default'
}

// Resource type i18n mapping
function getResourceTypeLabel(resourceType) {
  if (!resourceType) return '-'
  const key = `audit.resource.${resourceType}`
  const label = t(key)
  return label !== key ? label : resourceType
}

const columns = computed(() => [
  { title: t('common.time'), key: 'timestamp', width: 170, fixed: 'left', render: (row) => {
    if (!row.timestamp) return '-'
    const ts = row.timestamp > 1e12 ? row.timestamp : row.timestamp * 1000
    return new Date(ts).toLocaleString()
  }},
  { title: t('common.username'), key: 'username', width: 120 },
  { title: t('audit.actionType'), key: 'action', width: 140, render: (row) => h(NTag, { size: 'tiny', type: getActionTagType(row.action), bordered: false }, () => getActionLabel(row.action)) },
  { title: t('audit.resourceType'), key: 'resource_type', width: 100, render: (row) => getResourceTypeLabel(row.resource_type) },
  { title: t('audit.resourceId'), key: 'resource_id', width: 140, ellipsis: { tooltip: true } },
  { title: t('common.detail'), key: 'detail', minWidth: 200, ellipsis: { tooltip: true } },
  {
    title: t('common.action'), key: 'actions', width: 80, fixed: 'right',
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

async function loadUserOptions() {
  try {
    const users = await api.listUsers()
    if (Array.isArray(users)) {
      usernameOptions.value = users.map(u => ({ label: u.username || u, value: u.username || u }))
    }
  } catch (e) {
    // Non-critical: username filter falls back to empty options
    usernameOptions.value = []
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
  loadUserOptions()
})
</script>
