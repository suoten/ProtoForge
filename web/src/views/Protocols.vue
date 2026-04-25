<template>
  <div>
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <div class="pf-section-title">协议服务</div>
          <div class="pf-section-desc">点击「一键启动」即可使用默认配置启动协议</div>
        </div>
        <n-button type="primary" @click="startAll" :loading="startingAll">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
          全部启动
        </n-button>
      </n-space>

      <n-grid :cols="3" :x-gap="16" :y-gap="16">
        <n-gi v-for="p in protocols" :key="p.name">
          <n-card size="small" hoverable>
            <template #header>
              <n-space align="center" size="small">
                <div :style="{ width:'36px',height:'36px',borderRadius:'10px',display:'flex',alignItems:'center',justifyContent:'center',background: protocolColors[p.name] || '#f1f5f9' }">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="white" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                </div>
                <div>
                  <div style="font-weight:600;font-size:14px">{{ p.display_name || p.name }}</div>
                  <div style="font-size:11px;color:#94a3b8">{{ p.description || '物联网协议服务' }}</div>
                </div>
              </n-space>
            </template>
            <template #header-extra>
              <n-tag :type="p.status === 'running' ? 'success' : 'default'" size="small" :bordered="false">
                <template #icon v-if="p.status === 'running'">
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                </template>
                {{ p.status === 'running' ? '运行中' : '已停止' }}
              </n-tag>
            </template>
            <n-space justify="space-between" align="center">
              <n-space size="small" align="center">
                <n-text depth="3" style="font-size:12px">{{ p.default_port ? `端口 ${p.default_port}` : '' }}</n-text>
                <n-tag size="tiny" :type="protocolModes[p.name] === 'client' ? 'warning' : 'info'" :bordered="false">
                  {{ protocolModes[p.name] === 'client' ? '客户端上报' : '服务端模拟' }}
                </n-tag>
              </n-space>
              <n-space size="small">
                <n-button v-if="p.status !== 'running'" type="primary" size="small" @click="quickStart(p.name)">一键启动</n-button>
                <n-button v-else type="warning" size="small" @click="stopProtocol(p.name)">停止</n-button>
                <n-button size="small" tertiary @click="openAdvanced(p)">高级配置</n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>

      <n-modal v-model:show="showAdvanced" preset="card" :title="`高级配置 - ${advancedProtocol.display_name || advancedProtocol.name}`" style="width: 500px">
        <n-alert type="info" :bordered="false" style="margin-bottom: 12px">留空将使用默认值，无需全部填写</n-alert>
        <n-form :model="advancedConfig" label-placement="left" label-width="80">
          <n-form-item v-for="(value, key) in advancedConfig" :key="key" :label="key">
            <n-input v-model:value="advancedConfig[key]" :placeholder="String(value)" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAdvanced = false">取消</n-button>
            <n-button type="primary" @click="startWithConfig" :loading="starting">启动</n-button>
          </n-space>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { NSpace, NGrid, NGi, NCard, NTag, NButton, NAlert, NModal, NForm, NFormItem, NInput, NText, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const protocols = ref([])
const showAdvanced = ref(false)
const starting = ref(false)
const startingAll = ref(false)
const advancedProtocol = ref({})
const advancedConfig = ref({})

const protocolColors = {
  modbus_tcp: '#6366f1', modbus_rtu: '#818cf8', opcua: '#10b981', mqtt: '#f59e0b',
  http: '#8b5cf6', gb28181: '#ef4444', bacnet: '#06b6d4', s7: '#3b82f6',
  mc: '#e11d48', fins: '#0ea5e9', ab: '#f97316', opcda: '#14b8a6',
  fanuc: '#eab308', mtconnect: '#22c55e', toledo: '#a855f7',
}

async function loadData() {
  try {
    const res = await api.getProtocols()
    protocols.value = res
  } catch (e) {
    message.error('加载协议列表失败')
  }
}

const protocolModes = {
  modbus_tcp: 'server', modbus_rtu: 'server', opcua: 'server', mqtt: 'client',
  http: 'server', gb28181: 'client', bacnet: 'server', s7: 'server',
  mc: 'server', fins: 'server', ab: 'server', opcda: 'server',
  fanuc: 'server', mtconnect: 'server', toledo: 'server',
}

async function startAll() {
  startingAll.value = true
  const stopped = protocols.value.filter(p => p.status !== 'running')
  let portWarnings = []
  for (const p of stopped) {
    try {
      const res = await api.startProtocol(p.name, null)
      if (res.port_changed) portWarnings.push(`${p.display_name || p.name}: ${res.message}`)
    } catch (e) { /* skip */ }
  }
  message.success(`已启动 ${stopped.length} 个协议`)
  if (portWarnings.length > 0) {
    message.warning(portWarnings.join('\n'), { duration: 8000 })
  }
  await loadData()
  startingAll.value = false
}

async function quickStart(name) {
  try {
    const res = await api.startProtocol(name, null)
    if (res.port_changed) {
      message.warning(res.message, { duration: 6000 })
    } else {
      message.success(`${name} 已启动（使用默认配置）`)
    }
    await loadData()
  } catch (e) {
    message.error('启动失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function stopProtocol(name) {
  try {
    await api.stopProtocol(name)
    message.success(`${name} 已停止`)
    await loadData()
  } catch (e) {
    message.error('停止失败: ' + (e.response?.data?.detail || e.message))
  }
}

function openAdvanced(p) {
  advancedProtocol.value = p
  try {
    const schema = p.config_schema || {}
    advancedConfig.value = {}
    for (const [key, info] of Object.entries(schema)) {
      advancedConfig.value[key] = info.default ?? ''
    }
  } catch (e) {
    advancedConfig.value = { host: '0.0.0.0', port: '' }
  }
  showAdvanced.value = true
}

async function startWithConfig() {
  starting.value = true
  try {
    const config = {}
    for (const [key, value] of Object.entries(advancedConfig.value)) {
      if (value !== '' && value !== null && value !== undefined) {
        config[key] = isNaN(Number(value)) ? value : Number(value)
      }
    }
    await api.startProtocol(advancedProtocol.value.name, config)
    showAdvanced.value = false
    message.success(`${advancedProtocol.value.name} 已启动`)
    await loadData()
  } catch (e) {
    message.error('启动失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    starting.value = false
  }
}

onMounted(loadData)
</script>
