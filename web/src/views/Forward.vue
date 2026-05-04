<template>
  <n-space vertical size="large">
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">数据转发</div>
        <div class="pf-section-desc">将仿真数据转发到外部目标（InfluxDB、HTTP、文件等）</div>
      </div>
      <n-space>
        <n-button v-if="forwardRunning" type="warning" @click="stopForward" :loading="stopping">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
          停止转发
        </n-button>
        <n-button v-else type="primary" @click="startForward" :loading="starting">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          启动转发
        </n-button>
        <n-button type="primary" @click="showAddModal = true">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
          添加目标
        </n-button>
      </n-space>
    </n-space>

    <n-alert v-if="forwardRunning" type="success" :bordered="false">
      转发服务运行中 — 已发送: {{ stats.sent_count || 0 }} | 已丢弃: {{ stats.dropped_count || 0 }} | 速率: {{ stats.rate || 0 }}条/秒
    </n-alert>
    <n-alert v-else type="info" :bordered="false">
      转发服务已停止。点击「启动转发」将数据推送到已配置的目标。
    </n-alert>

    <n-grid :cols="4" :x-gap="12" :y-gap="12">
      <n-gi>
        <n-card size="small" class="pf-gradient-card">
          <div class="pf-stat-value">{{ targets.length }}</div>
          <div style="font-size:13px;opacity:0.9">转发目标</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-green' : ''">
          <div class="pf-stat-value">{{ stats.sent_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">已发送</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-orange' : ''">
          <div class="pf-stat-value">{{ stats.dropped_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">已丢弃</div>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :class="forwardRunning ? 'pf-gradient-card-rose' : ''">
          <div class="pf-stat-value">{{ stats.error_count || 0 }}</div>
          <div style="font-size:13px" :style="{ opacity: forwardRunning ? 0.9 : 0.6 }">错误数</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-card size="small" title="转发目标列表">
      <template #header-extra>
        <n-button size="small" @click="loadTargets" :loading="loadingTargets">刷新</n-button>
      </template>
      <n-data-table v-if="targets.length > 0" :columns="targetColumns" :data="targets" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" :row-key="row => row.name" />
      <n-empty v-else description="暂无转发目标，点击「添加目标」配置">
        <template #extra>
          <n-button @click="showAddModal = true">添加目标</n-button>
        </template>
      </n-empty>
    </n-card>

    <n-modal v-model:show="showAddModal" preset="card" title="添加转发目标" style="width:560px">
      <n-form :model="addForm" label-placement="left" label-width="100">
        <n-form-item label="目标名称">
          <n-input v-model:value="addForm.name" placeholder="如 influxdb-prod" />
        </n-form-item>
        <n-form-item label="目标类型">
          <n-select v-model:value="addForm.type" :options="typeOptions" />
        </n-form-item>
        <template v-if="addForm.type === 'influxdb'">
          <n-form-item label="主机地址">
            <n-input v-model:value="addForm.host" placeholder="localhost" />
          </n-form-item>
          <n-form-item label="端口">
            <n-input-number v-model:value="addForm.port" :min="1" :max="65535" placeholder="8086" style="width:100%" />
          </n-form-item>
          <n-form-item label="数据库">
            <n-input v-model:value="addForm.database" placeholder="protoforge" />
          </n-form-item>
        </template>
        <template v-else-if="addForm.type === 'http'">
          <n-form-item label="目标URL">
            <n-input v-model:value="addForm.url" placeholder="http://example.com/api/data" />
          </n-form-item>
          <n-form-item label="请求头(JSON)">
            <n-input v-model:value="addForm.headers_json" type="textarea" :rows="3" placeholder='{"Authorization": "Bearer xxx"}' />
          </n-form-item>
        </template>
        <template v-else-if="addForm.type === 'file'">
          <n-form-item label="文件路径">
            <n-input v-model:value="addForm.path" placeholder="data/forward_output.log" />
          </n-form-item>
          <n-form-item label="文件格式">
            <n-select v-model:value="addForm.format" :options="[{label: 'JSON Lines', value: 'jsonl'}, {label: 'CSV', value: 'csv'}]" />
          </n-form-item>
        </template>
        <n-form-item label="协议筛选">
          <n-input v-model:value="addForm.protocol" placeholder="留空则转发全部" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddModal = false">取消</n-button>
          <n-button type="primary" @click="addTarget" :loading="adding">添加</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { NSpace, NButton, NAlert, NCard, NDataTable, NModal, NForm, NFormItem,
  NInput, NInputNumber, NSelect, NGrid, NGi, NText, NTag, NEmpty, NPopconfirm, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const dialog = useDialog()

const targets = ref([])
const stats = ref({})
const forwardRunning = ref(false)
const loadingTargets = ref(false)
const starting = ref(false)
const stopping = ref(false)
const showAddModal = ref(false)
const adding = ref(false)

const addForm = ref({
  name: '', type: 'influxdb', host: 'localhost', port: 8086,
  database: 'protoforge', url: '', path: 'data/forward_output.log',
  format: 'jsonl', headers_json: '', protocol: '',
})

const typeOptions = [
  { label: 'InfluxDB', value: 'influxdb' },
  { label: 'HTTP', value: 'http' },
  { label: '文件', value: 'file' },
]

const targetColumns = [
  { title: '名称', key: 'name', width: 160 },
  { title: '类型', key: 'type', width: 100, render: (row) => {
    const labels = { influxdb: 'InfluxDB', http: 'HTTP', file: '文件' }
    return h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => labels[row.type] || row.type)
  }},
  { title: '目标地址', key: 'display_url', width: 260, ellipsis: { tooltip: true } },
  { title: '协议筛选', key: 'protocol', width: 100, render: (row) => row.protocol || '全部' },
  {
    title: '操作', key: 'actions', width: 100,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => removeTarget(row.name) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
      default: () => `确定删除目标 "${row.name}" 吗？`,
    })
  },
]

async function loadTargets() {
  loadingTargets.value = true
  try {
    const res = await api.getForwardTargets()
    targets.value = (res || []).map(t => ({
      ...t,
      display_url: t.url || t.path || (t.host ? `${t.host}:${t.port}` : ''),
    }))
  } catch (e) {
    message.error('加载转发目标失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingTargets.value = false }
}

async function loadStats() {
  try {
    stats.value = await api.getForwardStats()
  } catch (e) { console.warn('加载转发统计失败:', e) }
}

async function addTarget() {
  if (!addForm.value.name) { message.warning('请输入目标名称'); return }
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
        catch { message.warning('请求头JSON格式错误'); return }
      }
    } else if (addForm.value.type === 'file') {
      cfg.path = addForm.value.path
      cfg.format = addForm.value.format
    }
    await api.addForwardTarget(cfg)
    showAddModal.value = false
    addForm.value = { name: '', type: 'influxdb', host: 'localhost', port: 8086, database: 'protoforge', url: '', path: 'data/forward_output.log', format: 'jsonl', headers_json: '', protocol: '' }
    message.success('转发目标已添加')
    await loadTargets()
  } catch (e) {
    message.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally { adding.value = false }
}

async function removeTarget(name) {
  try {
    await api.removeForwardTarget(name)
    message.success('已删除')
    await loadTargets()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function startForward() {
  starting.value = true
  try {
    await api.startForward()
    forwardRunning.value = true
    message.success('转发已启动')
    loadStats()
  } catch (e) {
    message.error('启动失败: ' + (e.response?.data?.detail || e.message))
  } finally { starting.value = false }
}

async function stopForward() {
  stopping.value = true
  try {
    await api.stopForward()
    forwardRunning.value = false
    message.success('转发已停止')
  } catch (e) {
    message.error('停止失败: ' + (e.response?.data?.detail || e.message))
  } finally { stopping.value = false }
}

onMounted(() => {
  loadTargets()
  loadStats()
})
</script>
