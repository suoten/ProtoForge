<template>
  <div style="max-width:1200px;margin:0 auto;">
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <div class="pf-section-title">设备管理</div>
          <div class="pf-section-desc">管理所有仿真设备，支持快速创建和高级配置</div>
        </div>
        <n-space>
          <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width:160px" />
          <n-button type="primary" @click="openQuickCreate">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
            快速创建
          </n-button>
          <n-button tertiary @click="showCreateModal = true">高级创建</n-button>
        </n-space>
      </n-space>

      <n-alert v-if="noProtocolRunning" type="warning" :bordered="false">
        <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01"/></svg></template>
        没有协议服务在运行，设备将无法正常工作。
        <n-button size="tiny" type="primary" @click="goProtocols" style="margin-left:8px">前往启动协议</n-button>
      </n-alert>

      <n-data-table :columns="columns" :data="filteredDevices" :bordered="false"
        :pagination="{ pageSize: 15 }" :row-key="row => row.id" />

      <n-modal v-model:show="showQuickCreateModal" preset="card" title="快速创建设备" style="width:500px">
        <n-steps :current="quickStep" size="small" style="margin-bottom:16px">
          <n-step title="选模板" />
          <n-step title="起名字" />
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
        <n-space v-if="quickStep === 3" vertical align="center" style="padding:20px 0">
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
              <n-button v-if="quickStep < 3" type="primary" @click="quickStep++" :disabled="quickStep === 1 && !qcTemplateId || quickStep === 2 && !qcDeviceName">下一步</n-button>
              <n-button v-if="quickStep === 3" type="primary" @click="doQuickCreate" :loading="qcLoading">创建并启动</n-button>
            </n-space>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showCreateModal" preset="card" title="高级创建设备" style="width:600px">
        <n-form :model="newDevice" label-placement="left" label-width="80">
          <n-form-item label="设备ID"><n-input v-model:value="newDevice.id" placeholder="如: sensor-001" /></n-form-item>
          <n-form-item label="设备名称"><n-input v-model:value="newDevice.name" placeholder="如: 温湿度传感器-1" /></n-form-item>
          <n-form-item label="协议"><n-select v-model:value="newDevice.protocol" :options="protocolOptions.filter(o => o.value)" /></n-form-item>
          <n-form-item label="从模板创建"><n-select v-model:value="selectedTemplate" :options="templateOptions" placeholder="选择模板" clearable /></n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showCreateModal = false">取消</n-button>
            <n-button type="primary" @click="createDevice" :loading="creating">创建</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showEditModal" preset="card" title="编辑设备" style="width:600px">
        <n-form :model="editDevice" label-placement="left" label-width="80">
          <n-form-item label="设备名称"><n-input v-model:value="editDevice.name" /></n-form-item>
          <n-form-item label="协议"><n-input :value="editDevice.protocol" disabled /></n-form-item>
        </n-form>
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

      <!-- 故障注入 Modal -->
      <n-modal v-model:show="showFaultModal" preset="card" title="故障注入" style="width:560px">
        <n-space vertical size="medium">
          <n-text depth="3" style="font-size:13px">目标设备：<n-text strong>{{ faultTargetDevice?.name }}</n-text></n-text>

          <n-form-item label="故障类型" label-placement="left" label-width="80">
            <n-select
              v-model:value="faultTypeId"
              :options="faultTypeGroupedOptions"
              placeholder="选择故障类型"
              @update:value="onFaultTypeChange"
            />
          </n-form-item>

          <!-- 场景说明卡片 -->
          <div v-if="selectedFaultType" style="background:#1a1a2e;border:1px solid #2d2d4e;border-radius:8px;padding:14px 16px;">
            <!-- 标题行：故障名 + 场景类型标签 + 分类标签 -->
            <n-space align="center" style="margin-bottom:10px;flex-wrap:wrap;gap:6px">
              <n-text strong style="font-size:14px">{{ selectedFaultType.name }}</n-text>
              <n-tag :type="scenarioTagType(selectedFaultType.scenario_type)" size="small" round>
                {{ scenarioTypeLabel(selectedFaultType.scenario_type) }}
              </n-tag>
              <n-tag size="small" :bordered="false" style="background:#2d2d4e;color:#94a3b8">
                {{ faultCategoryLabel(selectedFaultType.category) }}
              </n-tag>
            </n-space>

            <!-- 描述文本 -->
            <n-text depth="3" style="font-size:12px;line-height:1.7;display:block;white-space:pre-wrap">{{ selectedFaultType.description }}</n-text>

            <!-- 影响测点 -->
            <div style="margin-top:10px;padding-top:10px;border-top:1px solid #2d2d4e">
              <n-text depth="3" style="font-size:11px">影响测点：</n-text>
              <n-space size="small" style="margin-top:4px;flex-wrap:wrap">
                <n-tag
                  v-for="pf in selectedFaultType.point_faults"
                  :key="pf.point"
                  size="tiny"
                  :bordered="false"
                  style="background:#2d2d4e;color:#e2e8f0;font-family:monospace"
                >
                  {{ pf.point }}
                  <span style="color:#94a3b8;margin-left:4px">
                    {{ pointFaultModeLabel(pf) }}
                  </span>
                </n-tag>
              </n-space>
            </div>
          </div>

          <n-form-item label="持续时间" label-placement="left" label-width="80">
            <n-input-number
              v-model:value="faultDuration"
              :min="5"
              :max="3600"
              style="width:100%"
            >
              <template #suffix>秒</template>
            </n-input-number>
          </n-form-item>

          <n-form-item label="故障强度" label-placement="left" label-width="80">
            <n-space vertical style="width:100%">
              <n-slider v-model:value="faultIntensity" :min="0.1" :max="1.0" :step="0.1" />
              <n-text depth="3" style="font-size:12px">
                {{ faultIntensityLabel }}（{{ faultIntensity }}）
                <span v-if="selectedFaultType?.scenario_type === 'mode_switch'" style="color:#f59e0b">
                  · 工况切换型强度不影响切换幅度
                </span>
              </n-text>
            </n-space>
          </n-form-item>
        </n-space>
        <template #action>
          <n-space justify="end">
            <n-button @click="showFaultModal = false">取消</n-button>
            <n-button type="error" :loading="faultLoading" :disabled="!faultTypeId" @click="doInjectFault">
              注入故障
            </n-button>
          </n-space>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { NSpace, NSelect, NButton, NDataTable, NModal, NForm, NFormItem, NInput, NTag,
  NSteps, NStep, NText, NAlert, NInputNumber, NSlider, useMessage, useDialog } from 'naive-ui'
import { useRouter } from 'vue-router'
import api from '../api.js'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const devices = ref([])
const protocols = ref([])
const templates = ref([])
const filterProtocol = ref(null)
const showCreateModal = ref(false)
const showQuickCreateModal = ref(false)
const showEditModal = ref(false)
const showPointsModal = ref(false)
const creating = ref(false)
const saving = ref(false)
const currentPoints = ref([])
const selectedTemplate = ref(null)
const editDevice = ref({ id: '', name: '', protocol: '' })
const newDevice = ref({ id: '', name: '', protocol: 'modbus_tcp', points: [] })
const quickStep = ref(1)
const qcTemplateId = ref(null)
const qcDeviceName = ref('')
const qcLoading = ref(false)

// 故障注入状态
const showFaultModal = ref(false)
const faultTargetDevice = ref(null)
const faultTypes = ref([])
const faultTypeId = ref(null)
const faultDuration = ref(120)
const faultIntensity = ref(1.0)
const faultLoading = ref(false)
// device_id -> fault info，用于在列表中显示故障状态
const activeFaults = ref({})

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

const columns = [
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
    title: '故障', key: 'fault', width: 130,
    render: (row) => {
      const fault = activeFaults.value[row.id]
      if (!fault || fault.status === 'none') return h(NTag, { size: 'tiny', bordered: false }, () => '正常')
      const pct = Math.round((fault.progress || 0) * 100)
      const ft = faultTypes.value.find(t => t.id === fault.fault_type_id)
      const scenarioLabel = ft ? scenarioTypeLabel(ft.scenario_type) : ''
      return h(NSpace, { size: 2, vertical: false, align: 'center' }, () => [
        h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => `${fault.fault_type_name} ${pct}%`),
        scenarioLabel ? h(NTag, { size: 'tiny', bordered: false, style: 'font-size:10px;background:#2d1b1b;color:#f87171' }, () => scenarioLabel) : null,
      ])
    }
  },
  {
    title: '操作', key: 'actions', width: 320,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewPoints(row.id) }, () => '测点'),
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => openEditDevice(row) }, () => '编辑'),
      row.status === 'online' || row.status === 'running'
        ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => toggleDevice(row.id, 'stop') }, () => '停止')
        : h(NButton, { size: 'tiny', type: 'primary', secondary: true, onClick: () => toggleDevice(row.id, 'start') }, () => '启动'),
      activeFaults.value[row.id] && activeFaults.value[row.id].status !== 'none'
        ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => stopFault(row.id) }, () => '停止故障')
        : h(NButton, { size: 'tiny', type: 'error', ghost: true, disabled: row.status !== 'online', onClick: () => openFaultModal(row) }, () => '注入故障'),
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
  showQuickCreateModal.value = true
}

async function doQuickCreate() {
  qcLoading.value = true
  try {
    await api.quickCreateDevice(qcTemplateId.value, qcDeviceName.value)
    message.success(`设备 "${qcDeviceName.value}" 创建成功并已启动！`)
    showQuickCreateModal.value = false
    await loadData()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally { qcLoading.value = false }
}

async function createDevice() {
  creating.value = true
  try {
    let config = { ...newDevice.value, points: [] }
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

function openEditDevice(row) {
  editDevice.value = { id: row.id, name: row.name, protocol: row.protocol }
  showEditModal.value = true
}

async function saveEditDevice() {
  saving.value = true
  try {
    await api.updateDevice(editDevice.value.id, { id: editDevice.value.id, name: editDevice.value.name, protocol: editDevice.value.protocol, points: [] })
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

// 故障注入相关
const faultTypeOptions = computed(() =>
  faultTypes.value.map(t => ({ label: `${t.name}（${faultCategoryLabel(t.category)}）`, value: t.id }))
)

// 按场景类型分组的故障选项
const SCENARIO_ORDER = ['trend_drift', 'sudden_spike', 'high_noise', 'mode_switch', 'relation_constraint']
const faultTypeGroupedOptions = computed(() => {
  const groups = {}
  for (const t of faultTypes.value) {
    const st = t.scenario_type || 'trend_drift'
    if (!groups[st]) groups[st] = []
    groups[st].push({ label: t.name, value: t.id })
  }
  return SCENARIO_ORDER
    .filter(st => groups[st])
    .map(st => ({
      type: 'group',
      label: scenarioTypeLabel(st),
      key: st,
      children: groups[st],
    }))
})

const selectedFaultType = computed(() =>
  faultTypes.value.find(t => t.id === faultTypeId.value) || null
)

const faultIntensityLabel = computed(() => {
  const v = faultIntensity.value
  if (v <= 0.3) return '轻微'
  if (v <= 0.6) return '中等'
  if (v <= 0.8) return '严重'
  return '极严重'
})

function faultCategoryLabel(category) {
  const map = { mechanical: '机械', thermal: '热', electrical: '电气', process: '工艺' }
  return map[category] || category
}

function scenarioTypeLabel(scenarioType) {
  const map = {
    trend_drift: '趋势漂移型',
    sudden_spike: '突发脉冲型',
    high_noise: '高噪声波动型',
    mode_switch: '工况切换型',
    relation_constraint: '关系约束型',
  }
  return map[scenarioType] || scenarioType
}

function scenarioTagType(scenarioType) {
  const map = {
    trend_drift: 'warning',
    sudden_spike: 'error',
    high_noise: 'info',
    mode_switch: 'success',
    relation_constraint: 'default',
  }
  return map[scenarioType] || 'default'
}

function pointFaultModeLabel(pf) {
  if (pf.mode === 'step') return '→ 阶跃'
  if (pf.mode === 'gradual') {
    if (pf.multiplier != null) return `→ ×${pf.multiplier}`
    if (pf.target_value != null) return `→ ${pf.target_value}`
  }
  if (pf.mode === 'instant') {
    if (pf.target_value != null) return `→ ${pf.target_value}`
    if (pf.multiplier != null && pf.multiplier !== 1.0) return `→ ×${pf.multiplier}`
    return '± 噪声'
  }
  return ''
}

function onFaultTypeChange(val) {
  const t = faultTypes.value.find(f => f.id === val)
  if (t && t.default_duration) faultDuration.value = t.default_duration
}

function openFaultModal(row) {
  faultTargetDevice.value = row
  faultTypeId.value = null
  faultDuration.value = 120
  faultIntensity.value = 1.0
  showFaultModal.value = true
}

async function doInjectFault() {
  if (!faultTypeId.value || !faultTargetDevice.value) return
  faultLoading.value = true
  try {
    await api.injectFault(faultTargetDevice.value.id, faultTypeId.value, faultDuration.value, faultIntensity.value)
    message.success(`已向设备 "${faultTargetDevice.value.name}" 注入故障`)
    showFaultModal.value = false
    await loadFaultStatus()
  } catch (e) {
    message.error('注入失败: ' + (e.response?.data?.detail || e.message))
  } finally { faultLoading.value = false }
}

async function stopFault(deviceId) {
  try {
    await api.clearDeviceFault(deviceId)
    message.success('故障已停止')
    await loadFaultStatus()
  } catch (e) {
    message.error('停止故障失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadFaultStatus() {
  try {
    const list = await api.getActiveFaults()
    const map = {}
    for (const f of list) map[f.device_id] = f
    activeFaults.value = map
  } catch (e) { /* 静默失败 */ }
}

async function loadData() {
  try {
    const [devRes, protoRes, tmplRes, ftRes] = await Promise.all([
      api.getDevices(), api.getProtocols(), api.getTemplates(), api.getFaultTypes()
    ])
    devices.value = devRes; protocols.value = protoRes; templates.value = tmplRes; faultTypes.value = ftRes
    await loadFaultStatus()
  } catch (e) { message.error('加载数据失败: ' + (e.response?.data?.detail || e.message)) }
}

let faultPollTimer = null
onMounted(() => {
  loadData()
  faultPollTimer = setInterval(loadFaultStatus, 3000)
})

onUnmounted(() => { if (faultPollTimer) clearInterval(faultPollTimer) })
</script>
