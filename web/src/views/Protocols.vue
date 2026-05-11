<template>
  <div>
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <div class="pf-section-title">{{ t('protocols.title') }}</div>
          <div class="pf-section-desc">{{ t('protocols.subtitle') }}</div>
        </div>
        <n-space>
          <n-button type="primary" @click="startAll" :loading="startingAll">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
            {{ t('protocols.startAll') }}
          </n-button>
          <n-button type="warning" @click="stopAll" :loading="stoppingAll">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
            {{ t('protocols.stopAll') }}
          </n-button>
        </n-space>
      </n-space>

      <n-spin :show="dataLoading">
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
                  <div style="font-size:11px;color:#94a3b8">{{ p.description || t('protocols.defaultDesc') }}</div>
                </div>
              </n-space>
            </template>
            <template #header-extra>
              <n-tag :type="p.status === 'running' ? 'success' : 'default'" size="small" :bordered="false">
                <template #icon v-if="p.status === 'running'">
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                </template>
                {{ p.status === 'running' ? t('common.running') : t('common.stopped') }}
              </n-tag>
            </template>
            <n-space justify="space-between" align="center">
              <n-space size="small" align="center">
                <n-text depth="3" style="font-size:12px">{{ p.default_port ? t('common.port') + ' ' + p.default_port : '' }}</n-text>
                <n-tag size="tiny" :type="protocolModes[p.name] === 'Broker' || protocolModes[p.name] === 'SIP' || protocolModes[p.name] === 'Agent' ? 'warning' : 'info'" :bordered="false">
                  {{ protocolModes[p.name] || 'Server' }}
                </n-tag>
              </n-space>
              <n-space size="small">
                <n-button v-if="p.status !== 'running'" type="primary" size="small" :loading="startingProtocol === p.name" @click="quickStart(p.name)">{{ t('protocols.quickStart') }}</n-button>
                <n-button v-else type="warning" size="small" :loading="stoppingProtocol === p.name" @click="stopProtocol(p.name)">{{ t('common.stop') }}</n-button>
                <n-button size="small" tertiary @click="openAdvanced(p)">{{ t('protocols.advancedConfig') }}</n-button>
                <n-button size="small" tertiary @click="showProtocolInfo(p.name)">{{ t('common.detail') }}</n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>
      </n-spin>

      <n-modal v-model:show="showAdvanced" preset="card" :title="t('protocols.advancedConfigTitle', { name: advancedProtocol.display_name || advancedProtocol.name })" style="width: 500px">
        <n-alert type="info" :bordered="false" style="margin-bottom: 12px">{{ t('protocols.advancedConfigHint') }}</n-alert>
        <n-form :model="advancedConfig" label-placement="left" label-width="80">
          <n-form-item v-for="(value, key) in advancedConfig" :key="key" :label="key">
            <n-input v-model:value="advancedConfig[key]" :placeholder="String(value)" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAdvanced = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="startWithConfig" :loading="starting">{{ t('common.start') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showInfoModal" preset="card" :title="t('protocols.protocolDetailTitle', { name: protocolInfoName })" style="width: 600px">
        <n-spin :show="loadingInfo">
          <n-space vertical v-if="protocolInfoData">
            <n-descriptions label-placement="left" :column="1" bordered size="small">
              <n-descriptions-item :label="t('protocols.protocolName')">{{ protocolInfoData.name || protocolInfoName }}</n-descriptions-item>
              <n-descriptions-item :label="t('protocols.displayName')">{{ protocolInfoData.display_name || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.description')">{{ protocolInfoData.description || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('protocols.defaultPort')">{{ protocolInfoData.default_port || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('protocols.mode')">{{ protocolInfoData.mode || 'Server' }}</n-descriptions-item>
              <n-descriptions-item :label="t('protocols.version')">{{ protocolInfoData.version || '-' }}</n-descriptions-item>
            </n-descriptions>
            <n-text strong v-if="protocolInfoData.features && protocolInfoData.features.length > 0" style="font-size:13px">{{ t('protocols.supportedFeatures') }}:</n-text>
            <n-space v-if="protocolInfoData.features && protocolInfoData.features.length > 0" size="small">
              <n-tag v-for="f in protocolInfoData.features" :key="f" size="tiny" type="info" :bordered="false">{{ f }}</n-tag>
            </n-space>
            <n-text strong v-if="protocolConfigData && Object.keys(protocolConfigData).length > 0" style="font-size:13px">{{ t('protocols.configParams') }}:</n-text>
            <n-data-table v-if="protocolConfigData && Object.keys(protocolConfigData).length > 0"
              :columns="configInfoColumns" :data="configInfoRows" :bordered="false" size="small" />
          </n-space>
        </n-spin>
        <template #action>
          <n-button @click="showInfoModal = false">{{ t('common.close') }}</n-button>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NSpace, NGrid, NGi, NCard, NTag, NButton, NAlert, NModal, NForm, NFormItem, NInput, NText, NDescriptions, NDescriptionsItem, NDataTable, NSpin, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { protocolColors, protocolModes } from '../constants.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
const protocols = ref([])
const dataLoading = ref(false)
const showAdvanced = ref(false)
const starting = ref(false)
const startingProtocol = ref(null)
const stoppingProtocol = ref(null)
const startingAll = ref(false)
const stoppingAll = ref(false)
const advancedProtocol = ref({})
const advancedConfig = ref({})

const showInfoModal = ref(false)
const protocolInfoName = ref('')
const protocolInfoData = ref(null)
const protocolConfigData = ref(null)
const loadingInfo = ref(false)

const configInfoColumns = computed(() => [
  { title: t('protocols.param'), key: 'key', width: 140 },
  { title: t('common.type'), key: 'type', width: 100 },
  { title: t('protocols.defaultValue'), key: 'default', width: 120 },
  { title: t('common.description'), key: 'description' },
])

const configInfoRows = computed(() => {
  if (!protocolConfigData.value) return []
  return Object.entries(protocolConfigData.value)
    .filter(([_, info]) => info !== null && info !== undefined)
    .map(([key, info]) => ({
      key,
      type: (info && info.type) || '-',
      default: (info && info.default) ?? '-',
      description: (info && info.description) || '-',
    }))
})

async function loadData() {
  dataLoading.value = true
  try {
    const res = await api.getProtocols()
    protocols.value = res || []
  } catch (e) {
    message.error(t('protocols.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { dataLoading.value = false }
}

async function startAll() {
  const stopped = protocols.value.filter(p => p.status !== 'running')
  if (!stopped.length) { message.info(t('protocols.allRunning')); return }
  dialog.warning({
    title: t('protocols.confirmStartAll'),
    content: t('protocols.confirmStartAllDesc', { count: stopped.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      startingAll.value = true
      let portWarnings = []
      let failCount = 0
      try {
        for (const p of stopped) {
          try {
            const res = await api.startProtocol(p.name, null)
            if (res.port_changed) portWarnings.push(`${p.display_name || p.name}: ${res.message}`)
          } catch (e) { failCount++; message.warning(t('protocols.protocolStartFailed', { name: p.name }) + ': ' + (e.response?.data?.detail || e.message)) }
        }
        if (failCount > 0) {
          message.warning(t('protocols.startAllPartial', { success: stopped.length - failCount, fail: failCount }))
        } else {
          message.success(t('protocols.startAllSuccess', { count: stopped.length }))
        }
        if (portWarnings.length > 0) {
          message.warning(portWarnings.join('\n'), { duration: 8000 })
        }
        await loadData()
      } finally { startingAll.value = false }
    }
  })
}

async function stopAll() {
  const running = protocols.value.filter(p => p.status === 'running')
  if (!running.length) { message.info(t('protocols.allStopped')); return }
  dialog.warning({
    title: t('protocols.confirmStopAll'),
    content: t('protocols.confirmStopAllDesc', { count: running.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      stoppingAll.value = true
      let failCount = 0
      try {
        for (const p of running) {
          try {
            await api.stopProtocol(p.name)
          } catch (e) { failCount++; message.warning(t('protocols.protocolStopFailed', { name: p.name }) + ': ' + (e.response?.data?.detail || e.message)) }
        }
        if (failCount > 0) {
          message.warning(t('protocols.stopAllPartial', { success: running.length - failCount, fail: failCount }))
        } else {
          message.success(t('protocols.stopAllSuccess', { count: running.length }))
        }
        await loadData()
      } finally { stoppingAll.value = false }
    }
  })
}

async function quickStart(name) {
  dialog.info({
    title: t('protocols.confirmStart') || '确认启动协议',
    content: t('protocols.confirmStartDesc', { name }) || `启动协议 "${name}" 将开放网络端口并消耗系统资源，确定继续？`,
    positiveText: t('common.start') || '启动',
    negativeText: t('common.cancel') || '取消',
    onPositiveClick: async () => {
      startingProtocol.value = name
      try {
        const res = await api.startProtocol(name, null)
        if (res.port_changed) {
          message.warning(res.message, { duration: 6000 })
        } else {
          message.success(t('protocols.protocolStarted', { name }))
        }
        await loadData()
      } catch (e) {
        message.error(t('protocols.startFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        startingProtocol.value = null
      }
    }
  })
}

async function stopProtocol(name) {
  dialog.warning({
    title: t('protocols.confirmStop'),
    content: t('protocols.confirmStopDesc', { name }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      stoppingProtocol.value = name
      try {
        await api.stopProtocol(name)
        message.success(t('protocols.protocolStopped', { name }))
        await loadData()
      } catch (e) {
        message.error(t('protocols.stopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        stoppingProtocol.value = null
      }
    }
  })
}

async function showProtocolInfo(name) {
  protocolInfoName.value = name
  showInfoModal.value = true
  loadingInfo.value = true
  protocolInfoData.value = null
  protocolConfigData.value = null
  try {
    const results = await Promise.allSettled([
      api.getProtocolInfo(),
      api.getProtocolConfig(name),
    ])
    const infoRes = results[0].status === 'fulfilled' ? results[0].value : {}
    const configRes = results[1].status === 'fulfilled' ? results[1].value : {}
    if (results[0].status === 'rejected') message.warning(t('protocols.infoLoadFailed'))
    if (results[1].status === 'rejected') message.warning(t('protocols.configLoadFailed'))
    const infoList = Array.isArray(infoRes) ? infoRes : (infoRes.protocols || [])
    const found = infoList.find(p => p.name === name) || protocols.value.find(p => p.name === name) || { name }
    protocolInfoData.value = found
    protocolConfigData.value = configRes.config_schema || (Object.keys(configRes).length > 0 ? configRes : {})
  } catch (e) {
    protocolInfoData.value = protocols.value.find(p => p.name === name) || { name }
    protocolConfigData.value = {}
  } finally { loadingInfo.value = false }
}

function openAdvanced(p) {
  advancedProtocol.value = p
  try {
    const schema = p.config_schema || {}
    advancedConfig.value = {}
    for (const [key, info] of Object.entries(schema)) {
      if (info !== null && info !== undefined) {
        advancedConfig.value[key] = info.default ?? ''
      }
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
        config[key] = (value !== '' && !isNaN(Number(value))) ? Number(value) : value
      }
    }
    await api.startProtocol(advancedProtocol.value.name, config)
    showAdvanced.value = false
    message.success(t('protocols.protocolStarted', { name: advancedProtocol.value.name }))
    await loadData()
  } catch (e) {
    message.error(t('protocols.startFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    starting.value = false
  }
}

onMounted(() => {
  loadData()
  connectWs()
})

onUnmounted(() => {
  wsManualClose = true
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  if (ws) { ws.close(); ws = null }
})

let ws = null
let wsReconnectTimer = null
let wsReconnectDelay = 1000
let wsReconnectAttempts = 0
let wsManualClose = false
const WS_MAX_RECONNECT_DELAY = 30000
const WS_MAX_RECONNECT_ATTEMPTS = 20
function connectWs() {
  if (wsManualClose) return
  try {
    ws = api.createDeviceWs()
    if (!ws) return
  } catch (e) {
    console.error('Failed to create device WebSocket:', e.message)
    message.warning(t('protocols.wsConnectFailed'))
    wsReconnectAttempts++
    if (wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      wsReconnectTimer = setTimeout(connectWs, 5000)
    }
    return
  }
  ws.onopen = () => { wsReconnectDelay = 1000; wsReconnectAttempts = 0 }
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'devices' && Array.isArray(msg.data)) {
        loadData()
      }
    } catch (e) {
      console.debug('[WS] Non-JSON message ignored:', typeof event.data === 'string' ? event.data.substring(0, 100) : event.data)
    }
  }
  ws.onerror = () => { wsReconnectDelay = Math.min(wsReconnectDelay * 2, WS_MAX_RECONNECT_DELAY) }
  ws.onclose = () => {
    if (wsManualClose) return
    wsReconnectAttempts++
    if (wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      wsReconnectTimer = setTimeout(connectWs, wsReconnectDelay)
      wsReconnectDelay = Math.min(wsReconnectDelay * 2, WS_MAX_RECONNECT_DELAY)
    }
  }
}
</script>
