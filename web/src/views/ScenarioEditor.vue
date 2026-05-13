<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('scenarioEditor.title') }}</div>
        <div class="pf-section-desc">{{ t('scenarioEditor.subtitle') }}</div>
      </div>
      <n-space>
        <n-select v-model:value="selectedScenario" :options="scenarioOptions" :placeholder="t('scenarioEditor.selectScenario')" style="width: 200px" @update:value="loadScenario" />
        <n-button type="primary" @click="saveScenarioLayout" :loading="saving">{{ t('scenarioEditor.saveLayout') }}</n-button>
        <n-button @click="addDeviceNode">{{ t('scenarioEditor.addDevice') }}</n-button>
        <n-button type="success" @click="startScenario" :loading="scenarioLoading" v-if="selectedScenario">{{ t('common.start') }}</n-button>
        <n-button type="warning" @click="stopScenario" :loading="scenarioLoading" v-if="selectedScenario">{{ t('common.stop') }}</n-button>
      </n-space>
    </n-space>

    <div style="height: 600px; border: 1px solid #e0e0e0; border-radius: 4px;">
      <VueFlow v-model:nodes="nodes" v-model:edges="edges" :default-viewport="{ zoom: 0.8 }"
        :min-zoom="0.3" :max-zoom="2" fit-view-on-init @connect="onConnect"
        @node-double-click="onNodeDoubleClick"
        @edge-double-click="onEdgeDoubleClick">
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

    <n-modal v-model:show="showAddDeviceModal" preset="card" :title="t('scenarioEditor.addDeviceNode')" style="width: 500px">
      <n-form :model="newNode" label-placement="left" label-width="80">
        <n-form-item :label="t('scenarioEditor.deviceId')">
          <n-input v-model:value="newNode.deviceId" :placeholder="t('scenarioEditor.deviceIdPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.deviceName')">
          <n-input v-model:value="newNode.deviceName" :placeholder="t('scenarioEditor.deviceNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('common.protocol')">
          <n-select v-model:value="newNode.protocol" :options="protocolTypeOptions" @update:value="() => { newNode.templateId = null }" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.fromTemplate')">
          <n-select v-model:value="newNode.templateId" :options="templateOptions" clearable :placeholder="t('scenarioEditor.optional')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showAddDeviceModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="confirmAddNode">{{ t('common.add') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showRuleModal" preset="card" :title="t('scenarioEditor.configureRule')" style="width: 500px">
      <n-form :model="newRule" label-placement="left" label-width="80">
        <n-form-item :label="t('scenarioEditor.ruleName')">
          <n-input v-model:value="newRule.name" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.ruleType')">
          <n-select v-model:value="newRule.ruleType" :options="ruleTypeOptions" :placeholder="t('common.selectPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.sourcePoint')">
          <n-input v-model:value="newRule.sourcePoint" :placeholder="t('scenarioEditor.sourcePointPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.condition')">
          <n-select v-model:value="newRule.operator" :options="operatorOptions" :placeholder="t('common.selectPlaceholder')" style="width: 140px" />
          <n-input-number v-model:value="newRule.threshold" style="width: 150px" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.targetPoint')">
          <n-input v-model:value="newRule.targetPoint" :placeholder="t('scenarioEditor.targetPointPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.targetValue')">
          <n-input v-model:value="newRule.targetValue" :placeholder="t('scenarioEditor.targetValuePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('scenarioEditor.cooldown')">
          <n-input-number v-model:value="newRule.cooldown" :min="0" style="width: 120px" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showRuleModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="confirmRule">{{ t('common.confirm') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showPointsModal" preset="card" :title="t('scenarioEditor.pointEditTitle', { name: editingDevice.label || '' })" style="width: 700px">
      <n-space vertical>
        <n-button size="small" type="primary" @click="addPoint">{{ t('scenarioEditor.addPoint') }}</n-button>
        <n-data-table :columns="pointEditColumns" :data="editingPoints" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showPointsModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="savePoints">{{ t('scenarioEditor.savePoints') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, h, defineComponent } from 'vue'
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
  NTag, NDataTable, useMessage, useDialog
} from 'naive-ui'
import { useRoute, onBeforeRouteLeave } from 'vue-router'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { protocolColors, dataTypeOptions, generatorTypeOptions } from '../constants.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
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
        `${props.data?.pointCount || 0} ${t('common.pointCount')}`),
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
const scenarioLoading = ref(false)
const hasUnsavedChanges = ref(false)
const editingEdgeId = ref(null)
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
const templateOptions = computed(() => {
  const list = newNode.value.protocol
    ? templates.value.filter(tmpl => tmpl.protocol === newNode.value.protocol)
    : templates.value
  return list.map(tmpl => ({ label: `${tmpl.name} (${tmpl.protocol})`, value: tmpl.id }))
})
const operatorOptions = computed(() => [
  { label: t('scenarioEditor.greaterThan'), value: '>' },
  { label: t('scenarioEditor.greaterEqual'), value: '>=' },
  { label: t('scenarioEditor.lessThan'), value: '<' },
  { label: t('scenarioEditor.lessEqual'), value: '<=' },
  { label: t('scenarioEditor.equal'), value: '==' },
  { label: t('scenarioEditor.notEqual'), value: '!=' },
])
const ruleTypeOptions = computed(() => [
  { label: t('scenarioEditor.thresholdTrigger'), value: 'threshold' },
  { label: t('scenarioEditor.valueChangeTrigger'), value: 'value_change' },
  { label: t('scenarioEditor.timerTrigger'), value: 'timer' },
  { label: t('scenarioEditor.scriptTrigger'), value: 'script' },
])

const pointEditColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 120, render: (row, idx) => h(NInput, { value: row.name, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].name = v } }) },
  { title: t('common.address'), key: 'address', width: 80, render: (row, idx) => h(NInput, { value: row.address, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].address = v } }) },
  { title: t('common.dataType'), key: 'data_type', width: 100, render: (row, idx) => h(NSelect, { value: row.data_type, size: 'tiny', options: dataTypeOptions, onUpdateValue: v => { editingPoints.value[idx].data_type = v } }) },
  { title: t('common.generator'), key: 'generator_type', width: 100, render: (row, idx) => h(NSelect, { value: row.generator_type, size: 'tiny', options: generatorOptions, onUpdateValue: v => { editingPoints.value[idx].generator_type = v } }) },
  { title: t('common.minValue'), key: 'min_value', width: 80, render: (row, idx) => h(NInputNumber, { value: row.min_value, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].min_value = v } }) },
  { title: t('common.maxValue'), key: 'max_value', width: 80, render: (row, idx) => h(NInputNumber, { value: row.max_value, size: 'tiny', onUpdateValue: v => { editingPoints.value[idx].max_value = v } }) },
  { title: t('common.action'), key: 'actions', width: 60, render: (row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => editingPoints.value.splice(idx, 1) }, () => t('common.delete')) },
])

const generatorOptions = generatorTypeOptions

function onConnect(params) {
  pendingConnection.value = params
  editingEdgeId.value = null
  newRule.value = { name: '', ruleType: 'threshold', sourcePoint: 'value', operator: '>', threshold: 0, targetPoint: 'alarm', targetValue: 'true', cooldown: 0 }
  showRuleModal.value = true
}

function onNodeDoubleClick({ node }) {
  const deviceData = node.data || {}
  editingDevice.value = { nodeId: node.id, label: deviceData.label, deviceId: deviceData.deviceId }
  editingPoints.value = (deviceData.points || [{ name: 'value', address: '0', data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 }]).map(p => ({ ...p }))
  showPointsModal.value = true
}

function onEdgeDoubleClick({ edge }) {
  const rule = edge.data?.rule || {}
  editingEdgeId.value = edge.id
  const condition = rule.condition || {}
  newRule.value = {
    name: rule.name || edge.data?.label || '',
    ruleType: rule.rule_type || rule.ruleType || 'threshold',
    sourcePoint: rule.source_point || rule.sourcePoint || 'value',
    operator: condition.operator || rule.operator || '>',
    threshold: condition.value ?? rule.threshold ?? 0,
    targetPoint: rule.target_point || rule.targetPoint || 'alarm',
    targetValue: rule.target_value ?? rule.targetValue ?? 'true',
    cooldown: condition.cooldown ?? rule.cooldown ?? 0,
  }
  showRuleModal.value = true
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
  hasUnsavedChanges.value = true
  message.success(t('scenarioEditor.pointsUpdated'))
}

function confirmRule() {
  const ruleLabel = `${newRule.value.name}: ${newRule.value.sourcePoint} ${newRule.value.operator} ${newRule.value.threshold}`
  if (editingEdgeId.value) {
    const edge = edges.value.find(e => e.id === editingEdgeId.value)
    if (edge) {
      edge.data = {
        ...edge.data,
        label: ruleLabel,
        rule: { ...newRule.value },
      }
    }
    editingEdgeId.value = null
  } else if (pendingConnection.value) {
    addEdges([{
      ...pendingConnection.value,
      type: 'rule',
      data: {
        label: ruleLabel,
        rule: { ...newRule.value },
      },
      animated: true,
    }])
  }
  showRuleModal.value = false
  pendingConnection.value = null
  hasUnsavedChanges.value = true
  message.success(t('scenarioEditor.ruleAdded'))
}

function addDeviceNode() {
  showAddDeviceModal.value = true
}

async function confirmAddNode() {
  if (!newNode.value.deviceId?.trim()) { message.warning(t('scenarioEditor.deviceIdRequired')); return }
  if (!newNode.value.deviceName?.trim()) { message.warning(t('scenarioEditor.deviceNameRequired')); return }
  const id = `node-${Date.now()}`
  const x = 100 + Math.random() * 400
  const y = 100 + Math.random() * 300
  let points = [{ name: 'value', address: '0', data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 }]
  if (newNode.value.templateId) {
    try {
      const tmplRes = await api.getTemplate(newNode.value.templateId)
      points = tmplRes.points || points
    } catch (e) { message.warning(t('scenarioEditor.templateLoadFailed')) }
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
  hasUnsavedChanges.value = true
  message.success(t('scenarioEditor.deviceNodeAdded'))
}

async function loadScenario(scenarioId) {
  try {
    const results = await Promise.allSettled([
      api.getScenario(scenarioId),
      api.getDevices(),
    ])
    const scenario = results[0].status === 'fulfilled' ? results[0].value : null
    const allDevices = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    if (results[0].status === 'rejected') {
      message.error(t('scenarioEditor.loadScenarioFailed'))
      return
    }
    if (results[1].status === 'rejected') {
      message.warning(t('scenarioEditor.devicesLoadFailed'))
    }
    const deviceMap = {}
    for (const d of allDevices) {
      deviceMap[d.id] = d.status === 'online' || d.status === 'running'
    }
    nodes.value = (scenario.devices || []).map((d, i) => ({
      id: `node-${d.id}`, type: 'device',
      position: d.position || { x: 100 + (i % 3) * 250, y: 100 + Math.floor(i / 3) * 150 },
      data: {
        label: d.name, deviceId: d.id, protocol: d.protocol,
        online: deviceMap[d.id] || false, points: d.points || [], pointCount: (d.points || []).length
      }
    }))
    edges.value = (scenario.rules || []).map((rule, i) => ({
      id: `edge-${i}`, source: `node-${rule.source_device_id}`, target: `node-${rule.target_device_id}`,
      type: 'rule', data: { label: rule.name || `Rule ${i}`, rule },
      animated: true,
    })).filter(e => e.source && e.target)
  } catch (e) {
    message.error(t('scenarioEditor.loadScenarioFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function saveScenarioLayout() {
  if (!selectedScenario.value) {
    message.warning(t('scenarioEditor.selectScenarioFirst'))
    return
  }
  saving.value = true
  try {
    const deviceConfigs = nodes.value.filter(n => n.data && n.data.deviceId).map(n => ({  // FIXED: 过滤无data或deviceId的节点
      id: n.data.deviceId, name: n.data.label || n.data.deviceId, protocol: n.data.protocol || 'modbus',
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
    const rules = edges.value.filter(e => e.source && e.target).map(e => ({  // FIXED: 过滤无source/target的边
      id: e.id, name: e.data?.rule?.name || e.data?.label || 'Rule',
      rule_type: e.data?.rule?.ruleType || 'threshold',
      source_device_id: e.source.replace('node-', '') || '',
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

    const failedDevices = []
    for (const dc of deviceConfigs) {
      if (!dc.id) continue
      try {
        await api.createDevice({
          id: dc.id, name: dc.name, protocol: dc.protocol,
          points: dc.points, protocol_config: dc.protocol_config,
        })
        try { await api.startDevice(dc.id) } catch (e) { failedDevices.push(dc.name || dc.id); message.warning(t('scenarioEditor.deviceStartFailed', { name: dc.name || dc.id }) + ': ' + (e.response?.data?.detail || e.message)) }
      } catch (e) {
        const status = e.response?.status
        const detail = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : JSON.stringify(e.response?.data?.detail || '')
        if (status === 400 && (detail.includes('already exists') || detail.includes('ALREADY_EXISTS') || e.response?.data?.error_code === 'ALREADY_EXISTS')) {
          try {
            await api.updateDevice(dc.id, {
              id: dc.id, name: dc.name, protocol: dc.protocol,
              points: dc.points, protocol_config: dc.protocol_config,
            })
            try { await api.startDevice(dc.id) } catch (e2) { failedDevices.push(dc.name || dc.id); message.warning(t('scenarioEditor.deviceStartFailed', { name: dc.name || dc.id }) + ': ' + (e2.response?.data?.detail || e2.message)) }
          } catch (e2) {
            failedDevices.push(dc.name || dc.id)
            message.warning(t('scenarioEditor.deviceUpdateFailed', { name: dc.name || dc.id }) + ': ' + (e2.response?.data?.detail || e2.message))
          }
        } else {
          failedDevices.push(dc.name || dc.id)
          message.warning(t('scenarioEditor.deviceCreateFailed', { name: dc.name || dc.id }) + ': ' + (e.response?.data?.detail || e.message))
        }
      }
    }

    const currentScenario = scenarios.value.find(s => s.id === selectedScenario.value)
    await api.updateScenario(selectedScenario.value, {
      id: selectedScenario.value,
      name: currentScenario?.name || '',
      description: currentScenario?.description || '',
      devices: deviceConfigs, rules,
    })
    if (failedDevices.length > 0) {
      message.warning(t('scenarioEditor.savePartialFailed', { count: failedDevices.length }))
    } else {
      message.success(t('scenarioEditor.saveSuccess'))
    }
    hasUnsavedChanges.value = false
  } catch (e) {
    message.error(t('scenarioEditor.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function startScenario() {
  if (!selectedScenario.value) return
  dialog.warning({
    title: t('scenarioEditor.confirmStart'),
    content: t('scenarioEditor.confirmStartDesc'),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      scenarioLoading.value = true
      try {
        await api.startScenario(selectedScenario.value)
        message.success(t('scenarioEditor.scenarioStarted'))
        await loadScenario(selectedScenario.value)
      } catch (e) {
        message.error(t('scenarioEditor.startFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        scenarioLoading.value = false
      }
    }
  })
}

async function stopScenario() {
  if (!selectedScenario.value) return
  dialog.warning({
    title: t('scenarioEditor.confirmStop'),
    content: t('scenarioEditor.confirmStopDesc'),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      scenarioLoading.value = true
      try {
        await api.stopScenario(selectedScenario.value)
        message.success(t('scenarioEditor.scenarioStopped'))
        await loadScenario(selectedScenario.value)
      } catch (e) {
        message.error(t('scenarioEditor.stopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        scenarioLoading.value = false
      }
    }
  })
}

async function loadData() {
  try {
    const results = await Promise.allSettled([
      api.getScenarios(), api.getTemplates(), api.getProtocols()
    ])
    scenarios.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
    templates.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    protocols.value = results[2].status === 'fulfilled' ? (results[2].value || []) : []
    const failedIdx = results.map((r, i) => r.status === 'rejected' ? i : -1).filter(i => i >= 0)
    if (failedIdx.length > 0) {
      const names = [t('scenarios.title'), t('templates.title'), t('protocols.title')]
      message.warning(t('scenarioEditor.partialLoadFailed') + ': ' + failedIdx.map(i => names[i]).join('、'))
    }
    const scenarioId = route.params.id
    if (scenarioId) {
      selectedScenario.value = scenarioId
      await loadScenario(scenarioId)
    }
  } catch (e) {
    message.error(t('scenarioEditor.loadDataFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadData)

onBeforeRouteLeave((_to, _from, next) => {
  if (hasUnsavedChanges.value) {
    dialog.warning({
      title: t('scenarioEditor.unsavedChanges'),
      content: t('scenarioEditor.unsavedChangesDesc'),
      positiveText: t('scenarioEditor.leave'),
      negativeText: t('scenarioEditor.stay'),
      maskClosable: false,
      onPositiveClick: () => next(),
      onNegativeClick: () => next(false),
    })
  } else {
    next()
  }
})

function handleBeforeUnload(e) {
  if (hasUnsavedChanges.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>
