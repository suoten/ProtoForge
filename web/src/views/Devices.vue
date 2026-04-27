<template>
  <div>
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <div class="pf-section-title">设备管理</div>
          <div class="pf-section-desc">管理所有仿真设备，支持快速创建和高级配置</div>
        </div>
        <n-space>
          <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width:160px" />
          <n-button v-if="selectedIds.length > 0" type="primary" @click="batchStart" :loading="batchLoading">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
            启动选中({{ selectedIds.length }})
          </n-button>
          <n-button v-if="selectedIds.length > 0" type="warning" @click="batchStop" :loading="batchLoading">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
            停止选中({{ selectedIds.length }})
          </n-button>
          <n-button @click="startAllDevices" :loading="batchLoading">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
            全部启动
          </n-button>
          <n-button @click="stopAllDevices" :loading="batchLoading">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
            全部停止
          </n-button>
          <n-button type="primary" @click="openQuickCreate">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
            快速创建
          </n-button>
          <n-button tertiary @click="openAdvancedCreate">高级创建</n-button>
        </n-space>
      </n-space>

      <n-alert v-if="noProtocolRunning" type="warning" :bordered="false">
        <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01"/></svg></template>
        没有协议服务在运行，设备将无法正常工作。
        <n-button size="tiny" type="primary" @click="goProtocols" style="margin-left:8px">前往启动协议</n-button>
      </n-alert>

      <n-data-table :columns="columns" :data="filteredDevices" :bordered="false"
        :pagination="{ pageSize: 15 }" :row-key="row => row.id"
        v-model:checked-row-keys="selectedIds" :single-line="false" />

      <n-modal v-model:show="showQuickCreateModal" preset="card" title="快速创建设备" style="width:560px">
        <n-steps :current="quickStep" size="small" style="margin-bottom:16px">
          <n-step title="选模板" />
          <n-step title="起名字" />
          <n-step title="协议配置" />
          <n-step title="完成" />
        </n-steps>
        <n-space v-if="quickStep === 1" vertical>
          <n-text>选择设备模板：</n-text>
          <n-select v-model:value="qcTemplateId" :options="quickTemplateOptions" placeholder="搜索模板..." filterable />
        </n-space>
        <n-space v-if="quickStep === 2" vertical>
          <n-text>给设备起个名字：</n-text>
          <n-input v-model:value="qcDeviceName" placeholder="如：车间温湿度传感器" size="large" />
          <n-text v-if="qcTemplateId" depth="3" style="font-size:12px">协议: {{ qcTemplateName }} | 测点: {{ qcTemplatePoints }}个</n-text>
        </n-space>
        <div v-if="quickStep === 3">
          <div v-if="qcDeviceConfigFields.length === 0" style="text-align:center;padding:20px 0;color:#94a3b8">
            该协议无需额外配置，直接下一步即可
          </div>
          <n-form v-else :model="qcProtocolConfig" label-placement="left" label-width="140">
            <n-form-item v-for="f in qcDeviceConfigFields" :key="f.key" :label="f.label">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="qcProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="qcProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="qcProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
              <n-text v-if="f.description" depth="3" style="margin-left:8px;font-size:12px">{{ f.description }}</n-text>
            </n-form-item>
          </n-form>
        </div>
        <n-space v-if="quickStep === 4" vertical align="center" style="padding:20px 0">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <n-text>准备创建设备：</n-text>
          <n-text strong>{{ qcDeviceName }}</n-text>
          <n-text depth="3">模板: {{ qcTemplateName }}</n-text>
        </n-space>
        <template #action>
          <n-space justify="space-between" style="width:100%">
            <n-button v-if="quickStep > 1" @click="quickStep--">上一步</n-button>
            <div v-else></div>
            <n-space>
              <n-button @click="showQuickCreateModal = false">取消</n-button>
              <n-button v-if="quickStep < 4" type="primary" @click="quickStepNext" :disabled="quickStep === 1 && !qcTemplateId || quickStep === 2 && !qcDeviceName">下一步</n-button>
              <n-button v-if="quickStep === 4" type="primary" @click="doQuickCreate" :loading="qcLoading">创建并启动</n-button>
            </n-space>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showCreateModal" preset="card" title="高级创建设备" style="width:640px">
        <n-form :model="newDevice" label-placement="left" label-width="80">
          <n-form-item label="设备ID"><n-input v-model:value="newDevice.id" placeholder="如: sensor-001" /></n-form-item>
          <n-form-item label="设备名称"><n-input v-model:value="newDevice.name" placeholder="如: 温湿度传感器-1" /></n-form-item>
          <n-form-item label="协议"><n-select v-model:value="newDevice.protocol" :options="protocolOptions.filter(o => o.value)" @update:value="onAdvancedProtocolChange" /></n-form-item>
          <n-form-item label="从模板创建"><n-select v-model:value="selectedTemplate" :options="templateOptions" placeholder="选择模板" clearable /></n-form-item>
        </n-form>
        <div v-if="advancedConfigFields.length > 0" style="margin-top:8px">
          <div style="font-weight:600;margin-bottom:8px;font-size:14px">协议配置</div>
          <n-form :model="advancedProtocolConfig" label-placement="left" label-width="140">
            <n-form-item v-for="f in advancedConfigFields" :key="f.key" :label="f.label">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="advancedProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="advancedProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="advancedProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
            </n-form-item>
          </n-form>
        </div>
        <template #action>
          <n-space>
            <n-button @click="showCreateModal = false">取消</n-button>
            <n-button type="primary" @click="createDevice" :loading="creating">创建</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showEditModal" preset="card" title="编辑设备" style="width:640px">
        <n-form :model="editDevice" label-placement="left" label-width="80">
          <n-form-item label="设备名称"><n-input v-model:value="editDevice.name" /></n-form-item>
          <n-form-item label="协议"><n-input :value="editDevice.protocol" disabled /></n-form-item>
        </n-form>
        <div v-if="editConfigFields.length > 0" style="margin-top:8px">
          <div style="font-weight:600;margin-bottom:8px;font-size:14px">协议配置</div>
          <n-form :model="editProtocolConfig" label-placement="left" label-width="140">
            <n-form-item v-for="f in editConfigFields" :key="f.key" :label="f.label">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="editProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="editProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="editProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
            </n-form-item>
          </n-form>
        </div>
        <template #action>
          <n-space>
            <n-button @click="showEditModal = false">取消</n-button>
            <n-button type="primary" @click="saveEditDevice" :loading="saving">保存</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showPointsModal" preset="card" title="设备测点" style="width:700px">
        <n-data-table :columns="pointColumns" :data="currentPoints" :bordered="false" size="small" />
      </n-modal>

      <n-modal v-model:show="showGuideModal" preset="card" title="连接指南" style="width:680px">
        <div v-if="guideData">
          <n-space vertical size="large">
            <n-alert :type="guideData.mode === 'client' ? 'warning' : 'info'" :bordered="false">
              <template #icon>
                <svg v-if="guideData.mode === 'server'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/></svg>
                <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4 M10 17l5-5-5-5 M15 12H3"/></svg>
              </template>
              <div style="font-weight:600;margin-bottom:4px">{{ guideData.mode_label }}</div>
              <div>{{ guideData.mode_desc }}</div>
            </n-alert>

            <div v-if="guideData.mode === 'server'">
              <div style="font-weight:600;margin-bottom:8px">📋 {{ guideData.connect_hint }}</div>
              <n-card size="small" embedded>
                <div v-for="(val, key) in guideData.connection_info" :key="key" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                  <n-text depth="3">{{ key }}</n-text>
                  <n-text code>{{ val }}</n-text>
                </div>
              </n-card>
            </div>

            <div v-if="guideData.mode === 'client'">
              <div style="font-weight:600;margin-bottom:8px">📋 {{ guideData.connect_hint }}</div>
              <n-card size="small" embedded>
                <div v-for="(val, key) in guideData.connection_info" :key="key" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                  <n-text depth="3">{{ key }}</n-text>
                  <n-text code>{{ val }}</n-text>
                </div>
              </n-card>
            </div>

            <div v-if="guideData.code_example">
              <div style="font-weight:600;margin-bottom:8px">💻 代码示例</div>
              <n-card size="small" embedded>
                <pre style="margin:0;white-space:pre-wrap;font-size:13px;line-height:1.6;font-family:Consolas,Monaco,monospace">{{ guideData.code_example }}</pre>
              </n-card>
            </div>
          </n-space>
        </div>
        <template #action>
          <n-button @click="showGuideModal = false">关闭</n-button>
          <n-button type="primary" @click="copyGuide">复制代码</n-button>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h, watch } from 'vue'
import { NSpace, NSelect, NButton, NDataTable, NModal, NForm, NFormItem, NInput, NInputNumber, NTag,
  NSteps, NStep, NText, NAlert, useMessage, useDialog } from 'naive-ui'
import { useRouter } from 'vue-router'
import api from '../api.js'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const devices = ref([])
const selectedIds = ref([])
const batchLoading = ref(false)
const protocols = ref([])
const templates = ref([])
const filterProtocol = ref(null)
const showCreateModal = ref(false)
const showQuickCreateModal = ref(false)
const showEditModal = ref(false)
const showPointsModal = ref(false)
const showGuideModal = ref(false)
const guideData = ref(null)
const creating = ref(false)
const saving = ref(false)
const currentPoints = ref([])
const selectedTemplate = ref(null)
const editDevice = ref({ id: '', name: '', protocol: '', protocol_config: {} })
const editProtocolConfig = ref({})
const editConfigFields = ref([])
const newDevice = ref({ id: '', name: '', protocol: 'modbus_tcp', points: [] })
const advancedProtocolConfig = ref({})
const advancedConfigFields = ref([])
const quickStep = ref(1)
const qcTemplateId = ref(null)
const qcDeviceName = ref('')
const qcLoading = ref(false)
const qcProtocolConfig = ref({})
const qcDeviceConfigFields = ref([])
const qcProtocol = ref('')

const protocolLabels = {
  modbus_tcp: 'Modbus TCP', modbus_rtu: 'Modbus RTU', opcua: 'OPC-UA', mqtt: 'MQTT',
  http: 'HTTP', gb28181: 'GB28181', bacnet: 'BACnet', s7: 'S7',
  mc: 'Mitsubishi MC', fins: 'Omron FINS', ab: 'Rockwell AB', opcda: 'OPC-DA',
  fanuc: 'FANUC FOCAS', mtconnect: 'MTConnect', toledo: 'Mettler-Toledo',
}

const protocolOptions = computed(() => [
  { label: '全部', value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const templateOptions = computed(() =>
  templates.value.map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
)

const quickTemplateOptions = computed(() => {
  const popular = ['modbus_temperature_sensor', 'siemens_s7_1200', 'smart_lock', 'flow_meter',
    'mc_fx5u', 'fanuc_0if_plus', 'ab_controllogix', 'fins_cp1h',
    'toledo_scale', 'opcda_scada_server', 'mtconnect_mill', 'ptz_camera', 'hvac_controller']
  const popularSet = new Set(popular)
  const popularItems = templates.value
    .filter(t => popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  const otherItems = templates.value
    .filter(t => !popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  return [...popularItems, ...otherItems]
})

const qcTemplateName = computed(() => {
  const t = templates.value.find(t => t.id === qcTemplateId.value)
  return t ? t.name : ''
})

const qcTemplatePoints = computed(() => {
  const t = templates.value.find(t => t.id === qcTemplateId.value)
  return t ? (t.points?.length || t.point_count || 0) : 0
})

const filteredDevices = computed(() => {
  if (!filterProtocol.value) return devices.value
  return devices.value.filter(d => d.protocol === filterProtocol.value)
})

const noProtocolRunning = computed(() => protocols.value.length > 0 && protocols.value.every(p => p.status !== 'running'))

function goProtocols() { router.push('/protocols') }

async function loadDeviceConfig(protocol) {
  if (!protocol) return { fields: [], defaults: {} }
  try {
    const res = await api.getProtocolDeviceConfig(protocol)
    const defaults = {}
    res.fields.forEach(f => { defaults[f.key] = f.default })
    return { fields: res.fields, defaults }
  } catch (e) { return { fields: [], defaults: {} } }
}

const columns = [
  { type: 'selection' },
  { title: '设备', key: 'name', width: 160, render: (row) => h('div', {}, [
    h('div', { style: 'font-weight:500' }, row.name || row.id),
    h('div', { style: 'font-size:11px;color:#94a3b8' }, row.id),
  ]) },
  { title: '协议', key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => protocolLabels[row.protocol] || row.protocol) },
  {
    title: '状态', key: 'status', width: 100,
    render: (row) => h(NTag, { type: row.status === 'online' ? 'success' : row.status === 'error' ? 'error' : 'default', size: 'small', bordered: false }, () => row.status === 'online' ? '在线' : row.status === 'error' ? '错误' : '离线')
  },
  { title: '测点', key: 'points', width: 70, render: (row) => (row.points || []).length },
  {
    title: '操作', key: 'actions', width: 280,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewPoints(row.id) }, () => '测点'),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => showGuide(row.id) }, () => '指南'),
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => openEditDevice(row) }, () => '编辑'),
      row.status === 'online' || row.status === 'running'
        ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => toggleDevice(row.id, 'stop') }, () => '停止')
        : h(NButton, { size: 'tiny', type: 'primary', secondary: true, onClick: () => toggleDevice(row.id, 'start') }, () => '启动'),
      h(NButton, { size: 'tiny', type: 'error', secondary: true, onClick: () => confirmDeleteDevice(row) }, () => '删除'),
    ])
  },
]

const pointColumns = [
  { title: '名称', key: 'name', width: 120 },
  { title: '值', key: 'value', width: 120 },
  { title: '时间', key: 'timestamp', width: 180, render: (row) => row.timestamp ? new Date(row.timestamp * 1000).toLocaleString() : '-' },
  { title: '质量', key: 'quality', width: 80 },
]

function openQuickCreate() {
  quickStep.value = 1; qcTemplateId.value = null; qcDeviceName.value = ''
  qcProtocolConfig.value = {}; qcDeviceConfigFields.value = []; qcProtocol.value = ''
  showQuickCreateModal.value = true
}

async function quickStepNext() {
  if (quickStep.value === 2 && qcTemplateId.value) {
    const t = templates.value.find(t => t.id === qcTemplateId.value)
    if (t && t.protocol && t.protocol !== qcProtocol.value) {
      qcProtocol.value = t.protocol
      const { fields, defaults } = await loadDeviceConfig(t.protocol)
      qcDeviceConfigFields.value = fields
      qcProtocolConfig.value = defaults
    }
  }
  quickStep.value++
}

async function doQuickCreate() {
  qcLoading.value = true
  try {
    await api.quickCreateDevice(qcTemplateId.value, qcDeviceName.value, null, qcProtocolConfig.value)
    message.success(`设备 "${qcDeviceName.value}" 创建成功并已启动！`)
    showQuickCreateModal.value = false
    await loadData()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally { qcLoading.value = false }
}

function openAdvancedCreate() {
  newDevice.value = { id: '', name: '', protocol: 'modbus_tcp', points: [] }
  advancedProtocolConfig.value = {}; advancedConfigFields.value = []
  selectedTemplate.value = null
  showCreateModal.value = true
}

async function onAdvancedProtocolChange(protocol) {
  const { fields, defaults } = await loadDeviceConfig(protocol)
  advancedConfigFields.value = fields
  advancedProtocolConfig.value = defaults
}

async function loadData() {
  try {
    const [devRes, protoRes, tmplRes] = await Promise.all([api.getDevices(), api.getProtocols(), api.getTemplates()])
    devices.value = devRes; protocols.value = protoRes; templates.value = tmplRes
  } catch (e) { message.error('加载数据失败: ' + (e.response?.data?.detail || e.message)) }
}

async function batchStart() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const id of selectedIds.value) {
    try { await api.startDevice(id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  selectedIds.value = []
  message.success(`已启动 ${ok} 个设备` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function batchStop() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const id of selectedIds.value) {
    try { await api.stopDevice(id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  selectedIds.value = []
  message.success(`已停止 ${ok} 个设备` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function startAllDevices() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const dev of filteredDevices.value) {
    try { await api.startDevice(dev.id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  message.success(`已启动 ${ok} 个设备` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function stopAllDevices() {
  batchLoading.value = true
  let ok = 0, fail = 0
  for (const dev of filteredDevices.value) {
    try { await api.stopDevice(dev.id); ok++ } catch { fail++ }
  }
  batchLoading.value = false
  message.success(`已停止 ${ok} 个设备` + (fail ? `，${fail} 个失败` : ''))
  loadData()
}

async function createDevice() {
  creating.value = true
  try {
    let config = { ...newDevice.value, points: [], protocol_config: advancedProtocolConfig.value }
    if (selectedTemplate.value) {
      const tmplRes = await api.getTemplate(selectedTemplate.value)
      config.points = tmplRes.points; config.protocol = tmplRes.protocol
    }
    if (!config.points.length) config.points = [{ name: 'value', address: '0', data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 }]
    await api.createDevice(config)
    showCreateModal.value = false
    newDevice.value = { id: '', name: '', protocol: 'modbus_tcp', points: [] }
    selectedTemplate.value = null
    message.success('设备创建成功')
    await loadData()
  } catch (e) { message.error('创建失败: ' + (e.response?.data?.detail || e.message)) }
  finally { creating.value = false }
}

async function openEditDevice(row) {
  editDevice.value = { id: row.id, name: row.name, protocol: row.protocol, protocol_config: row.protocol_config || {} }
  const { fields, defaults } = await loadDeviceConfig(row.protocol)
  editConfigFields.value = fields
  editProtocolConfig.value = { ...defaults, ...(row.protocol_config || {}) }
  showEditModal.value = true
}

async function saveEditDevice() {
  saving.value = true
  try {
    await api.updateDevice(editDevice.value.id, {
      id: editDevice.value.id, name: editDevice.value.name,
      protocol: editDevice.value.protocol, points: [],
      protocol_config: editProtocolConfig.value,
    })
    showEditModal.value = false; message.success('设备更新成功'); await loadData()
  } catch (e) { message.error('更新失败: ' + (e.response?.data?.detail || e.message)) }
  finally { saving.value = false }
}

async function toggleDevice(id, action) {
  try {
    if (action === 'start') { await api.startDevice(id); message.success('设备已启动') }
    else { await api.stopDevice(id); message.success('设备已停止') }
    await loadData()
  } catch (e) { message.error((action === 'start' ? '启动' : '停止') + '失败: ' + (e.response?.data?.detail || e.message)) }
}

function confirmDeleteDevice(row) {
  dialog.warning({ title: '确认删除', content: `确定要删除设备 "${row.name}" (${row.id}) 吗？`, positiveText: '删除', negativeText: '取消', onPositiveClick: () => deleteDevice(row.id) })
}

async function deleteDevice(id) {
  try { await api.deleteDevice(id); message.success('设备已删除'); await loadData() }
  catch (e) { message.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function viewPoints(id) {
  try { const res = await api.getDevicePoints(id); currentPoints.value = res; showPointsModal.value = true }
  catch (e) { message.error('读取测点失败: ' + (e.response?.data?.detail || e.message)) }
}

async function showGuide(id) {
  try {
    guideData.value = await api.getDeviceConnectionGuide(id)
    showGuideModal.value = true
  } catch (e) { message.error('获取连接指南失败: ' + (e.response?.data?.detail || e.message)) }
}

function copyGuide() {
  if (!guideData.value?.code_example) return
  navigator.clipboard.writeText(guideData.value.code_example)
  message.success('代码已复制到剪贴板')
}

onMounted(loadData)
</script>
