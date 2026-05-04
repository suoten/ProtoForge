<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">Webhook 管理</div>
        <div class="pf-section-desc">配置事件回调，将系统事件实时推送到外部服务</div>
      </div>
      <n-space>
        <n-button @click="loadWebhooks" :loading="loading">刷新</n-button>
        <n-button type="primary" @click="showAddModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
          添加 Webhook
        </n-button>
      </n-space>
    </n-space>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ webhooks.length }}</div>
          <div style="font-size:13px;opacity:0.9">总数</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-green">
          <div class="pf-stat-value">{{ enabledCount }}</div>
          <div style="font-size:13px;opacity:0.9">已启用</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-orange">
          <div class="pf-stat-value">{{ webhookStats.total_triggers || 0 }}</div>
          <div style="font-size:13px;opacity:0.9">触发次数</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" class="pf-gradient-card-rose">
          <div class="pf-stat-value">{{ webhookStats.error_rate ? (webhookStats.error_rate * 100).toFixed(1) + '%' : '0%' }}</div>
          <div style="font-size:13px;opacity:0.9">错误率</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" title="Webhook 列表">
      <n-data-table v-if="webhooks.length > 0" :columns="columns" :data="webhooks" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
      <n-empty v-else description="暂无 Webhook，点击添加配置回调">
        <template #extra>
          <n-button @click="showAddModal = true">添加 Webhook</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showAddModal" preset="card" title="添加 Webhook" style="width:560px">
      <n-form :model="addForm" label-placement="left" label-width="120">
        <n-form-item label="名称">
          <n-input v-model:value="addForm.name" placeholder="如 告警通知" />
        </n-form-item>
        <n-form-item label="回调URL">
          <n-input v-model:value="addForm.url" placeholder="https://example.com/webhook" />
        </n-form-item>
        <n-form-item label="触发事件">
          <n-select v-model:value="addForm.events" :options="eventOptions" multiple filterable placeholder="选择触发事件" />
        </n-form-item>
        <n-form-item label="HTTP方法">
          <n-select v-model:value="addForm.method" :options="methodOptions" />
        </n-form-item>
        <n-form-item label="请求头(JSON)">
          <n-input v-model:value="addForm.headers_json" type="textarea" :rows="3" placeholder='{"Authorization": "Bearer xxx"}' />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="addForm.enabled" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="addForm.description" type="textarea" :rows="2" placeholder="Webhook 描述（可选）" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddModal = false">取消</n-button>
          <n-button type="primary" @click="addWebhook" :loading="adding">添加</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEditModal" preset="card" title="编辑 Webhook" style="width:560px">
      <n-form :model="editForm" label-placement="left" label-width="120">
        <n-form-item label="名称">
          <n-input v-model:value="editForm.name" placeholder="如 告警通知" />
        </n-form-item>
        <n-form-item label="回调URL">
          <n-input v-model:value="editForm.url" placeholder="https://example.com/webhook" />
        </n-form-item>
        <n-form-item label="触发事件">
          <n-select v-model:value="editForm.events" :options="eventOptions" multiple filterable placeholder="选择触发事件" />
        </n-form-item>
        <n-form-item label="HTTP方法">
          <n-select v-model:value="editForm.method" :options="methodOptions" />
        </n-form-item>
        <n-form-item label="请求头(JSON)">
          <n-input v-model:value="editForm.headers_json" type="textarea" :rows="3" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="editForm.enabled" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="editForm.description" type="textarea" :rows="2" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showEditModal = false">取消</n-button>
          <n-button type="primary" @click="updateWebhook" :loading="saving">保存</n-button>
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

const message = useMessage()
const dialog = useDialog()

const webhooks = ref([])
const webhookStats = ref({})
const loading = ref(false)
const showAddModal = ref(false)
const showEditModal = ref(false)
const adding = ref(false)
const saving = ref(false)
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

const eventOptions = [
  { label: '设备上线 (device_online)', value: 'device_online' },
  { label: '设备下线 (device_offline)', value: 'device_offline' },
  { label: '数据变化 (data_change)', value: 'data_change' },
  { label: '场景启动 (scenario_start)', value: 'scenario_start' },
  { label: '场景停止 (scenario_stop)', value: 'scenario_stop' },
  { label: '测试完成 (test_complete)', value: 'test_complete' },
  { label: '告警触发 (alarm_triggered)', value: 'alarm_triggered' },
  { label: '系统错误 (system_error)', value: 'system_error' },
  { label: '测试事件 (test)', value: 'test' },
]

const methodOptions = [
  { label: 'POST', value: 'POST' },
  { label: 'PUT', value: 'PUT' },
  { label: 'PATCH', value: 'PATCH' },
]

const columns = [
  { title: '名称', key: 'name', width: 150, ellipsis: { tooltip: true } },
  { title: 'URL', key: 'url', width: 280, ellipsis: { tooltip: true } },
  {
    title: '触发事件', key: 'events', width: 200,
    render: (row) => {
      const evts = row.events || []
      if (evts.length === 0) return h(NText, { depth: 3, style: 'font-size:12px' }, () => '未选择')
      if (evts.length <= 2) {
        return evts.map(e => h(NTag, { size: 'tiny', type: 'info', bordered: false, style: 'margin-right:4px' }, () => e))
      }
      return h(NSpace, { size: 4 }, () => [
        h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => evts[0]),
        h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => `+${evts.length - 1}`),
      ])
    }
  },
  { title: '方法', key: 'method', width: 80 },
  {
    title: '状态', key: 'enabled', width: 80,
    render: (row) => row.enabled !== false
      ? h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => '启用')
      : h(NTag, { size: 'tiny', type: 'default', bordered: false }, () => '禁用')
  },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => testWebhookAction(row.id) }, () => '测试'),
      h(NButton, { size: 'tiny', secondary: true, onClick: () => openEdit(row) }, () => '编辑'),
      h(NPopconfirm, { onPositiveClick: () => deleteWebhookAction(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
        default: () => `确定删除 "${row.name}" 吗？`,
      })
    ])
  },
]

async function loadWebhooks() {
  loading.value = true
  try {
    const res = await api.getWebhooks()
    webhooks.value = (res || []).map(w => ({
      ...w,
      events: w.events || [],
      enabled: w.enabled !== false,
    }))
  } catch (e) {
    message.error('加载 Webhook 失败: ' + (e.response?.data?.detail || e.message))
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    webhookStats.value = await api.getWebhookStats()
  } catch (e) { console.warn('加载 Webhook 统计失败:', e) }
}

async function addWebhook() {
  if (!addForm.value.url) { message.warning('请输入回调URL'); return }
  adding.value = true
  try {
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
      catch { message.warning('请求头JSON格式错误'); return }
    }
    await api.addWebhook(cfg)
    showAddModal.value = false
    addForm.value = { name: '', url: '', events: [], method: 'POST', headers_json: '', enabled: true, description: '' }
    message.success('Webhook 已添加')
    await loadWebhooks()
  } catch (e) {
    message.error('添加失败: ' + (e.response?.data?.detail || e.message))
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
  if (!editForm.value.url) { message.warning('请输入回调URL'); return }
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
      catch { message.warning('请求头JSON格式错误'); return }
    }
    await api.updateWebhook(editingId.value, cfg)
    showEditModal.value = false
    message.success('Webhook 已更新')
    await loadWebhooks()
  } catch (e) {
    message.error('更新失败: ' + (e.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

async function testWebhookAction(id) {
  try {
    await api.testWebhook(id)
    message.success('测试已触发，请检查目标服务')
  } catch (e) {
    message.error('测试失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteWebhookAction(id) {
  try {
    await api.deleteWebhook(id)
    message.success('已删除')
    await loadWebhooks()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadWebhooks()
  loadStats()
})
</script>
