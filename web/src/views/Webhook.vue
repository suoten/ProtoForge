<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('webhook.title') }}</div>
        <div class="pf-section-desc">{{ t('webhook.subtitle') }}</div>
      </div>
      <n-space>
        <n-button @click="loadWebhooks" :loading="loading">{{ t('common.refresh') }}</n-button>
        <n-button type="primary" @click="showAddModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
          {{ t('webhook.addWebhook') }}
        </n-button>
      </n-space>
    </n-space>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ webhooks.length }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('webhook.totalCount') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-green">
          <div class="pf-stat-value">{{ enabledCount }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('webhook.enabledCount') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-orange">
          <div class="pf-stat-value">{{ webhookStats.total_triggers || 0 }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('webhook.triggerCount') }}</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-rose">
          <div class="pf-stat-value">{{ webhookStats.error_rate ? (webhookStats.error_rate * 100).toFixed(1) + '%' : '0%' }}</div>
          <div style="font-size:13px;opacity:0.9">{{ t('webhook.errorRate') }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" :title="t('webhook.webhookList')">
      <n-data-table v-if="webhooks.length > 0" :columns="columns" :data="webhooks" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
      <n-empty v-else :description="t('webhook.noWebhooks')">
        <template #extra>
          <n-button @click="showAddModal = true">{{ t('webhook.addWebhook') }}</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showAddModal" preset="card" :title="t('webhook.addTitle')" style="width:560px">
      <n-form :model="addForm" label-placement="left" label-width="120">
        <n-form-item :label="t('webhook.webhookName')">
          <n-input v-model:value="addForm.name" :placeholder="t('webhook.namePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.callbackUrl')">
          <n-input v-model:value="addForm.url" :placeholder="t('webhook.callbackUrlPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.triggerEvents')">
          <n-select v-model:value="addForm.events" :options="eventOptions" multiple filterable :placeholder="t('webhook.selectEvents')" />
        </n-form-item>
        <n-form-item :label="t('webhook.httpMethod')">
          <n-select v-model:value="addForm.method" :options="methodOptions" :placeholder="t('common.selectPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.headers')">
          <n-input v-model:value="addForm.headers_json" type="textarea" :rows="3" :placeholder="t('webhook.headersPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.enabledLabel')">
          <n-switch v-model:value="addForm.enabled" />
        </n-form-item>
        <n-form-item :label="t('webhook.descriptionLabel')">
          <n-input v-model:value="addForm.description" type="textarea" :rows="2" :placeholder="t('webhook.descriptionPlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="addWebhook" :loading="adding">{{ t('common.add') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEditModal" preset="card" :title="t('webhook.editTitle')" style="width:560px">
      <n-form :model="editForm" label-placement="left" label-width="120">
        <n-form-item :label="t('webhook.webhookName')">
          <n-input v-model:value="editForm.name" :placeholder="t('webhook.namePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.callbackUrl')">
          <n-input v-model:value="editForm.url" :placeholder="t('webhook.callbackUrlPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.triggerEvents')">
          <n-select v-model:value="editForm.events" :options="eventOptions" multiple filterable :placeholder="t('webhook.selectEvents')" />
        </n-form-item>
        <n-form-item :label="t('webhook.httpMethod')">
          <n-select v-model:value="editForm.method" :options="methodOptions" :placeholder="t('common.selectPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('webhook.headers')">
          <n-input v-model:value="editForm.headers_json" type="textarea" :rows="3" />
        </n-form-item>
        <n-form-item :label="t('webhook.enabledLabel')">
          <n-switch v-model:value="editForm.enabled" />
        </n-form-item>
        <n-form-item :label="t('webhook.descriptionLabel')">
          <n-input v-model:value="editForm.description" type="textarea" :rows="2" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showEditModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="updateWebhook" :loading="saving">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NButton, NCard, NDataTable, NModal, NForm, NFormItem,
  NInput, NSelect, NSwitch, NGrid, NGi, NTag, NEmpty, NPopconfirm,
  NText, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()

const webhooks = ref([])
const webhookStats = ref({})
const loading = ref(false)
const showAddModal = ref(false)
const showEditModal = ref(false)
const adding = ref(false)
const saving = ref(false)
const testingIds = ref(new Set())
const deletingIds = ref(new Set())
const editingId = ref('')

const addForm = ref({
  name: '', url: '', events: [], method: 'POST',
  headers_json: '', enabled: true, description: '',
})

const editForm = ref({
  name: '', url: '', events: [], method: 'POST',
  headers_json: '', enabled: true, description: '',
})

const enabledCount = computed(() => webhooks.value.filter(w => w.enabled !== false).length)

const eventOptions = computed(() => [
  { label: t('webhook.deviceOnline'), value: 'device_online' },
  { label: t('webhook.deviceOffline'), value: 'device_offline' },
  { label: t('webhook.dataChange'), value: 'data_change' },
  { label: t('webhook.scenarioStart'), value: 'scenario_start' },
  { label: t('webhook.scenarioStop'), value: 'scenario_stop' },
  { label: t('webhook.testComplete'), value: 'test_complete' },
  { label: t('webhook.alarmTriggered'), value: 'alarm_triggered' },
  { label: t('webhook.systemError'), value: 'system_error' },
  { label: t('webhook.testEvent'), value: 'test' },
])

const methodOptions = [
  { label: 'POST', value: 'POST' },
  { label: 'PUT', value: 'PUT' },
  { label: 'PATCH', value: 'PATCH' },
]

const columns = computed(() => [
  { title: t('common.name'), key: 'name', width: 150, ellipsis: { tooltip: true } },
  { title: 'URL', key: 'url', width: 280, ellipsis: { tooltip: true } },
  {
    title: t('webhook.triggerEvents'), key: 'events', width: 200,
    render: (row) => {
      const evts = row.events || []
      if (evts.length === 0) return h(NText, { depth: 3, style: 'font-size:12px' }, () => t('common.noSelection'))
      if (evts.length <= 2) {
        return evts.map(e => h(NTag, { size: 'tiny', type: 'info', bordered: false, style: 'margin-right:4px' }, () => e))
      }
      return h(NSpace, { size: 4 }, () => [
        h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => evts[0]),
        h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => `+${evts.length - 1}`),
      ])
    }
  },
  { title: t('webhook.httpMethod'), key: 'method', width: 80 },
  {
    title: t('common.status'), key: 'enabled', width: 80,
    render: (row) => row.enabled !== false
      ? h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => t('common.enabled'))
      : h(NTag, { size: 'tiny', type: 'default', bordered: false }, () => t('common.disabled'))
  },
  {
    title: t('common.action'), key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'info', secondary: true, loading: testingIds.value.has(row.id), onClick: () => testWebhookAction(row.id) }, () => t('common.test')),
      h(NButton, { size: 'tiny', secondary: true, onClick: () => openEdit(row) }, () => t('common.edit')),
      h(NPopconfirm, { onPositiveClick: () => deleteWebhookAction(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => t('common.delete')),
        default: () => t('webhook.confirmDelete', { name: row.name }),
      })
    ])
  },
])

async function loadWebhooks() {
  loading.value = true
  try {
    const res = await api.listWebhooks()
    webhooks.value = (res || []).map(w => ({
      ...w,
      events: w.events || [],
      enabled: w.enabled !== false,
    }))
  } catch (e) {
    message.error(t('webhook.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    webhookStats.value = await api.getWebhookStats()
  } catch (e) {
    webhookStats.value = webhookStats.value || {}
    message.warning(t('webhook.loadStatsFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function addWebhook() {
  if (!addForm.value.url?.trim()) { message.warning(t('webhook.callbackUrlRequired')); return }
  if (!addForm.value.events?.length) { message.warning(t('webhook.selectOneEvent')); return }
  adding.value = true
  try {
    if (!addForm.value.url?.trim()) { message.warning(t('webhook.urlRequired')); adding.value = false; return }
    try { const u = new URL(addForm.value.url); if (!['http:','https:'].includes(u.protocol)) throw new Error() } catch { message.warning(t('webhook.urlInvalid')); adding.value = false; return }
    const cfg = {
      name: addForm.value.name || `webhook-${Date.now()}`,
      url: addForm.value.url,
      events: addForm.value.events,
      method: addForm.value.method,
      enabled: addForm.value.enabled,
      description: addForm.value.description,
    }
    if (addForm.value.headers_json) {
      try { cfg.headers = JSON.parse(addForm.value.headers_json) }
      catch { message.warning(t('webhook.headersJsonError')); adding.value = false; return }
    }
    await api.addWebhook(cfg)
    showAddModal.value = false
    addForm.value = { name: '', url: '', events: [], method: 'POST', headers_json: '', enabled: true, description: '' }
    message.success(t('webhook.webhookAdded'))
    await loadWebhooks()
  } catch (e) {
    message.error(t('webhook.addFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { adding.value = false }
}

function openEdit(row) {
  editingId.value = row.id
  editForm.value = {
    name: row.name || '',
    url: row.url || '',
    events: [...(row.events || [])],
    method: row.method || 'POST',
    headers_json: row.headers ? JSON.stringify(row.headers) : '',
    enabled: row.enabled !== false,
    description: row.description || '',
  }
  showEditModal.value = true
}

async function updateWebhook() {
  if (!editForm.value.url) { message.warning(t('webhook.callbackUrlRequired')); return }
  saving.value = true
  try {
    const cfg = {
      name: editForm.value.name,
      url: editForm.value.url,
      events: editForm.value.events,
      method: editForm.value.method,
      enabled: editForm.value.enabled,
      description: editForm.value.description,
    }
    if (editForm.value.headers_json) {
      try { cfg.headers = JSON.parse(editForm.value.headers_json) }
      catch { message.warning(t('webhook.headersJsonError')); saving.value = false; return }
    }
    await api.updateWebhook(editingId.value, cfg)
    showEditModal.value = false
    message.success(t('webhook.webhookUpdated'))
    await loadWebhooks()
  } catch (e) {
    message.error(t('webhook.updateFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

async function testWebhookAction(id) {
  testingIds.value.add(id)
  try {
    await api.testWebhook(id)
    message.success(t('webhook.testTriggered'))
  } catch (e) {
    message.error(t('webhook.testFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { testingIds.value.delete(id) }
}

async function deleteWebhookAction(id) {
  deletingIds.value.add(id)
  try {
    await api.deleteWebhook(id)
    message.success(t('common.deleted'))
    await loadWebhooks()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { deletingIds.value.delete(id) }
}

onMounted(() => {
  loadWebhooks()
  loadStats()
})
</script>
