<template>
  <div>
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <div class="pf-section-title">{{ t('protocols.title') }}</div>
          <div class="pf-section-desc">{{ t('protocols.subtitle') }}</div>
        </div>
        <n-space>
          <n-button type="primary" @click="startAll" :loading="startingAll" :disabled="startingAll || stoppingAll">
            <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
            {{ t('protocols.startAll') }}
          </n-button>
          <n-button type="warning" @click="stopAll" :loading="stoppingAll" :disabled="startingAll || stoppingAll">
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

      <!-- Advanced Config Modal -->
      <n-modal v-model:show="showAdvanced" preset="card" :title="t('protocols.advancedConfigTitle', { name: advancedProtocol.display_name || advancedProtocol.name })" style="width: 500px">
        <n-alert type="info" :bordered="false" style="margin-bottom: 12px">{{ t('protocols.advancedConfigHint') }}</n-alert>
        <n-form :model="advancedConfig" label-placement="left" label-width="120">
          <n-form-item v-for="(info, key) in advancedConfigSchema" :key="key" :label="key">
            <n-input-number v-if="info.type === 'number' || info.type === 'integer'" v-model:value="advancedConfig[key]" :placeholder="String(info.default ?? '')" style="width:100%" />
            <n-input v-else v-model:value="advancedConfig[key]" :placeholder="String(info.default ?? '')" />
            <template #feedback v-if="info.description"><n-text depth="3" style="font-size:12px">{{ info.description }}</n-text></template>
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAdvanced = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="startWithConfig" :loading="starting">{{ t('common.start') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- Protocol Detail Modal -->
      <n-modal v-model:show="showInfoModal" preset="card" :title="t('protocols.protocolDetailTitle', { name: protocolInfoName })" style="width: 600px">
        <n-spin :show="loadingInfo">
          <n-space vertical v-if="protocolInfoData">
            <n-descriptions label-placement="left" :column="1" bordered size="small">
              <n-descriptions-item :label="t('common.protocolName')">{{ protocolInfoData.name || protocolInfoName }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.displayName')">{{ protocolInfoData.display_name || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.description')">{{ protocolInfoData.description || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.defaultPort')">{{ protocolInfoData.default_port || '-' }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.mode')">{{ protocolInfoData.mode || 'Server' }}</n-descriptions-item>
              <n-descriptions-item :label="t('common.version')">{{ protocolInfoData.version || '-' }}</n-descriptions-item>
            </n-descriptions>
            <n-text strong v-if="protocolInfoData.features && protocolInfoData.features.length > 0" style="font-size:13px">{{ t('common.features') }}:</n-text>
            <n-space v-if="protocolInfoData.features && protocolInfoData.features.length > 0" size="small">
              <n-tag v-for="f in protocolInfoData.features" :key="f" size="tiny" type="info" :bordered="false">{{ f }}</n-tag>
            </n-space>
            <n-text strong v-if="protocolConfigData && Object.keys(protocolConfigData).length > 0" style="font-size:13px">{{ t('common.configParams') }}:</n-text>
            <n-data-table v-if="protocolConfigData && Object.keys(protocolConfigData).length > 0"
              :columns="configInfoColumns" :data="configInfoRows" :bordered="false" size="small" />
          </n-space>
        </n-spin>
        <template #action>
          <n-button @click="showInfoModal = false">{{ t('common.close') }}</n-button>
        </template>
      </n-modal>

      <!-- Start Progress Modal -->
      <n-modal v-model:show="showProgressModal" :mask-closable="false" :close-on-esc="false" preset="card"
        :title="progressModalTitle" style="width: 520px">
        <div style="min-height: 180px">
          <!-- Single protocol start progress -->
          <template v-if="progressMode === 'single-start' || progressMode === 'single-stop'">
            <div style="text-align:center;padding: 16px 0 8px">
              <div style="font-size:15px;font-weight:500;margin-bottom:16px">
                {{ progressMode === 'single-start' ? t('protocols.startingProtocol', { name: progressTarget }) : t('protocols.stoppingProtocol', { name: progressTarget }) }}
              </div>
              <!-- Step indicators -->
              <n-space vertical size="large" style="max-width:320px;margin:0 auto;text-align:left">
                <div v-for="(step, idx) in progressSteps" :key="idx"
                  :style="{ display:'flex', alignItems:'center', gap:'12px', opacity: getStepOpacity(idx), transition: 'all 0.4s ease' }">
                  <div :style="{ width:'28px',height:'28px',borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',fontSize:'13px',fontWeight:600,transition:'all 0.4s ease',background: getStepBg(idx), color: getStepColor(idx) }">
                    <svg v-if="step.status === 'done'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                    <svg v-else-if="step.status === 'error'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    <n-spin v-else-if="step.status === 'active'" :size="14" />
                    <span v-else>{{ idx + 1 }}</span>
                  </div>
                  <span :style="{ fontSize:'14px', color: step.status === 'pending' ? '#94a3b8' : step.status === 'error' ? '#e88080' : '#334155', fontWeight: step.status === 'active' ? 600 : 400, transition: 'all 0.3s ease' }">{{ step.label }}</span>
                </div>
              </n-space>
              <!-- Error message -->
              <n-alert v-if="progressError" type="error" :bordered="false" style="margin-top:16px;text-align:left">
                {{ progressError }}
              </n-alert>
            </div>
          </template>

          <!-- Batch start/stop progress -->
          <template v-if="progressMode === 'batch-start' || progressMode === 'batch-stop'">
            <div style="margin-bottom:12px">
              <n-progress :percentage="batchPercentage" :show-indicator="true"
                :status="batchHasError ? 'warning' : 'success'"
                :height="8" :border-radius="4" />
              <div style="text-align:center;margin-top:8px;font-size:13px;color:#64748b">
                {{ progressMode === 'batch-start'
                  ? t('protocols.batchProgress', { current: batchCurrent, total: batchTotal })
                  : t('protocols.batchProgress', { current: batchCurrent, total: batchTotal }) }}
              </div>
            </div>
            <div style="max-height:240px;overflow-y:auto">
              <div v-for="item in batchItems" :key="item.name"
                :style="{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'8px 12px', borderRadius:'8px', marginBottom:'4px', background: item.status === 'active' ? '#f0f9ff' : item.status === 'success' ? '#f0fdf4' : item.status === 'error' ? '#fef2f2' : 'transparent', transition: 'all 0.3s ease' }">
                <div style="display:flex;align-items:center;gap:8px">
                  <div :style="{ width:'8px',height:'8px',borderRadius:'50%',background: item.status === 'success' ? '#18a058' : item.status === 'error' ? '#d03050' : item.status === 'active' ? '#2080f0' : '#c0c4cc', transition: 'all 0.3s ease' }">
                    <div v-if="item.status === 'active'" style="width:8px;height:8px;border-radius:50%;background:#2080f0;animation:pulse 1.5s ease-in-out infinite"></div>
                  </div>
                  <span style="font-size:13px;font-weight:500">{{ item.displayName || item.name }}</span>
                </div>
                <n-tag :type="item.status === 'success' ? 'success' : item.status === 'error' ? 'error' : item.status === 'active' ? 'info' : 'default'"
                  size="tiny" :bordered="false">
                  {{ item.status === 'success' ? t('protocols.batchItemSuccess')
                    : item.status === 'error' ? t('protocols.batchItemFailed')
                    : item.status === 'active' ? t('protocols.batchItemStarting')
                    : t('protocols.batchItemPending') }}
                </n-tag>
              </div>
            </div>
          </template>
        </div>
        <template #action>
          <n-button v-if="progressDone" type="primary" @click="closeProgressModal">{{ t('common.close') }}</n-button>
          <n-button v-else disabled>{{ t('protocols.batchItemStarting') }}</n-button>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NSpace, NGrid, NGi, NCard, NTag, NButton, NAlert, NModal, NForm, NFormItem, NInput, NInputNumber, NText, NDescriptions, NDescriptionsItem, NDataTable, NSpin, NProgress, useMessage, useDialog } from 'naive-ui'
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
const advancedConfigSchema = computed(() => {
  const schema = advancedProtocol.value.config_schema || {}
  const properties = schema.properties || {}
  return properties
})

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

// ---- Progress Modal State ----
const showProgressModal = ref(false)
const progressMode = ref('') // 'single-start' | 'single-stop' | 'batch-start' | 'batch-stop'
const progressTarget = ref('')
const progressSteps = ref([])
const progressError = ref('')
const progressDone = ref(false)

// Batch state
const batchItems = ref([])
const batchCurrent = ref(0)
const batchTotal = ref(0)
const batchHasError = ref(false)

const progressModalTitle = computed(() => {
  if (progressMode.value === 'single-start') return progressDone.value
    ? (progressError.value ? t('protocols.startErrorTitle') : t('protocols.startSuccessTitle'))
    : t('protocols.startingTitle')
  if (progressMode.value === 'single-stop') return progressDone.value
    ? (progressError.value ? t('protocols.stopErrorTitle') : t('protocols.stopSuccessTitle'))
    : t('protocols.stoppingTitle')
  if (progressMode.value === 'batch-start') return progressDone.value
    ? t('protocols.batchSuccessTitle')
    : t('protocols.batchStartingTitle')
  if (progressMode.value === 'batch-stop') return progressDone.value
    ? t('protocols.batchSuccessTitle')
    : t('protocols.batchStoppingTitle')
  return ''
})

const batchPercentage = computed(() => {
  if (batchTotal.value === 0) return 0
  return Math.round((batchCurrent.value / batchTotal.value) * 100)
})

function getStepOpacity(idx) {
  const step = progressSteps.value[idx]
  if (!step) return 0.4
  if (step.status === 'done' || step.status === 'active' || step.status === 'error') return 1
  return 0.4
}

function getStepBg(idx) {
  const step = progressSteps.value[idx]
  if (!step) return '#f1f5f9'
  if (step.status === 'done') return '#18a058'
  if (step.status === 'active') return '#2080f0'
  if (step.status === 'error') return '#d03050'
  return '#f1f5f9'
}

function getStepColor(idx) {
  const step = progressSteps.value[idx]
  if (!step) return '#94a3b8'
  if (step.status === 'done' || step.status === 'active' || step.status === 'error') return '#fff'
  return '#94a3b8'
}

function closeProgressModal() {
  showProgressModal.value = false
  progressMode.value = ''
  progressSteps.value = []
  progressError.value = ''
  progressDone.value = false
  batchItems.value = []
  batchCurrent.value = 0
  batchTotal.value = 0
  batchHasError.value = false
}

// Animate steps for single protocol start/stop
async function animateSteps(name, action) {
  const isStart = action === 'start'
  const stepLabels = isStart
    ? [t('protocols.startStepInit'), t('protocols.startStepPort'), t('protocols.startStepEngine'), t('protocols.startStepReady')]
    : [t('protocols.startStepInit'), t('protocols.startStepEngine'), t('protocols.startStepReady')]

  progressSteps.value = stepLabels.map(label => ({ label, status: 'pending' }))
  progressError.value = ''
  progressDone.value = false

  // Step 1: Init
  progressSteps.value[0].status = 'active'
  await delay(400)
  progressSteps.value[0].status = 'done'

  // Step 2: Port / Engine
  progressSteps.value[1].status = 'active'
  await delay(350)

  // Actual API call happens in parallel with step animation
  return { stepLabels }
}

async function finishStepsSuccess() {
  // Mark remaining steps as done
  for (let i = 0; i < progressSteps.value.length; i++) {
    if (progressSteps.value[i].status !== 'done') {
      progressSteps.value[i].status = 'active'
      await delay(250)
      progressSteps.value[i].status = 'done'
    }
  }
  progressDone.value = true
}

async function finishStepsError(error) {
  // Mark current active step as error, remaining as pending
  for (const step of progressSteps.value) {
    if (step.status === 'active') step.status = 'error'
    else if (step.status === 'pending') break
  }
  progressError.value = error
  progressDone.value = true
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function loadData() {
  dataLoading.value = true
  try {
    const res = await api.getProtocols()
    protocols.value = res || []
  } catch (e) {
    message.error(t('protocols.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { dataLoading.value = false }
}

// ---- Single Protocol Start with Progress ----
async function quickStart(name) {
  dialog.warning({
    title: t('protocols.confirmStart'),
    content: t('protocols.confirmStartDesc', { name }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      doStartProtocol(name, null)
    }
  })
}

async function doStartProtocol(name, config) {
  startingProtocol.value = name
  progressMode.value = 'single-start'
  progressTarget.value = name
  showProgressModal.value = true

  // Start step animation
  const stepLabels = [t('protocols.startStepInit'), t('protocols.startStepPort'), t('protocols.startStepEngine'), t('protocols.startStepReady')]
  progressSteps.value = stepLabels.map(label => ({ label, status: 'pending' }))
  progressError.value = ''
  progressDone.value = false

  // Animate step 1 (init)
  progressSteps.value[0].status = 'active'
  await delay(400)
  progressSteps.value[0].status = 'done'

  // Animate step 2 (port) - start API call in parallel
  progressSteps.value[1].status = 'active'
  const apiPromise = api.startProtocol(name, config)

  await delay(350)
  progressSteps.value[1].status = 'done'

  // Step 3 (engine) - wait for API
  progressSteps.value[2].status = 'active'

  try {
    const res = await apiPromise
    progressSteps.value[2].status = 'done'

    // Step 4 (ready)
    progressSteps.value[3].status = 'active'
    await delay(300)
    progressSteps.value[3].status = 'done'
    progressDone.value = true

    if (res.port_changed) {
      message.warning(res.message, { duration: 6000 })
    }
    await loadData()
  } catch (e) {
    const errMsg = e.response?.data?.detail || e.message
    progressSteps.value[2].status = 'error'
    progressError.value = t('protocols.startErrorDesc', { name, error: errMsg })
    progressDone.value = true
  } finally {
    startingProtocol.value = null
  }
}

// ---- Single Protocol Stop with Progress ----
async function stopProtocol(name) {
  dialog.warning({
    title: t('protocols.confirmStop'),
    content: t('protocols.confirmStopDesc', { name }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      doStopProtocol(name)
    }
  })
}

async function doStopProtocol(name) {
  stoppingProtocol.value = name
  progressMode.value = 'single-stop'
  progressTarget.value = name
  showProgressModal.value = true

  const stepLabels = [t('protocols.startStepInit'), t('protocols.startStepEngine'), t('protocols.startStepReady')]
  progressSteps.value = stepLabels.map(label => ({ label, status: 'pending' }))
  progressError.value = ''
  progressDone.value = false

  progressSteps.value[0].status = 'active'
  await delay(300)
  progressSteps.value[0].status = 'done'

  progressSteps.value[1].status = 'active'
  try {
    await api.stopProtocol(name)
    progressSteps.value[1].status = 'done'

    progressSteps.value[2].status = 'active'
    await delay(250)
    progressSteps.value[2].status = 'done'
    progressDone.value = true

    await loadData()
  } catch (e) {
    const errMsg = e.response?.data?.detail || e.message
    progressSteps.value[1].status = 'error'
    progressError.value = t('protocols.stopErrorDesc', { name, error: errMsg })
    progressDone.value = true
  } finally {
    stoppingProtocol.value = null
  }
}

// ---- Batch Start with Progress ----
async function startAll() {
  const stopped = protocols.value.filter(p => p.status !== 'running')
  if (!stopped.length) { message.info(t('protocols.allRunning')); return }
  dialog.warning({
    title: t('protocols.confirmStartAll'),
    content: t('protocols.confirmStartAllDesc', { count: stopped.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      doStartAll(stopped)
    }
  })
}

async function doStartAll(stopped) {
  startingAll.value = true
  progressMode.value = 'batch-start'
  batchTotal.value = stopped.length
  batchCurrent.value = 0
  batchHasError.value = false
  batchItems.value = stopped.map(p => ({
    name: p.name,
    displayName: p.display_name || p.name,
    status: 'pending'
  }))
  showProgressModal.value = true
  progressDone.value = false

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < stopped.length; i++) {
    const p = stopped[i]
    batchItems.value[i].status = 'active'
    batchCurrent.value = i + 1

    try {
      await api.startProtocol(p.name, null)
      batchItems.value[i].status = 'success'
      successCount++
    } catch (e) {
      batchItems.value[i].status = 'error'
      failCount++
      batchHasError.value = true
    }

    // Small delay between protocols for visual effect
    if (i < stopped.length - 1) await delay(200)
  }

  progressDone.value = true
  startingAll.value = false

  if (failCount > 0 && successCount > 0) {
    message.warning(t('protocols.batchPartialDesc', { success: successCount, fail: failCount }))
  } else if (successCount > 0) {
    message.success(t('protocols.batchSuccessDesc', { success: successCount }))
  }

  await loadData()
}

// ---- Batch Stop with Progress ----
async function stopAll() {
  const running = protocols.value.filter(p => p.status === 'running')
  if (!running.length) { message.info(t('protocols.allStopped')); return }
  dialog.warning({
    title: t('protocols.confirmStopAll'),
    content: t('protocols.confirmStopAllDesc', { count: running.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      doStopAll(running)
    }
  })
}

async function doStopAll(running) {
  stoppingAll.value = true
  progressMode.value = 'batch-stop'
  batchTotal.value = running.length
  batchCurrent.value = 0
  batchHasError.value = false
  batchItems.value = running.map(p => ({
    name: p.name,
    displayName: p.display_name || p.name,
    status: 'pending'
  }))
  showProgressModal.value = true
  progressDone.value = false

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < running.length; i++) {
    const p = running[i]
    batchItems.value[i].status = 'active'
    batchCurrent.value = i + 1

    try {
      await api.stopProtocol(p.name)
      batchItems.value[i].status = 'success'
      successCount++
    } catch (e) {
      batchItems.value[i].status = 'error'
      failCount++
      batchHasError.value = true
    }

    if (i < running.length - 1) await delay(200)
  }

  progressDone.value = true
  stoppingAll.value = false

  if (failCount > 0 && successCount > 0) {
    message.warning(t('protocols.stopAllPartial', { success: successCount, fail: failCount }))
  } else if (successCount > 0) {
    message.success(t('protocols.stopAllSuccess', { count: successCount }))
  }

  await loadData()
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
    protocolConfigData.value = configRes.properties || configRes.config_schema?.properties || (Object.keys(configRes).length > 0 ? configRes : {})
  } catch (e) {
    protocolInfoData.value = protocols.value.find(p => p.name === name) || { name }
    protocolConfigData.value = {}
  } finally { loadingInfo.value = false }
}

function openAdvanced(p) {
  advancedProtocol.value = p
  try {
    const schema = p.config_schema || {}
    const properties = schema.properties || schema
    advancedConfig.value = {}
    for (const [key, info] of Object.entries(properties)) {
      if (info !== null && info !== undefined && typeof info === 'object' && info.type) {
        advancedConfig.value[key] = info.default ?? ''
      }
    }
  } catch (e) {
    advancedConfig.value = {}
  }
  showAdvanced.value = true
}

async function startWithConfig() {
  starting.value = true
  try {
    const config = {}
    for (const [key, value] of Object.entries(advancedConfig.value)) {
      if (value !== '' && value !== null && value !== undefined) {
        config[key] = (String(value).trim() !== '' && !isNaN(Number(value))) ? Number(value) : value
      }
    }
    showAdvanced.value = false
    await doStartProtocol(advancedProtocol.value.name, config)
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
        if (wsLoadDataTimer) clearTimeout(wsLoadDataTimer)
        wsLoadDataTimer = setTimeout(() => { loadData() }, 300)
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

<style scoped>
@keyframes pulse {
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
  100% { opacity: 1; transform: scale(1); }
}
</style>
