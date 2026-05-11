<template>
  <n-space vertical>
    <n-space justify="space-between" align="center">
      <div>
        <div class="pf-section-title">{{ t('marketplace.title') }}</div>
        <div class="pf-section-desc">{{ t('marketplace.subtitle', { n: templates.length }) }}</div>
      </div>
    </n-space>

    <n-space>
      <n-input v-model:value="searchQuery" :placeholder="t('marketplace.searchPlaceholder')" style="width: 280px" clearable />
      <n-radio-group v-model:value="filterCategory" size="small">
        <n-radio-button value="all">{{ t('marketplace.categoryAll') }}</n-radio-button>
        <n-radio-button value="plc">{{ t('marketplace.categoryPLC') }}</n-radio-button>
        <n-radio-button value="sensor">{{ t('marketplace.categorySensor') }}</n-radio-button>
        <n-radio-button value="cnc">{{ t('marketplace.categoryCNC') }}</n-radio-button>
        <n-radio-button value="iot">{{ t('marketplace.categoryIoT') }}</n-radio-button>
        <n-radio-button value="camera">{{ t('marketplace.categoryCamera') }}</n-radio-button>
        <n-radio-button value="hvac">{{ t('marketplace.categoryBuilding') }}</n-radio-button>
      </n-radio-group>
      <n-select v-model:value="filterProtocol" :options="protocolOptions" :placeholder="t('common.protocol')" clearable style="width: 130px" />
    </n-space>

    <n-grid :cols="3" :x-gap="16" :y-gap="16">
      <n-gi v-for="tmpl in filteredTemplates" :key="tmpl.id">
        <n-card size="small" hoverable style="height: 100%">
          <template #header>
            <n-space align="center" justify="space-between" style="width: 100%">
              <span style="font-weight: bold">{{ tmpl.name }}</span>
              <n-tag :type="protocolTagTypes[tmpl.protocol] || 'default'" size="small">{{ protocolLabels[tmpl.protocol] || tmpl.protocol }}</n-tag>
            </n-space>
          </template>
          <n-text depth="3" style="font-size: 13px">{{ tmpl.description || tmpl.name }}</n-text>
          <div style="margin-top: 8px; font-size: 12px; color: #999">
            {{ tmpl.manufacturer || '' }} {{ tmpl.model ? '| ' + tmpl.model : '' }} | {{ tmpl.point_count || (tmpl.points?.length || 0) }} {{ t('common.points') }}
          </div>
          <div style="margin-top: 6px">
            <n-tag v-for="tag in (tmpl.tags || []).slice(0, 3)" :key="tag" size="tiny" style="margin-right: 4px">{{ tag }}</n-tag>
          </div>
          <template #action>
            <n-button type="primary" size="small" block @click="quickUse(tmpl)">
              {{ t('marketplace.createDevice') }}
            </n-button>
          </template>
        </n-card>
      </n-gi>
    </n-grid>

    <n-empty v-if="filteredTemplates.length === 0" :description="t('marketplace.noMatch')" />

    <n-modal v-model:show="showUseModal" preset="card" :title="t('marketplace.createDevice')" style="width: 420px">
      <n-space vertical>
        <n-text>{{ t('marketplace.quickCreateDesc') }}</n-text>
        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item :label="t('templates.title')">{{ selectedTemplate?.name }}</n-descriptions-item>
          <n-descriptions-item :label="t('common.protocol')">{{ protocolLabels[selectedTemplate?.protocol] || selectedTemplate?.protocol }}</n-descriptions-item>
          <n-descriptions-item :label="t('common.pointCount')">{{ selectedTemplate?.point_count || (selectedTemplate?.points?.length || 0) }}</n-descriptions-item>
        </n-descriptions>
        <n-input v-model:value="useName" :placeholder="t('marketplace.deviceNamePlaceholder')" size="large" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showUseModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="doCreate" :loading="creating" :disabled="!useName">
            {{ t('marketplace.createAndStart') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { NSpace, NText, NInput, NRadioGroup, NRadioButton, NSelect, NGrid, NGi,
  NButton, NTag, NModal, NCard, NAlert, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { protocolTagTypes, protocolLabels } from '../constants.js'

const message = useMessage()
const router = useRouter()
const { t } = useI18n()
const templates = ref([])
const protocols = ref([])
const searchQuery = ref('')
const filterCategory = ref('all')
const filterProtocol = ref(null)
const showUseModal = ref(false)
const creating = ref(false)
const selectedTemplate = ref(null)
const useName = ref('')

const categoryMap = {
  plc: ['plc', 's7', 'siemens', 'mitsubishi', 'omron', 'allen-bradley', 'ab'],
  sensor: ['sensor', 'temperature', 'humidity', 'flow', 'level', 'pressure', 'power', 'vibration', 'smoke'],
  cnc: ['cnc', 'fanuc', 'machine', 'mt', 'machining'],
  iot: ['iot', 'lock', 'hvac', 'charger', 'inverter', 'smart'],
  camera: ['camera', 'nvr', 'ptz', 'gb28181', 'video'],
  hvac: ['hvac', 'ahu', 'lighting', 'bacnet', 'building'],
}

const protocolOptions = computed(() => [
  { label: t('marketplace.categoryAll') + t('common.protocol'), value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const filteredTemplates = computed(() => {
  let result = templates.value
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(item =>
      item.name.toLowerCase().includes(q) ||
      (item.description || '').toLowerCase().includes(q) ||
      (item.manufacturer || '').toLowerCase().includes(q) ||
      (item.tags || []).some(tag => tag.toLowerCase().includes(q))
    )
  }
  if (filterCategory.value !== 'all') {
    const keywords = categoryMap[filterCategory.value] || []
    result = result.filter(item => {
      const text = `${item.id} ${item.name} ${(item.tags || []).join(' ')} ${(item.description || '')} ${(item.manufacturer || '')}`.toLowerCase()
      return keywords.some(k => text.includes(k))
    })
  }
  if (filterProtocol.value) {
    result = result.filter(item => item.protocol === filterProtocol.value)
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
    const deviceId = useName.value.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '') || 'dev-' + Date.now().toString(36)
    await api.quickCreateDevice(selectedTemplate.value.id, useName.value, deviceId)
    message.success(t('welcome.createSuccess', { name: useName.value }), { duration: 5000 })
    showUseModal.value = false
    router.push('/devices')
  } catch (e) {
    message.error(t('common.createFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

async function loadData() {
  try {
    const results = await Promise.allSettled([api.getTemplates(), api.getProtocols()])
    templates.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
    protocols.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    if (results[0].status === 'rejected') message.warning(t('common.loadFailed'))
    if (results[1].status === 'rejected') message.warning(t('common.loadFailed'))
  } catch (e) {
    message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadData)
</script>
