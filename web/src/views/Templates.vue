<template>
  <n-space vertical>
    <n-space justify="space-between">
      <n-space>
        <n-select v-model:value="filterProtocol" :options="protocolOptions" :placeholder="t('templates.filterByProtocol')" clearable style="width: 160px" />
        <n-input v-model:value="searchQuery" :placeholder="t('templates.searchPlaceholder')" clearable style="width: 200px" @keyup.enter="doSearch" />
        <n-button type="primary" @click="doSearch" :loading="searching">{{ t('templates.search') }}</n-button>
        <n-select v-model:value="filterTag" :options="tagOptions" :placeholder="t('templates.filterByTag')" clearable style="width: 160px" />
      </n-space>
      <n-button type="primary" @click="showCreateModal = true">{{ t('templates.createTemplate') }}</n-button>
    </n-space>
    <n-grid v-if="filteredTemplates.length > 0" :cols="3" :x-gap="16" :y-gap="16">
      <n-gi v-for="tpl in filteredTemplates" :key="tpl.id">
        <n-card :title="tpl.name" size="small" hoverable>
          <template #header-extra>
            <n-tag size="small">{{ tpl.protocol }}</n-tag>
          </template>
          <n-descriptions label-placement="left" :column="1" size="small">
            <n-descriptions-item :label="t('templates.manufacturer')">{{ tpl.manufacturer || '-' }}</n-descriptions-item>
            <n-descriptions-item :label="t('templates.model')">{{ tpl.model || '-' }}</n-descriptions-item>
            <n-descriptions-item :label="t('templates.pointCount')">{{ tpl.point_count ?? (tpl.points?.length ?? 0) }}</n-descriptions-item>
            <n-descriptions-item :label="t('common.description')">{{ tpl.description || '-' }}</n-descriptions-item>
          </n-descriptions>
          <template #action>
            <n-space justify="space-between" align="center">
              <n-space>
                <n-tag v-for="tag in (tpl.tags || []).slice(0, 2)" :key="tag" size="tiny" type="info">{{ tag }}</n-tag>
              </n-space>
              <n-space size="small">
                <n-button size="tiny" type="primary" @click="openInstantiate(tpl)">{{ t('templates.instantiate') }}</n-button>
                <n-button size="tiny" secondary @click="openEdit(tpl)">{{ t('common.edit') }}</n-button>
                <n-button size="tiny" type="error" @click="confirmDelete(tpl)">{{ t('common.delete') }}</n-button>
              </n-space>
            </n-space>
          </template>
        </n-card>
      </n-gi>
    </n-grid>

    <n-space v-if="filteredTemplates.length === 0" style="text-align:center;padding:40px">
      <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6"/></svg>
      <div class="pf-section-title" style="font-size:16px">{{ t('templates.noTemplates') }}</div>
      <div style="margin-top: 12px">
        <n-text depth="3">{{ t('templates.tryClearFilter') }}</n-text>
      </div>
      <div style="margin-top: 16px">
        <n-button type="primary" @click="goMarketplace">{{ t('templates.goToMarketplace') }}</n-button>
      </div>
    </n-space>

    <n-modal v-model:show="showCreateModal" preset="card" :title="t('templates.createTitle')" style="width: 750px">
      <n-space vertical>
        <n-form :model="newTemplate" label-placement="left" label-width="80">
          <n-form-item :label="t('templates.templateId')">
            <n-input v-model:value="newTemplate.id" :placeholder="t('templates.templateIdPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('templates.templateName')">
            <n-input v-model:value="newTemplate.name" :placeholder="t('templates.templateNamePlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('templates.protocol')">
            <n-select v-model:value="newTemplate.protocol" :options="protocolOptions.filter(o => o.value)" />
          </n-form-item>
          <n-form-item :label="t('templates.manufacturer')">
            <n-input v-model:value="newTemplate.manufacturer" />
          </n-form-item>
          <n-form-item :label="t('templates.model')">
            <n-input v-model:value="newTemplate.model" />
          </n-form-item>
          <n-form-item :label="t('common.description')">
            <n-input v-model:value="newTemplate.description" type="textarea" />
          </n-form-item>
          <n-form-item :label="t('templates.tags')">
            <n-dynamic-tags v-model:value="newTagList" />
          </n-form-item>
        </n-form>
        <n-divider />
        <n-space justify="space-between" align="center">
          <n-text strong>{{ t('templates.pointConfigCount', { n: newTemplate.points.length }) }}</n-text>
          <n-button size="small" type="primary" @click="addNewPoint">{{ t('scenarioEditor.addPoint') }}</n-button>
        </n-space>
        <div v-if="newTemplate.points.length === 0" style="text-align:center;padding:20px">
          <n-text depth="3">{{ t('templates.noPointsHint') }}</n-text>
        </div>
        <n-data-table v-else :columns="pointEditColumns" :data="newTemplate.points" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showCreateModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="createTemplate" :loading="creating">{{ t('common.create') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEditModal" preset="card" :title="t('templates.editTitle')" style="width: 750px">
      <n-space vertical>
        <n-form :model="editForm" label-placement="left" label-width="80">
          <n-form-item :label="t('templates.templateId')">
            <n-input v-model:value="editForm.id" disabled />
          </n-form-item>
          <n-form-item :label="t('templates.templateName')">
            <n-input v-model:value="editForm.name" />
          </n-form-item>
          <n-form-item :label="t('templates.protocol')">
            <n-select v-model:value="editForm.protocol" :options="protocolOptions.filter(o => o.value)" />
          </n-form-item>
          <n-form-item :label="t('templates.manufacturer')">
            <n-input v-model:value="editForm.manufacturer" />
          </n-form-item>
          <n-form-item :label="t('templates.model')">
            <n-input v-model:value="editForm.model" />
          </n-form-item>
          <n-form-item :label="t('common.description')">
            <n-input v-model:value="editForm.description" type="textarea" />
          </n-form-item>
          <n-form-item :label="t('templates.tags')">
            <n-dynamic-tags v-model:value="editTagList" />
          </n-form-item>
        </n-form>
        <n-divider />
        <n-space justify="space-between" align="center">
          <n-text strong>{{ t('templates.pointConfigCount', { n: editForm.points.length }) }}</n-text>
          <n-button size="small" type="primary" @click="addEditPoint">{{ t('scenarioEditor.addPoint') }}</n-button>
        </n-space>
        <div v-if="editForm.points.length === 0" style="text-align:center;padding:20px">
          <n-text depth="3">{{ t('templates.noPointsHint') }}</n-text>
        </div>
        <n-data-table v-else :columns="editPointColumns" :data="editForm.points" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showEditModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="saveEditTemplate" :loading="saving">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showInstantiateModal" preset="card" :title="t('templates.instantiateTitle')" style="width: 450px">
      <n-form :model="instantiateForm" label-placement="left" label-width="80">
        <n-form-item :label="t('templates.templateLabel')">
          <n-input :value="selectedTemplate?.name" disabled />
        </n-form-item>
        <n-form-item :label="t('templates.deviceId')">
          <n-input v-model:value="instantiateForm.device_id" :placeholder="t('templates.deviceIdPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('templates.deviceName')">
          <n-input v-model:value="instantiateForm.device_name" :placeholder="t('templates.deviceNamePlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showInstantiateModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="instantiateDevice" :loading="instantiating">{{ t('templates.createDevice') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NSelect, NInput, NButton, NGrid, NGi, NCard, NTag, NDescriptions, NDescriptionsItem, NModal, NForm, NFormItem, NInputNumber, NDivider, NDataTable, NDynamicTags, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { dataTypeOptions as _dataTypeOptions, generatorTypeOptions as _generatorTypeOptions } from '../constants.js'
import { useRouter } from 'vue-router'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
const templates = ref([])
const protocols = ref([])
const filterProtocol = ref(null)
const searchQuery = ref('')
const filterTag = ref(null)
const allTags = ref([])
const searching = ref(false)
const showCreateModal = ref(false)
const showEditModal = ref(false)
const showInstantiateModal = ref(false)
const creating = ref(false)
const saving = ref(false)
const instantiating = ref(false)
const selectedTemplate = ref(null)
const instantiateForm = ref({ device_id: '', device_name: '' })

const newTemplate = ref({ id: '', name: '', protocol: 'modbus_tcp', manufacturer: '', model: '', description: '', points: [], tags: [] })
const newTagList = ref([])

const editForm = ref({ id: '', name: '', protocol: '', manufacturer: '', model: '', description: '', points: [], tags: [], protocol_config: {} })
const editTagList = ref([])

const protocolOptions = computed(() => [
  { label: t('common.all'), value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const tagOptions = computed(() => [
  { label: t('common.allTags'), value: null },
  ...allTags.value.map(tag => ({ label: tag, value: tag })),
])

const filteredTemplates = computed(() => {
  let result = templates.value
  if (filterProtocol.value) {
    result = result.filter(tpl => tpl.protocol === filterProtocol.value)
  }
  if (filterTag.value) {
    result = result.filter(tpl => (tpl.tags || []).includes(filterTag.value))
  }
  if (searchQuery.value && !searching.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(tpl =>
      tpl.name.toLowerCase().includes(q) ||
      (tpl.description || '').toLowerCase().includes(q) ||
      (tpl.tags || []).some(tag => tag.toLowerCase().includes(q))
    )
  }
  return result
})

const dataTypeOptions = _dataTypeOptions
const generatorOptions = _generatorTypeOptions

const pointEditColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 100, render: makeEditRenderer('name', newTemplate, NInput) },
  { title: t('common.address'), key: 'address', width: 80, render: makeEditRenderer('address', newTemplate, NInput) },
  { title: t('common.dataType'), key: 'data_type', width: 90, render: makeSelectRenderer('data_type', newTemplate, dataTypeOptions) },
  { title: t('common.generator'), key: 'generator_type', width: 90, render: makeSelectRenderer('generator_type', newTemplate, generatorOptions) },
  { title: t('common.minValue'), key: 'min_value', width: 80, render: makeEditRenderer('min_value', newTemplate, NInputNumber) },
  { title: t('common.maxValue'), key: 'max_value', width: 80, render: makeEditRenderer('max_value', newTemplate, NInputNumber) },
  { title: t('common.action'), key: 'actions', width: 60, render: (_row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => newTemplate.value.points.splice(idx, 1) }, () => t('common.delete')) },
])

const editPointColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 100, render: makeEditRenderer('name', editForm, NInput) },
  { title: t('common.address'), key: 'address', width: 80, render: makeEditRenderer('address', editForm, NInput) },
  { title: t('common.dataType'), key: 'data_type', width: 90, render: makeSelectRenderer('data_type', editForm, dataTypeOptions) },
  { title: t('common.generator'), key: 'generator_type', width: 90, render: makeSelectRenderer('generator_type', editForm, generatorOptions) },
  { title: t('common.minValue'), key: 'min_value', width: 80, render: makeEditRenderer('min_value', editForm, NInputNumber) },
  { title: t('common.maxValue'), key: 'max_value', width: 80, render: makeEditRenderer('max_value', editForm, NInputNumber) },
  { title: t('common.action'), key: 'actions', width: 60, render: (_row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => editForm.value.points.splice(idx, 1) }, () => t('common.delete')) },
])

function makeEditRenderer(key, sourceRef, Component) {
  return (_row, idx) => h(Component, {
    value: sourceRef.value.points[idx]?.[key],
    size: 'tiny',
    placeholder: key,
    style: 'width:100%',
    onUpdateValue: (v) => { const p = sourceRef.value.points[idx]; if (p) p[key] = v },
  })
}

function makeSelectRenderer(key, sourceRef, options) {
  return (_row, idx) => h(NSelect, {
    value: sourceRef.value.points[idx]?.[key],
    size: 'tiny',
    options,
    style: 'width:100%',
    onUpdateValue: (v) => { const p = sourceRef.value.points[idx]; if (p) p[key] = v },
  })
}

function goMarketplace() { router.push('/marketplace') }

async function loadData() {
  try {
    const results = await Promise.allSettled([api.getTemplates(), api.getProtocols()])
    templates.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
    protocols.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    if (results[0].status === 'rejected') message.warning(t('templates.loadTemplatesFailed'))
    if (results[1].status === 'rejected') message.warning(t('templates.loadProtocolsFailed'))
    await loadTags()
  } catch (e) {
    message.error(t('common.loadDataFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function loadTags() {
  try { const res = await api.listTemplateTags(); allTags.value = res || [] } catch (e) { allTags.value = []; message.warning(t('templates.loadTagsFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function doSearch() {
  if (!searchQuery.value) { await loadData(); return }
  searching.value = true
  try {
    const params = { q: searchQuery.value }
    if (filterProtocol.value) params.protocol = filterProtocol.value
    if (filterTag.value) params.tag = filterTag.value
    const res = await api.searchTemplates(params)
    templates.value = res || []
  } catch (e) {
    message.error(t('templates.searchFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { searching.value = false }
}

function addNewPoint() {
  newTemplate.value.points.push({ name: 'point_' + (newTemplate.value.points.length + 1), address: String(newTemplate.value.points.length), data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 })
}

function addEditPoint() {
  editForm.value.points.push({ name: 'point_' + (editForm.value.points.length + 1), address: String(editForm.value.points.length), data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 })
}

async function createTemplate() {
  if (!newTemplate.value.id || !newTemplate.value.name) { message.warning(t('templates.fillIdAndName')); return }
  creating.value = true
  try {
    await api.createTemplate({
      ...newTemplate.value, tags: newTagList.value,
      point_count: newTemplate.value.points.length,
    })
    showCreateModal.value = false
    newTemplate.value = { id: '', name: '', protocol: 'modbus_tcp', manufacturer: '', model: '', description: '', points: [], tags: [] }
    newTagList.value = []
    message.success(t('templates.templateCreated'))
    await loadData()
  } catch (e) {
    message.error(t('common.createFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { creating.value = false }
}

async function openEdit(tpl) {
  try {
    const detail = await api.getTemplate(tpl.id)
    editForm.value = {
      id: detail.id, name: detail.name, protocol: detail.protocol,
      manufacturer: detail.manufacturer || '', model: detail.model || '',
      description: detail.description || '',
      points: (detail.points || []).map(p => ({
        name: p.name, address: p.address || String(0),
        data_type: p.data_type || 'float32', generator_type: p.generator_type || 'random',
        min_value: p.min_value ?? 0, max_value: p.max_value ?? 100,
        fixed_value: p.fixed_value ?? null, unit: p.unit || '', access: p.access || 'rw',
      })),
      tags: detail.tags || [], protocol_config: detail.protocol_config || {},
    }
    editTagList.value = [...(detail.tags || [])]
    showEditModal.value = true
  } catch (e) {
    message.error(t('templates.getDetailFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function saveEditTemplate() {
  if (!editForm.value.name) { message.warning(t('templates.fillName')); return }
  saving.value = true
  try {
    await api.updateTemplate(editForm.value.id, {
      ...editForm.value, tags: editTagList.value,
    })
    showEditModal.value = false
    message.success(t('templates.templateUpdated'))
    await loadData()
  } catch (e) {
    message.error(t('common.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

function openInstantiate(tpl) {
  selectedTemplate.value = tpl
  instantiateForm.value = { device_id: '', device_name: tpl.name }
  showInstantiateModal.value = true
}

async function instantiateDevice() {
  if (!selectedTemplate.value) return
  if (!instantiateForm.value.device_id) { message.warning(t('templates.fillDeviceId')); return }
  instantiating.value = true
  try {
    const deviceConfig = await api.instantiateTemplate(selectedTemplate.value.id, { device_id: instantiateForm.value.device_id, device_name: instantiateForm.value.device_name })
    await api.createDevice(deviceConfig)
    showInstantiateModal.value = false
    message.success(t('templates.instantiateSuccess'))
  } catch (e) {
    message.error(t('templates.instantiateFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { instantiating.value = false }
}

function confirmDelete(tpl) {
  dialog.warning({
    title: t('common.delete'),
    content: t('templates.confirmDeleteTemplateDesc', { name: tpl.name, id: tpl.id }),
    positiveText: t('common.delete'), negativeText: t('common.cancel'),
    onPositiveClick: () => deleteTemplate(tpl.id),
  })
}

async function deleteTemplate(id) {
  try { await api.deleteTemplate(id); message.success(t('templates.templateDeleted')); await loadData() }
  catch (e) { message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

onMounted(loadData)
</script>
