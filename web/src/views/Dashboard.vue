<template>
  <div>
    <n-spin :show="loading">
      <n-space vertical size="large">

        <n-grid :cols="4" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card class="pf-gradient-card" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">设备总数</div>
                  <div class="pf-stat-value">{{ devices.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ onlineDevices }} 在线</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-green" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">运行中协议</div>
                  <div class="pf-stat-value">{{ runningProtocols }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">共 {{ protocols.length }} 个协议</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-orange" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">仿真场景</div>
                  <div class="pf-stat-value">{{ scenarios.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">{{ runningScenarios }} 运行中</div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card class="pf-gradient-card-rose" size="small">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <div style="font-size:12px;opacity:0.8;font-weight:500">设备模板</div>
                  <div class="pf-stat-value">{{ templates.length }}</div>
                </div>
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
              </div>
              <div style="margin-top:8px;font-size:11px;opacity:0.7">覆盖 {{ Object.keys(protocolLabels).length }} 种协议</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-grid :cols="2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                  <span class="pf-section-title" style="font-size:16px">快速操作</span>
                </n-space>
              </template>
              <n-space vertical size="small">
                <n-button type="primary" block size="large" @click="startAllProtocols">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
                  启动全部协议
                </n-button>
                <n-button block size="large" @click="$router.push('/marketplace')">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></template>
                  从模板创建设备
                </n-button>
                <n-button block size="large" @click="$router.push('/testing')">
                  <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></template>
                  一键仿真测试
                </n-button>
              </n-space>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8"/></svg>
                  <span class="pf-section-title" style="font-size:16px">最近日志</span>
                </n-space>
              </template>
              <n-space vertical size="small" style="max-height:200px;overflow-y:auto">
                <div v-for="log in recentLogs.slice(0, 8)" :key="log.timestamp"
                  style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f1f5f9">
                  <div :style="{ width:'6px',height:'6px',borderRadius:'50%',background: directionColorMap[log.direction]||'#94a3b8',flexShrink:0 }"></div>
                <span style="font-size:11px;color:#94a3b8;min-width:60px">{{ formatTime(log.timestamp) }}</span>
                <n-tag size="tiny" :type="directionTagTypeMap[log.direction]||'default'" :bordered="false">{{ log.protocol }}</n-tag>
                  <span style="font-size:12px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ log.summary }}</span>
                </div>
                <n-text v-if="!recentLogs.length" depth="3" style="font-size:12px">暂无日志</n-text>
              </n-space>
            </n-card>
          </n-gi>
        </n-grid>

        <n-alert v-if="loadError" type="error" style="margin-bottom:12px">
          数据加载失败: {{ loadError }}
          <n-button size="tiny" @click="loadData" style="margin-left:8px">重试</n-button>
        </n-alert>

        <n-card v-if="devices.length === 0 && !loading" size="small">
          <n-space vertical align="center" style="padding:32px 0">
            <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <div class="pf-section-title" style="font-size:16px">还没有仿真设备</div>
            <div class="pf-section-desc">3 步快速开始：选择模板 → 命名 → 一键创建</div>
            <n-button type="primary" @click="$router.push('/marketplace')">前往模板市场</n-button>
          </n-space>
        </n-card>

        <n-card v-else-if="devices.length > 0" size="small">
          <template #header>
            <n-space align="center" size="small">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              <span class="pf-section-title" style="font-size:16px">设备概览</span>
            </n-space>
          </template>
          <n-data-table :columns="deviceColumns" :data="devices.slice(0, 10)" :bordered="false" size="small"
            :pagination="devices.length > 10 ? { pageSize: 10 } : false" />
        </n-card>

      </n-space>
    </n-spin>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NGrid, NGi, NCard, NSpace, NButton, NDataTable, NTag, NText, NSpin, NAlert, useMessage } from 'naive-ui'
import api from '../api.js'
import { protocolLabels, deviceStatusMap, directionColorMap, directionTagTypeMap } from '../constants.js'

const message = useMessage()
const devices = ref([])
const protocols = ref([])
const templates = ref([])
const scenarios = ref([])
const recentLogs = ref([])
const loading = ref(true)
const loadError = ref('')

const onlineDevices = computed(() => devices.value.filter(d => d.status === 'online' || d.status === 'running').length)
const runningProtocols = computed(() => protocols.value.filter(p => p.status === 'running').length)
const runningScenarios = computed(() => scenarios.value.filter(s => s.status === 'running').length)

const deviceColumns = [
  { title: '设备', key: 'name', width: 160, render: (row) => h('span', { style: 'font-weight:500' }, row.name || row.id) },
  { title: '协议', key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => protocolLabels[row.protocol] || row.protocol) },
  {
    title: '状态', key: 'status', width: 100,
    render: (row) => {
      const [type, label] = deviceStatusMap[row.status] || ['default', row.status || '离线']
      return h(NTag, { size: 'tiny', type, bordered: false }, () => label)
    }
  },
  { title: '测点数', key: 'points', width: 80, render: (row) => row.point_count || (row.points || []).length },
]

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString()
}

async function startAllProtocols() {
  const stopped = protocols.value.filter(p => p.status !== 'running')
  if (!stopped.length) { message.info('所有协议已在运行中'); return }
  let failCount = 0
  for (const p of stopped) {
    try { await api.startProtocol(p.name, null) } catch (e) { failCount++ }
  }
  if (failCount > 0) {
    message.warning(`已启动 ${stopped.length - failCount} 个协议，${failCount} 个启动失败`)
  } else {
    message.success(`已启动 ${stopped.length} 个协议`)
  }
  await loadData()
}

async function loadData() {
  loading.value = true
  loadError.value = ''
  try {
    const [devRes, protoRes, tmplRes, scRes, logRes] = await Promise.all([
      api.getDevices(), api.getProtocols(), api.getTemplates(), api.getScenarios(), api.getLogs({ count: 50 }),
    ])
    devices.value = devRes
    protocols.value = protoRes
    templates.value = tmplRes
    scenarios.value = scRes
    recentLogs.value = Array.isArray(logRes) ? logRes : (logRes.logs || logRes.entries || [])
  } catch (e) {
    loadError.value = e.response?.data?.detail || e.message || '未知错误'
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
