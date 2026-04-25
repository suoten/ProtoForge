<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">模板市场</div>
        <div class="pf-section-desc">{{ templates.length }} 个设备模板，选择后一键创建仿真设备</div>
      </div>
    </n-space>

    <n-space>
      <n-input v-model:value="searchQuery" placeholder="搜索模板名称、厂商、标签..." style="width: 280px" clearable />
      <n-radio-group v-model:value="filterCategory" size="small">
        <n-radio-button value="all">全部</n-radio-button>
        <n-radio-button value="plc">PLC</n-radio-button>
        <n-radio-button value="sensor">传感器</n-radio-button>
        <n-radio-button value="cnc">数控机床</n-radio-button>
        <n-radio-button value="iot">IoT设备</n-radio-button>
        <n-radio-button value="camera">摄像头</n-radio-button>
        <n-radio-button value="hvac">楼宇</n-radio-button>
      </n-radio-group>
      <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议" clearable style="width: 130px" />
    </n-space>

    <n-grid :cols="3" :x-gap="16" :y-gap="16">
      <n-gi v-for="t in filteredTemplates" :key="t.id">
        <n-card size="small" hoverable style="height: 100%">
          <template #header>
            <n-space align="center" justify="space-between" style="width: 100%">
              <span style="font-weight: bold">{{ t.name }}</span>
              <n-tag :type="protocolColors[t.protocol] || 'default'" size="small">{{ protocolLabels[t.protocol] || t.protocol }}</n-tag>
            </n-space>
          </template>
          <n-text depth="3" style="font-size: 13px">{{ t.description || '工业设备仿真模板' }}</n-text>
          <div style="margin-top: 8px; font-size: 12px; color: #999">
            {{ t.manufacturer || '' }} {{ t.model ? '| ' + t.model : '' }} | {{ t.point_count || (t.points?.length || 0) }} 测点
          </div>
          <div style="margin-top: 6px">
            <n-tag v-for="tag in (t.tags || []).slice(0, 3)" :key="tag" size="tiny" style="margin-right: 4px">{{ tag }}</n-tag>
          </div>
          <template #action>
            <n-button type="primary" size="small" block @click="quickUse(t)">
              一键创建设备
            </n-button>
          </template>
        </n-card>
      </n-gi>
    </n-grid>

    <n-empty v-if="filteredTemplates.length === 0" description="没有找到匹配的模板，试试其他关键词" />

    <n-modal v-model:show="showUseModal" preset="card" title="一键创建设备" style="width: 420px">
      <n-space vertical>
        <n-text>只需输入设备名称，其他自动配置：</n-text>
        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item label="模板">{{ selectedTemplate?.name }}</n-descriptions-item>
          <n-descriptions-item label="协议">{{ protocolLabels[selectedTemplate?.protocol] || selectedTemplate?.protocol }}</n-descriptions-item>
          <n-descriptions-item label="测点数">{{ selectedTemplate?.point_count || (selectedTemplate?.points?.length || 0) }}</n-descriptions-item>
        </n-descriptions>
        <n-input v-model:value="useName" placeholder="给设备起个名字，如：车间温湿度传感器" size="large" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showUseModal = false">取消</n-button>
          <n-button type="primary" @click="doCreate" :loading="creating" :disabled="!useName">
            创建并启动
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { NSpace, NH3, NText, NInput, NRadioGroup, NRadioButton, NSelect, NGrid, NGi,
  NCard, NTag, NButton, NModal, NDescriptions, NDescriptionsItem, NEmpty, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const templates = ref([])
const protocols = ref([])
const searchQuery = ref('')
const filterCategory = ref('all')
const filterProtocol = ref(null)
const showUseModal = ref(false)
const creating = ref(false)
const selectedTemplate = ref(null)
const useName = ref('')

const protocolColors = {
  modbus_tcp: 'info', modbus_rtu: 'info', opcua: 'success', mqtt: 'warning',
  http: 'default', gb28181: 'error', bacnet: 'info', s7: 'success',
  mc: 'error', fins: 'info', ab: 'warning', opcda: 'success',
  fanuc: 'warning', mtconnect: 'success', toledo: 'default',
}
const protocolLabels = {
  modbus_tcp: 'Modbus TCP', modbus_rtu: 'Modbus RTU', opcua: 'OPC-UA', mqtt: 'MQTT',
  http: 'HTTP', gb28181: 'GB28181', bacnet: 'BACnet', s7: 'S7',
  mc: 'Mitsubishi MC', fins: 'Omron FINS', ab: 'Rockwell AB', opcda: 'OPC-DA',
  fanuc: 'FANUC FOCAS', mtconnect: 'MTConnect', toledo: 'Mettler-Toledo',
}

const categoryMap = {
  plc: ['plc', 's7', 'siemens', 'mitsubishi', 'omron', 'allen-bradley', 'ab'],
  sensor: ['sensor', 'temperature', 'humidity', 'flow', 'level', 'pressure', 'power', 'vibration', 'smoke'],
  cnc: ['cnc', 'fanuc', 'machine', 'mt', 'machining'],
  iot: ['iot', 'lock', 'hvac', 'charger', 'inverter', 'smart'],
  camera: ['camera', 'nvr', 'ptz', 'gb28181', 'video'],
  hvac: ['hvac', 'ahu', 'lighting', 'bacnet', 'building'],
}

const protocolOptions = computed(() => [
  { label: '全部协议', value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const filteredTemplates = computed(() => {
  let result = templates.value
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(t =>
      t.name.toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.manufacturer || '').toLowerCase().includes(q) ||
      (t.tags || []).some(tag => tag.toLowerCase().includes(q))
    )
  }
  if (filterCategory.value !== 'all') {
    const keywords = categoryMap[filterCategory.value] || []
    result = result.filter(t => {
      const text = `${t.id} ${t.name} ${(t.tags || []).join(' ')} ${(t.description || '')} ${(t.manufacturer || '')}`.toLowerCase()
      return keywords.some(k => text.includes(k))
    })
  }
  if (filterProtocol.value) {
    result = result.filter(t => t.protocol === filterProtocol.value)
  }
  return result
})

function quickUse(template) {
  selectedTemplate.value = template
  useName.value = template.name
  showUseModal.value = true
}

async function doCreate() {
  if (!selectedTemplate.value || !useName.value) return
  creating.value = true
  try {
    await api.quickCreateDevice(selectedTemplate.value.id, useName.value)
    message.success(`设备 "${useName.value}" 创建成功并已启动！`)
    showUseModal.value = false
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

async function loadData() {
  try {
    const [tRes, pRes] = await Promise.all([api.getTemplates(), api.getProtocols()])
    templates.value = tRes
    protocols.value = pRes
  } catch (e) {
    message.error('加载模板失败')
  }
}

onMounted(loadData)
</script>
