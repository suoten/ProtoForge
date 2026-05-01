<template>
  <div v-if="showWelcome" class="welcome-overlay">
    <div class="welcome-card">
      <div class="welcome-header">
        <svg viewBox="0 0 512 512" width="36" height="36">
          <defs><linearGradient id="welcomeLogoBg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="rgba(255,255,255,0.3)"/><stop offset="100%" stop-color="rgba(255,255,255,0.1)"/></linearGradient></defs>
          <rect width="512" height="512" rx="96" fill="url(#welcomeLogoBg)"/>
          <g transform="translate(256,256)" fill="none" stroke="white" stroke-width="12">
            <polygon points="0,-130 112.6,-65 112.6,65 0,130 -112.6,65 -112.6,-65" opacity="0.3"/>
            <polygon points="0,-85 73.6,-42.5 73.6,42.5 0,85 -73.6,42.5 -73.6,-42.5" opacity="0.5"/>
          </g>
          <g transform="translate(256,256)">
            <circle r="24" fill="white" opacity="0.9"/>
            <circle r="14" fill="#fbbf24"/>
          </g>
        </svg>
        <h2 style="color:white;font-size:22px;font-weight:700;margin:0">欢迎使用 ProtoForge</h2>
        <p style="color:rgba(255,255,255,0.7);font-size:13px;margin:4px 0 0">3 步快速上手物联网协议仿真</p>
      </div>
      <div class="welcome-body">
        <n-steps :current="currentStep" vertical>
          <n-step title="选择设备模板">
            <div style="margin-top:8px">
              <n-text depth="3" style="font-size:13px">从 35+ 工业设备模板中选择，一键创建仿真设备</n-text>
              <n-select v-model:value="selectedTemplate" :options="quickTemplateOptions"
                placeholder="选择一个模板..." filterable style="width:100%;margin-top:8px" />
            </div>
          </n-step>
          <n-step title="给设备起个名字">
            <div style="margin-top:8px">
              <n-input v-model:value="deviceName" placeholder="如：车间温湿度传感器" style="width:100%" />
            </div>
          </n-step>
          <n-step title="一键创建并启动">
            <div style="margin-top:8px">
              <n-button type="primary" size="large" @click="quickCreate" :loading="creating"
                :disabled="!selectedTemplate || !deviceName" block>
                <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
                一键创建设备
              </n-button>
            </div>
          </n-step>
        </n-steps>
        <n-divider />
        <n-space justify="center">
          <n-button text @click="skipWelcome" style="color:#94a3b8">跳过引导，直接使用 →</n-button>
        </n-space>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { NSpace, NText, NDivider, NSteps, NStep, NSelect, NInput, NButton, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const showWelcome = ref(false)
const currentStep = ref(1)
const selectedTemplate = ref(null)
const deviceName = ref('')
const creating = ref(false)
const templates = ref([])

const quickTemplateOptions = computed(() => {
  const popular = ['modbus_temperature_sensor', 'siemens_s7_1200', 'smart_lock', 'flow_meter',
    'mitsubishi_fx5u', 'fanuc_cnc', 'ptz_camera', 'hvac_controller']
  const popularSet = new Set(popular)
  const popularItems = templates.value
    .filter(t => popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  const otherItems = templates.value
    .filter(t => !popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  return [...popularItems, ...otherItems]
})

async function quickCreate() {
  if (!selectedTemplate.value || !deviceName.value) return
  creating.value = true
  try {
    let deviceId = deviceName.value.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
    if (!deviceId) deviceId = 'dev-' + Date.now().toString(36)
    await api.quickCreateDevice(selectedTemplate.value, deviceName.value, deviceId)
    message.success(`设备 "${deviceName.value}" 创建成功并已启动！`)
    showWelcome.value = false
    localStorage.setItem('protoforge_onboarded', '1')
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

function skipWelcome() {
  showWelcome.value = false
  localStorage.setItem('protoforge_onboarded', '1')
}

onMounted(async () => {
  if (localStorage.getItem('protoforge_onboarded')) return
  try {
    const res = await api.getTemplates()
    templates.value = res
    showWelcome.value = true
  } catch (e) { /* skip */ }
})
</script>

<style scoped>
.welcome-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
}
.welcome-card {
  width: 520px;
  background: white;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
}
.welcome-header {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  padding: 28px 32px 20px;
  text-align: center;
}
.welcome-body {
  padding: 24px 32px 28px;
}
</style>
