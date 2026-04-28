<template>
  <div>
    <n-space vertical size="large">
      <div>
        <div class="pf-section-title">系统设置</div>
        <div class="pf-section-desc">修改端口和配置后，重启对应协议服务即可生效</div>
      </div>

      <n-card title="服务器配置" size="small">
        <n-form :model="serverConfig" label-placement="left" label-width="120">
          <n-form-item label="监听地址">
            <n-input v-model:value="serverConfig.host" placeholder="0.0.0.0" />
          </n-form-item>
          <n-form-item label="Web端口">
            <n-input-number v-model:value="serverConfig.port" :min="1" :max="65535" style="width:100%" />
            <n-text depth="3" style="margin-left:8px;font-size:12px">重启服务后生效</n-text>
          </n-form-item>
          <n-form-item label="数据库路径">
            <n-input v-model:value="serverConfig.db_path" placeholder="data/protoforge.db 或 postgresql://user:pass@host:5432/db" />
          </n-form-item>
          <n-form-item label="日志级别">
            <n-select v-model:value="serverConfig.log_level" :options="logLevelOptions" style="width:200px" />
          </n-form-item>
          <n-form-item label="CORS源">
            <n-input v-model:value="serverConfig.cors_origins" placeholder="* 或 https://example.com" />
            <n-text depth="3" style="margin-left:8px;font-size:12px">多个用逗号分隔</n-text>
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="InfluxDB 转发配置（可选）" size="small">
        <n-form :model="influxdbConfig" label-placement="left" label-width="120">
          <n-form-item label="URL">
            <n-input v-model:value="influxdbConfig.url" placeholder="http://localhost:8086" />
          </n-form-item>
          <n-form-item label="Token">
            <n-input v-model:value="influxdbConfig.token" type="password" show-password-on="click" placeholder="InfluxDB API Token" />
          </n-form-item>
          <n-form-item label="组织">
            <n-input v-model:value="influxdbConfig.org" placeholder="default" />
          </n-form-item>
          <n-form-item label="Bucket">
            <n-input v-model:value="influxdbConfig.bucket" placeholder="protoforge" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="协议端口配置" size="small">
        <template #header-extra>
          <n-text depth="3" style="font-size:12px">修改后需重启对应协议</n-text>
        </template>
        <n-grid :cols="2" :x-gap="16" :y-gap="8">
          <n-gi v-for="item in protocolPortList" :key="item.key">
            <n-form-item :label="item.label" label-placement="left" :show-feedback="false" style="margin-bottom:4px">
              <n-input-number
                v-model:value="protocolPorts[item.key]"
                :min="1" :max="65535"
                :placeholder="String(item.default)"
                style="width:140px"
                size="small"
              />
              <n-tag size="tiny" :bordered="false" :type="item.running ? 'success' : 'default'" style="margin-left:8px">
                {{ item.running ? '运行中' : '已停止' }}
              </n-tag>
            </n-form-item>
          </n-gi>
        </n-grid>
      </n-card>

      <n-space>
        <n-button type="primary" @click="saveSettings" :loading="saving">
          <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg></template>
          保存配置
        </n-button>
        <n-button tertiary @click="loadSettings">重置</n-button>
      </n-space>

      <n-alert v-if="saveResult" :type="hasChanges ? 'success' : 'info'" :bordered="false">
        {{ saveResult }}
      </n-alert>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { NSpace, NCard, NForm, NFormItem, NInput, NInputNumber, NButton, NGrid, NGi, NTag, NText, NAlert, NSelect, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const saving = ref(false)
const saveResult = ref('')
const hasChanges = ref(false)

const serverConfig = ref({ host: '0.0.0.0', port: 8000, db_path: 'data/protoforge.db', log_level: 'info', cors_origins: '*' })
const influxdbConfig = ref({ url: '', token: '', org: 'default', bucket: 'protoforge' })
const protocolPorts = ref({})
const protocols = ref([])

const logLevelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
]

const protocolLabels = {
  modbus_tcp: 'Modbus TCP', modbus_rtu: 'Modbus RTU', opcua: 'OPC-UA', mqtt: 'MQTT',
  http: 'HTTP', gb28181: 'GB28181', bacnet: 'BACnet', s7: 'S7',
  mc: 'Mitsubishi MC', fins: 'Omron FINS', ab: 'Rockwell AB', opcda: 'OPC-DA',
  fanuc: 'FANUC FOCAS', mtconnect: 'MTConnect', toledo: 'Mettler-Toledo',
}

const defaultPorts = {
  modbus_tcp: 5020, modbus_rtu: 0, opcua: 4840, mqtt: 1883,
  http: 8080, gb28181: 5060, bacnet: 47808, s7: 102,
  mc: 5000, fins: 9600, ab: 44818, opcda: 51340,
  fanuc: 8193, mtconnect: 7878, toledo: 1701,
}

const protocolPortList = computed(() => {
  return Object.keys(protocolLabels).map(key => ({
    key,
    label: protocolLabels[key],
    default: defaultPorts[key],
    running: protocols.value.find(p => p.name === key)?.status === 'running',
  }))
})

async function loadSettings() {
  try {
    const [settings, protoRes] = await Promise.all([api.getSettings(), api.getProtocols()])
    serverConfig.value.host = settings.host || '0.0.0.0'
    serverConfig.value.port = settings.port || 8000
    serverConfig.value.db_path = settings.db_path || 'data/protoforge.db'
    serverConfig.value.log_level = settings.log_level || 'info'
    serverConfig.value.cors_origins = settings.cors_origins || '*'
    influxdbConfig.value.url = settings.influxdb_url || ''
    influxdbConfig.value.token = settings.influxdb_token || ''
    influxdbConfig.value.org = settings.influxdb_org || 'default'
    influxdbConfig.value.bucket = settings.influxdb_bucket || 'protoforge'
    protocolPorts.value = { ...(settings.protocol_ports || {}) }
    protocols.value = protoRes
    saveResult.value = ''
  } catch (e) {
    message.error('加载设置失败')
  }
}

async function saveSettings() {
  saving.value = true
  saveResult.value = ''
  try {
    const updates = {
      host: serverConfig.value.host,
      port: serverConfig.value.port,
      db_path: serverConfig.value.db_path,
      log_level: serverConfig.value.log_level,
      cors_origins: serverConfig.value.cors_origins,
      influxdb_url: influxdbConfig.value.url,
      influxdb_token: influxdbConfig.value.token,
      influxdb_org: influxdbConfig.value.org,
      influxdb_bucket: influxdbConfig.value.bucket,
    }
    for (const [key, value] of Object.entries(protocolPorts.value)) {
      updates[`${key}_port`] = value
    }
    const result = await api.updateSettings(updates)
    hasChanges.value = Object.keys(result.changed || {}).length > 0
    if (hasChanges.value) {
      const changedNames = Object.keys(result.changed).map(k => {
        if (k.endsWith('_port')) {
          const protoKey = k.slice(0, -5)
          return protocolLabels[protoKey] || protoKey
        }
        return k
      })
      saveResult.value = `已保存并更新: ${changedNames.join(', ')}。协议端口修改需重启对应协议生效，Web端口需重启服务生效。`
    } else {
      saveResult.value = '配置已保存，无变更'
    }
    message.success('设置已保存')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>
