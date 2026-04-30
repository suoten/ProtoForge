<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">场景编排器</div>
        <div class="pf-section-desc">可视化编排设备与联动规则</div>
      </div>
      <n-space>
        <n-select v-model:value="selectedScenario" :options="scenarioOptions" placeholder="选择场景" style="width: 200px" @update:value="loadScenario" />
        <n-button type="primary" @click="saveScenarioLayout" :loading="saving">保存布局</n-button>
        <n-button @click="addDeviceNode">添加设备</n-button>
        <n-button type="success" @click="startScenario" v-if="selectedScenario">启动场景</n-button>
        <n-button type="warning" @click="stopScenario" v-if="selectedScenario">停止场景</n-button>
      </n-space>
    </n-space>

    <div style="height: 600px; border: 1px solid #e0e0e0; border-radius: 4px;">
      <VueFlow v-model:nodes="nodes" v-model:edges="edges" :default-viewport="{ zoom: 0.8 }"
        :min-zoom="0.3" :max-zoom="2" fit-view-on-init @connect="onConnect"
        @node-double-click="onNodeDoubleClick">
        <Background :gap="20" />
        <Controls />
        <MiniMap />

        <template #node-device="deviceNodeProps">
          <DeviceNode :data="deviceNodeProps.data" />
        </template>

        <template #edge-rule="ruleEdgeProps">
          <RuleEdge v-bind="ruleEdgeProps" />
        </template>
      </VueFlow>
    </div>

    <n-modal v-model:show="showAddDeviceModal" preset="card" title="添加设备节点" style="width: 500px">
      <n-form :model="newNode" label-placement="left" label-width="80">
        <n-form-item label="设备ID">
          <n-input v-model:value="newNode.deviceId" placeholder="如: sensor-001" />
        </n-form-item>
        <n-form-item label="设备名称">
          <n-input v-model:value="newNode.deviceName" placeholder="如: 温湿度传感器" />
        </n-form-item>
        <n-form-item label="协议">
          <n-select v-model:value="newNode.protocol" :options="protocolTypeOptions" />
        </n-form-item>
        <n-form-item label="从模板">
          <n-select v-model:value="newNode.templateId" :options="templateOptions" clearable placeholder="可选" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddDeviceModal = false">取消</n-button>
          <n-button type="primary" @click="confirmAddNode">添加</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showRuleModal" preset="card" title="配置联动规则" style="width: 500px">
      <n-form :model="newRule" label-placement="left" label-width="80">
        <n-form-item label="规则名称">
          <n-input v-model:value="newRule.name" />
        </n-form-item>
        <n-form-item label="规则类型">
          <n-select v-model:value="newRule.ruleType" :options="ruleTypeOptions" />
        </n-form-item>
        <n-form-item label="源测点">
          <n-input v-model:value="newRule.sourcePoint" placeholder="如: temperature" />
        </n-form-item>
        <n-form-item label="条件">
          <n-select v-model:value="newRule.operator" :options="operatorOptions" style="width: 140px" />
          <n-input-number v-model:value="newRule.threshold" style="width: 150px" />
        </n-form-item>
        <n-form-item label="目标测点">
          <n-input v-model:value="newRule.targetPoint" placeholder="如: alarm" />
        </n-form-item>
        <n-form-item label="目标值">
          <n-input v-model:value="newRule.targetValue" placeholder="如: true 或 1" />
        </n-form-item>
        <n-form-item label="冷却(秒)">
          <n-input-number v-model:value="newRule.cooldown" :min="0" style="width: 120px" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showRuleModal = false">取消</n-button>
          <n-button type="primary" @click="confirmRule">确认</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showPointsModal" preset="card" :title="`测点编辑 - ${editingDevice.label || ''}`" style="width: 700px">
      <n-space vertical>
        <n-button size="small" type="primary" @click="addPoint">添加测点</n-button>
        <n-data-table :columns="pointEditColumns" :data="editingPoints" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showPointsModal = false">取消</n-button>
          <n-button type="primary" @click="savePoints">保存测点</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h, defineComponent } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import {
  NSpace, NButton, NSelect, NModal, NForm, NFormItem, NInput, NInputNumber,
  NTag, NCard, NDataTable, useMessage
} from 'naive-ui'
import { useRoute } from 'vue-router'
import api from '../api.js'
import { protocolColors } from '../constants.js'

const message = useMessage()
const route = useRoute()

const DeviceNode = defineComponent({
  props: { data: Object },
  setup(props) {
    return () => h('div', {
      style: {
        padding: '12px 16px', borderRadius: '8px', background: '#fff',
        border: `2px solid ${protocolColors[props.data?.protocol] || '#d9d9d9'}`,
        minWidth: '160px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)', position: 'relative'
      }
    }, [
      h('div', { style: { fontWeight: 'bold', marginBottom: '4px', fontSize: '14px' } }, props.data?.label || 'Device'),
      h('div', { style: { fontSize: '12px', color: '#888' } }, props.data?.deviceId || ''),
      h(NTag, { size: 'tiny', type: 'info', style: { marginTop: '4px' } }, () => props.data?.protocol || ''),
      h('div', {
        style: { width: '8px', height: '8px', borderRadius: '50%', background: props.data?.online ? '#52c41a' : '#ff4d4f',
          position: 'absolute', top: '8px', right: '8px' }
      }),
      h('div', { style: { fontSize: '10px', color: '#999', marginTop: '4px' } },
        `${props.data?.pointCount || 0} 测点`),
    ])
  }
})

const RuleEdge = defineComponent({
  props: { id: String, source: String, target: String, data: Object },
  setup(props) {
    return () => h('div', {
      style: { background: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', border: '1px solid #d9d9d9' }
    }, props.data?.label || 'rule')
  }
})

const { addEdges, onConnect: vfOnConnect } = useVueFlow()

const nodes = ref([])
const edges = ref([])
const scenarios = ref([])
const selectedScenario = ref(null)
const showAddDeviceModal = ref(false)
const showRuleModal = ref(false)
const showPointsModal = ref(false)
const saving = ref(false)
const devices = ref([])
const templates = ref([])
const protocols = ref([])
const editingDevice = ref({})
const editingPoints = ref([])

const newNode = ref({ deviceId: '', deviceName: '', protocol: 'modbus_tcp', templateId: null })
const newRule = ref({ name: '', ruleType: 'threshold', sourcePoint: 'value', operator: '>', threshold: 0, targetPoint: 'alarm', targetValue: 'true', cooldown: 0 })
const pendingConnection = ref(null)

const scenarioOptions = computed(() => scenarios.value.map(s => ({ label: s.name, value: s.id })))
const protocolTypeOptions = computed(() => protocols.value.map(p => ({ label: p.display_name, value: p.name })))
const templateOptions = computed(() => templates.value.map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id })))
const operatorOptions = [
  { label: '大于 (>)', value: '>' },
  { label: '大于等于 (>=)', value: '>=' },
  { label: '小于 (<)', value: '<' },
  { label: '小于等于 (<=)', value: '<=' },
  { label: '等于 (==)', value: '==' },
  { label: '不等于 (!=)', value: '!=' },
]
const ruleTypeOptions = [
  { label: '阈值触发', value: 'threshold' },
  { label: '值变化触发', value: 'value_change' },
  { label: '定时触发', value: 'timer' },
  { label: '脚本触发', value: 'script' },
]

const pointEditColumns = [
  { title: '名称', key: 'name', width: 120, render: (row, idx) => h(NInput, { value: row.name, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].name = v } }) },
  { title: '地址', key: 'address', width: 80, render: (row, idx) => h(NInput, { value: row.address, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].address = v } }) },
  { title: '数据类型', key: 'data_type', width: 100, render: (row, idx) => h(NSelect, { value: row.data_type, size: 'tiny', options: dataTypeOptions, onUpdateValue: v => { editingPoints.value[idx].data_type = v } }) },
  { title: '生成器', key: 'generator_type', width: 100, render: (row, idx) => h(NSelect, { value: row.generator_type, size: 'tiny', options: generatorOptions, onUpdateValue: v => { editingPoints.value[idx].generator_type = v } }) },
  { title: '最小值', key: 'min_value', width: 80, render: (row, idx) => h(NInputNumber, { value: row.min_value, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].min_value = v } }) },
  { title: '最大值', key: 'max_value', width: 80, render: (row, idx) => h(NInputNumber, { value: row.max_value, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].max_value = v } }) },
  { title: '操作', key: 'actions', width: 60, render: (row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => editingPoints.value.splice(idx, 1) }, () => '删') },
]

const dataTypeOptions = [
  { label: 'float32', value: 'float32' },
  { label: 'float64', value: 'float64' },
  { label: 'int16', value: 'int16' },
  { label: 'int32', value: 'int32' },
  { label: 'uint16', value: 'uint16' },
  { label: 'bool', value: 'bool' },
  { label: 'string', value: 'string' },
]

const generatorOptions = [
  { label: '随机', value: 'random' },
  { label: '正弦波', value: 'sine' },
  { label: '锯齿波', value: 'sawtooth' },
  { label: '方波', value: 'square' },
  { label: '递增', value: 'increment' },
  { label: '常量', value: 'constant' },
]

function onConnect(params) {
  pendingConnection.value = params
  showRuleModal.value = true
}

function onNodeDoubleClick({ node }) {
  const deviceData = node.data || {}
  editingDevice.value = { nodeId: node.id, label: deviceData.label, deviceId: deviceData.deviceId }
  editingPoints.value = (deviceData.points || [{ name: 'value', address: '0', data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 }]).map(p => ({ ...p }))
  showPointsModal.value = true
}

function addPoint() {
  editingPoints.value.push({ name: '', address: String(editingPoints.value.length), data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 })
}

function savePoints() {
  const node = nodes.value.find(n => n.id === editingDevice.value.nodeId)
  if (node) {
    node.data.points = [...editingPoints.value]
    node.data.pointCount = editingPoints.value.length
  }
  showPointsModal.value = false
  message.success('测点已更新')
}

function confirmRule() {
  if (pendingConnection.value) {
    addEdges([{
      ...pendingConnection.value,
      type: 'rule',
      data: {
        label: `${newRule.value.name}: ${newRule.value.sourcePoint} ${newRule.value.operator} ${newRule.value.threshold}`,
        rule: { ...newRule.value },
      },
      animated: true,
    }])
  }
  showRuleModal.value = false
  pendingConnection.value = null
}

function addDeviceNode() {
  showAddDeviceModal.value = true
}

async function confirmAddNode() {
  const id = `node-${Date.now()}`
  const x = 100 + Math.random() * 400
  const y = 100 + Math.random() * 300
  let points = [{ name: 'value', address: '0', data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 }]
  if (newNode.value.templateId) {
    try {
      const tmplRes = await api.getTemplate(newNode.value.templateId)
      points = tmplRes.points || points
    } catch (e) { /* use default */ }
  }
  nodes.value.push({
    id, type: 'device', position: { x, y },
    data: {
      label: newNode.value.deviceName, deviceId: newNode.value.deviceId,
      protocol: newNode.value.protocol, online: false, points, pointCount: points.length
    }
  })
  showAddDeviceModal.value = false
  newNode.value = { deviceId: '', deviceName: '', protocol: 'modbus_tcp', templateId: null }
}

async function loadScenario(scenarioId) {
  if (!scenarioId) return
  try {
    const scenario = await api.getScenario(scenarioId)
    nodes.value = (scenario.devices || []).map((d, i) => ({
      id: `node-${d.id}`, type: 'device',
      position: d.position || { x: 100 + (i % 3) * 250, y: 100 + Math.floor(i / 3) * 150 },
      data: {
        label: d.name, deviceId: d.id, protocol: d.protocol,
        online: false, points: d.points || [], pointCount: (d.points || []).length
      }
    }))
    edges.value = (scenario.rules || []).map((rule, i) => ({
      id: `edge-${i}`, source: `node-${rule.source_device_id}`, target: `node-${rule.target_device_id}`,
      type: 'rule', data: { label: rule.name || `Rule ${i}`, rule },
      animated: true,
    })).filter(e => e.source && e.target)
  } catch (e) {
    message.error('加载场景失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveScenarioLayout() {
  if (!selectedScenario.value) {
    message.warning('请先选择一个场景')
    return
  }
  saving.value = true
  try {
    const deviceConfigs = nodes.value.map(n => ({
      id: n.data.deviceId, name: n.data.label, protocol: n.data.protocol,
      points: (n.data.points || []).map(p => ({
        name: p.name, address: p.address ?? '0',
        data_type: p.data_type || 'float32', unit: p.unit || '',
        description: p.description || '', access: p.access || 'rw',
        generator_type: p.generator_type || 'random',
        generator_config: p.generator_config || {},
        min_value: p.min_value ?? null, max_value: p.max_value ?? null,
        fixed_value: p.fixed_value ?? null,
      })),
      protocol_config: n.data.protocol_config || {},
      position: n.position,
    }))
    const rules = edges.value.map(e => ({
      id: e.id, name: e.data?.rule?.name || e.data?.label || 'Rule',
      rule_type: e.data?.rule?.ruleType || 'threshold',
      source_device_id: e.source?.replace('node-', '') || '',
      source_point: e.data?.rule?.sourcePoint || 'value',
      target_device_id: e.target?.replace('node-', '') || '',
      target_point: e.data?.rule?.targetPoint || 'alarm',
      target_value: e.data?.rule?.targetValue || 'true',
      condition: {
        operator: e.data?.rule?.operator || '>',
        value: e.data?.rule?.threshold || 0,
        cooldown: e.data?.rule?.cooldown || 0,
      },
      enabled: true,
    })).filter(r => r.source_device_id && r.target_device_id)
    const currentScenario = scenarios.value.find(s => s.id === selectedScenario.value)
    await api.updateScenario(selectedScenario.value, {
      id: selectedScenario.value,
      name: currentScenario?.name || '',
      description: currentScenario?.description || '',
      devices: deviceConfigs, rules,
    })
    message.success('场景布局已保存')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function startScenario() {
  if (!selectedScenario.value) return
  try {
    await api.startScenario(selectedScenario.value)
    message.success('场景已启动')
    await loadScenario(selectedScenario.value)
  } catch (e) {
    message.error('启动失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function stopScenario() {
  if (!selectedScenario.value) return
  try {
    await api.stopScenario(selectedScenario.value)
    message.success('场景已停止')
    await loadScenario(selectedScenario.value)
  } catch (e) {
    message.error('停止失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadData() {
  try {
    const [sRes, dRes, tRes, pRes] = await Promise.all([
      api.getScenarios(), api.getDevices(), api.getTemplates(), api.getProtocols()
    ])
    scenarios.value = sRes
    devices.value = dRes
    templates.value = tRes
    protocols.value = pRes
    const scenarioId = route.params.id
    if (scenarioId) {
      selectedScenario.value = scenarioId
      await loadScenario(scenarioId)
    }
  } catch (e) {
    message.error('加载数据失败')
  }
}

onMounted(loadData)
</script>
