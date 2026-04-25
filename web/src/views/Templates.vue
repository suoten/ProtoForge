<template>
  <n-space vertical>
    <n-space justify="space-between">
      <n-space>
        <n-select v-model:value="filterProtocol" :options="protocolOptions" placeholder="按协议筛选" clearable style="width: 160px" />
        <n-input v-model:value="searchQuery" placeholder="搜索模板..." clearable style="width: 200px" />
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

    <n-modal v-model:show="showCreateModal" preset="card" title="创建模板" style="width: 600px">
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
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="showCreateModal = false">取消</n-button>
          <n-button type="primary" @click="createTemplate" :loading="creating">创建</n-button>
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
import { ref, computed, onMounted } from 'vue'
import { NSpace, NSelect, NInput, NButton, NGrid, NGi, NCard, NTag, NDescriptions, NDescriptionsItem, NModal, NForm, NFormItem, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'

import { useRouter } from 'vue-router'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const templates = ref([])
const protocols = ref([])
const filterProtocol = ref(null)
const searchQuery = ref('')
const showCreateModal = ref(false)
const showInstantiateModal = ref(false)
const creating = ref(false)
const instantiating = ref(false)
const selectedTemplate = ref(null)
const instantiateForm = ref({ device_id: '', device_name: '' })

const newTemplate = ref({ id: '', name: '', protocol: 'modbus_tcp', manufacturer: '', model: '', description: '', points: [], tags: [] })

const protocolOptions = computed(() => [
  { label: '全部', value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const filteredTemplates = computed(() => {
  let result = templates.value
  if (filterProtocol.value) {
    result = result.filter(t => t.protocol === filterProtocol.value)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(t =>
      t.name.toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.tags || []).some(tag => tag.toLowerCase().includes(q))
    )
  }
  return result
})

function goMarketplace() {
  router.push('/marketplace')
}

async function loadData() {
  try {
    const [tmplRes, protoRes] = await Promise.all([
      api.getTemplates(),
      api.getProtocols(),
    ])
    templates.value = tmplRes
    protocols.value = protoRes
  } catch (e) {
    message.error('加载数据失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function createTemplate() {
  creating.value = true
  try {
    await api.createTemplate({
      ...newTemplate.value,
      point_count: newTemplate.value.points?.length || 0,
    })
    showCreateModal.value = false
    newTemplate.value = { id: '', name: '', protocol: 'modbus_tcp', manufacturer: '', model: '', description: '', points: [], tags: [] }
    message.success('模板创建成功')
    await loadData()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

function openInstantiate(t) {
  selectedTemplate.value = t
  instantiateForm.value = { device_id: '', device_name: t.name }
  showInstantiateModal.value = true
}

async function instantiateDevice() {
  if (!selectedTemplate.value) return
  instantiating.value = true
  try {
    const config = await api.instantiateTemplate(selectedTemplate.value.id, instantiateForm.value)
    await api.createDevice(config.data)
    showInstantiateModal.value = false
    message.success('设备实例化成功')
  } catch (e) {
    message.error('实例化失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    instantiating.value = false
  }
}

function confirmDelete(t) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除模板 "${t.name}" (${t.id}) 吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteTemplate(t.id),
  })
}

async function deleteTemplate(id) {
  try {
    await api._delete(`/templates/${id}`)
    message.success('模板已删除')
    await loadData()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadData)
</script>
