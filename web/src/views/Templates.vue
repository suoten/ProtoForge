<template>
  <n-space vertical>
    <n-space justify="space-between">
      <n-space>
        <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width: 160px" />
        <n-input v-model:value="searchQuery" placeholder="搜索模板..." clearable style="width: 200px" @keyup.enter="doSearch" />
        <n-button type="primary" @click="doSearch" :loading="searching">搜索</n-button>
        <n-select v-model:value="filterTag" :options="tagOptions" placeholder="按标签筛选" clearable style="width: 160px" />
      </n-space>
      <n-button type="primary" @click="showCreateModal = true">创建模板</n-button>
    </n-space>
    <n-grid v-if="filteredTemplates.length > 0" :cols="3" :x-gap="16" :y-gap="16">
      <n-gi v-for="t in filteredTemplates" :key="t.id">
        <n-card :title="t.name" size="small" hoverable>
          <template #header-extra>
            <n-tag size="small">{{ t.protocol }}</n-tag>
          </template>
          <n-descriptions label-placement="left" :column="1" size="small">
            <n-descriptions-item label="厂商">{{ t.manufacturer || '-' }}</n-descriptions-item>
            <n-descriptions-item label="型号">{{ t.model || '-' }}</n-descriptions-item>
            <n-descriptions-item label="测点数">{{ t.point_count }}</n-descriptions-item>
            <n-descriptions-item label="描述">{{ t.description || '-' }}</n-descriptions-item>
          </n-descriptions>
          <template #action>
            <n-space justify="space-between" align="center">
              <n-space>
                <n-tag v-for="tag in (t.tags || []).slice(0, 2)" :key="tag" size="tiny" type="info">{{ tag }}</n-tag>
              </n-space>
              <n-space size="small">
                <n-button size="tiny" type="primary" @click="openInstantiate(t)">实例化</n-button>
                <n-button size="tiny" secondary @click="openEdit(t)">编辑</n-button>
                <n-button size="tiny" type="error" @click="confirmDelete(t)">删除</n-button>
              </n-space>
            </n-space>
          </template>
        </n-card>
      </n-gi>
    </n-grid>

    <n-space v-if="filteredTemplates.length === 0" style="text-align:center;padding:40px">
      <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6"/></svg>
      <div class="pf-section-title" style="font-size:16px">没有找到匹配的模板</div>
      <div style="margin-top: 12px">
        <n-text depth="3">试试清除筛选条件，或前往模板市场浏览更多</n-text>
      </div>
      <div style="margin-top: 16px">
        <n-button type="primary" @click="goMarketplace">前往模板市场</n-button>
      </div>
    </n-space>

    <n-modal v-model:show="showCreateModal" preset="card" title="创建模板" style="width: 750px">
      <n-space vertical>
        <n-form :model="newTemplate" label-placement="left" label-width="80">
          <n-form-item label="模板ID">
            <n-input v-model:value="newTemplate.id" placeholder="如: my-custom-device" />
          </n-form-item>
          <n-form-item label="名称">
            <n-input v-model:value="newTemplate.name" placeholder="如: 自定义传感器" />
          </n-form-item>
          <n-form-item label="协议">
            <n-select v-model:value="newTemplate.protocol" :options="protocolOptions.filter(o => o.value)" />
          </n-form-item>
          <n-form-item label="厂商">
            <n-input v-model:value="newTemplate.manufacturer" />
          </n-form-item>
          <n-form-item label="型号">
            <n-input v-model:value="newTemplate.model" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="newTemplate.description" type="textarea" />
          </n-form-item>
          <n-form-item label="标签">
            <n-dynamic-tags v-model:value="newTagList" />
          </n-form-item>
        </n-form>
        <n-divider />
        <n-space justify="space-between" align="center">
          <n-text strong>测点配置 ({{ newTemplate.points.length }} 个)</n-text>
          <n-button size="small" type="primary" @click="addNewPoint">添加测点</n-button>
        </n-space>
        <div v-if="newTemplate.points.length === 0" style="text-align:center;padding:20px">
          <n-text depth="3">暂无测点，请点击"添加测点"按钮配置</n-text>
        </div>
        <n-data-table v-else :columns="pointEditColumns" :data="newTemplate.points" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showCreateModal = false">取消</n-button>
          <n-button type="primary" @click="createTemplate" :loading="creating">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEditModal" preset="card" title="编辑模板" style="width: 750px">
      <n-space vertical>
        <n-form :model="editForm" label-placement="left" label-width="80">
          <n-form-item label="模板ID">
            <n-input v-model:value="editForm.id" disabled />
          </n-form-item>
          <n-form-item label="名称">
            <n-input v-model:value="editForm.name" />
          </n-form-item>
          <n-form-item label="协议">
            <n-select v-model:value="editForm.protocol" :options="protocolOptions.filter(o => o.value)" />
          </n-form-item>
          <n-form-item label="厂商">
            <n-input v-model:value="editForm.manufacturer" />
          </n-form-item>
          <n-form-item label="型号">
            <n-input v-model:value="editForm.model" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="editForm.description" type="textarea" />
          </n-form-item>
          <n-form-item label="标签">
            <n-dynamic-tags v-model:value="editTagList" />
          </n-form-item>
        </n-form>
        <n-divider />
        <n-space justify="space-between" align="center">
          <n-text strong>测点配置 ({{ editForm.points.length }} 个)</n-text>
          <n-button size="small" type="primary" @click="addEditPoint">添加测点</n-button>
        </n-space>
        <div v-if="editForm.points.length === 0" style="text-align:center;padding:20px">
          <n-text depth="3">暂无测点，请点击"添加测点"按钮配置</n-text>
        </div>
        <n-data-table v-else :columns="editPointColumns" :data="editForm.points" :bordered="false" size="small" />
      </n-space>
      <template #action>
        <n-space>
          <n-button @click="showEditModal = false">取消</n-button>
          <n-button type="primary" @click="saveEditTemplate" :loading="saving">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showInstantiateModal" preset="card" title="从模板实例化设备" style="width: 450px">
      <n-form :model="instantiateForm" label-placement="left" label-width="80">
        <n-form-item label="模板">
          <n-input :value="selectedTemplate?.name" disabled />
        </n-form-item>
        <n-form-item label="设备ID">
          <n-input v-model:value="instantiateForm.device_id" placeholder="如: sensor-001" />
        </n-form-item>
        <n-form-item label="设备名称">
          <n-input v-model:value="instantiateForm.device_name" placeholder="如: 温湿度传感器-1" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showInstantiateModal = false">取消</n-button>
          <n-button type="primary" @click="instantiateDevice" :loading="instantiating">创建设备</n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NSelect, NInput, NButton, NGrid, NGi, NCard, NTag, NDescriptions, NDescriptionsItem, NModal, NForm, NFormItem, NInputNumber, NDivider, NDataTable, NDynamicTags, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useRouter } from 'vue-router'

const router = useRouter()
const message = useMessage()
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
  { label: '全部', value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const tagOptions = computed(() => [
  { label: '全部标签', value: null },
  ...allTags.value.map(t => ({ label: t, value: t })),
])

const filteredTemplates = computed(() => {
  let result = templates.value
  if (filterProtocol.value) {
    result = result.filter(t => t.protocol === filterProtocol.value)
  }
  if (filterTag.value) {
    result = result.filter(t => (t.tags || []).includes(filterTag.value))
  }
  if (searchQuery.value && !searching.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(t =>
      t.name.toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.tags || []).some(tag => tag.toLowerCase().includes(q))
    )
  }
  return result
})

const dataTypeOptions = [
  { label: 'float32', value: 'float32' }, { label: 'float64', value: 'float64' },
  { label: 'int16', value: 'int16' }, { label: 'int32', value: 'int32' },
  { label: 'uint16', value: 'uint16' }, { label: 'bool', value: 'bool' },
  { label: 'string', value: 'string' },
]

const generatorOptions = [
  { label: '随机', value: 'random' }, { label: '正弦波', value: 'sine' },
  { label: '锯齿波', value: 'sawtooth' }, { label: '方波', value: 'square' },
  { label: '递增', value: 'increment' }, { label: '常量', value: 'constant' },
  { label: '固定值', value: 'fixed' },
]

const pointEditColumns = [
  { title: '名称', key: 'name', width: 100, render: makeEditRenderer('name', newTemplate, NInput) },
  { title: '地址', key: 'address', width: 80, render: makeEditRenderer('address', newTemplate, NInput) },
  { title: '类型', key: 'data_type', width: 90, render: makeSelectRenderer('data_type', newTemplate, dataTypeOptions) },
  { title: '生成器', key: 'generator_type', width: 90, render: makeSelectRenderer('generator_type', newTemplate, generatorOptions) },
  { title: '最小值', key: 'min_value', width: 80, render: makeEditRenderer('min_value', newTemplate, NInputNumber) },
  { title: '最大值', key: 'max_value', width: 80, render: makeEditRenderer('max_value', newTemplate, NInputNumber) },
  { title: '操作', key: 'actions', width: 60, render: (_row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => newTemplate.value.points.splice(idx, 1) }, () => '删除') },
]

const editPointColumns = [
  { title: '名称', key: 'name', width: 100, render: makeEditRenderer('name', editForm, NInput) },
  { title: '地址', key: 'address', width: 80, render: makeEditRenderer('address', editForm, NInput) },
  { title: '类型', key: 'data_type', width: 90, render: makeSelectRenderer('data_type', editForm, dataTypeOptions) },
  { title: '生成器', key: 'generator_type', width: 90, render: makeSelectRenderer('generator_type', editForm, generatorOptions) },
  { title: '最小值', key: 'min_value', width: 80, render: makeEditRenderer('min_value', editForm, NInputNumber) },
  { title: '最大值', key: 'max_value', width: 80, render: makeEditRenderer('max_value', editForm, NInputNumber) },
  { title: '操作', key: 'actions', width: 60, render: (_row, idx) => h(NButton, { size: 'tiny', type: 'error', onClick: () => editForm.value.points.splice(idx, 1) }, () => '删除') },
]

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
    const [tmplRes, protoRes] = await Promise.all([api.getTemplates(), api.getProtocols()])
    templates.value = tmplRes
    protocols.value = protoRes
    await loadTags()
  } catch (e) {
    message.error('加载数据失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadTags() {
  try { const res = await api.listTemplateTags(); allTags.value = res?.tags || res || [] } catch { allTags.value = [] }
}

async function doSearch() {
  if (!searchQuery.value) { await loadData(); return }
  searching.value = true
  try {
    const params = { q: searchQuery.value }
    if (filterProtocol.value) params.protocol = filterProtocol.value
    if (filterTag.value) params.tag = filterTag.value
    const res = await api.searchTemplates(params)
    templates.value = (res?.templates || res || [])
  } catch (e) {
    message.error('搜索失败: ' + (e.response?.data?.detail || e.message))
  } finally { searching.value = false }
}

function addNewPoint() {
  newTemplate.value.points.push({ name: 'point_' + (newTemplate.value.points.length + 1), address: String(newTemplate.value.points.length), data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 })
}

function addEditPoint() {
  editForm.value.points.push({ name: 'point_' + (editForm.value.points.length + 1), address: String(editForm.value.points.length), data_type: 'float32', generator_type: 'random', min_value: 0, max_value: 100 })
}

async function createTemplate() {
  if (!newTemplate.value.id || !newTemplate.value.name) { message.warning('请填写模板ID和名称'); return }
  creating.value = true
  try {
    await api.createTemplate({
      ...newTemplate.value, tags: newTagList.value,
      point_count: newTemplate.value.points.length,
    })
    showCreateModal.value = false
    newTemplate.value = { id: '', name: '', protocol: 'modbus_tcp', manufacturer: '', model: '', description: '', points: [], tags: [] }
    newTagList.value = []
    message.success('模板创建成功')
    await loadData()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally { creating.value = false }
}

async function openEdit(t) {
  try {
    const detail = await api.getTemplate(t.id)
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
    message.error('获取模板详情失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveEditTemplate() {
  if (!editForm.value.name) { message.warning('请填写模板名称'); return }
  saving.value = true
  try {
    await api.updateTemplate(editForm.value.id, {
      ...editForm.value, tags: editTagList.value,
    })
    showEditModal.value = false
    message.success('模板已更新')
    await loadData()
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

function openInstantiate(t) {
  selectedTemplate.value = t
  instantiateForm.value = { device_id: '', device_name: t.name }
  showInstantiateModal.value = true
}

async function instantiateDevice() {
  if (!selectedTemplate.value) return
  if (!instantiateForm.value.device_id) { message.warning('请填写设备ID'); return }
  instantiating.value = true
  try {
    const deviceConfig = await api.instantiateTemplate(selectedTemplate.value.id, { device_id: instantiateForm.value.device_id, device_name: instantiateForm.value.device_name })
    await api.createDevice(deviceConfig)
    showInstantiateModal.value = false
    message.success('设备实例化成功')
  } catch (e) {
    message.error('实例化失败: ' + (e.response?.data?.detail || e.message))
  } finally { instantiating.value = false }
}

function confirmDelete(t) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除模板 "${t.name}" (${t.id}) 吗？已基于该模板创建的设备不受影响。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: () => deleteTemplate(t.id),
  })
}

async function deleteTemplate(id) {
  try { await api.deleteTemplate(id); message.success('模板已删除'); await loadData() }
  catch (e) { message.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

onMounted(loadData)
</script>

