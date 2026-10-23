<template>
  <n-modal :show="show" preset="card" title="点表导入向导" style="width:min(860px, 94vw)" @update:show="v => $emit('update:show', v)">
    <n-space vertical size="large">
      <n-alert type="info" :bordered="false">
        <div style="font-size:13px; line-height:1.7">
          粘贴或上传客户点表（Excel / CSV / TSV），自动识别<b>厂商地址风格</b>（西门子 DB 块、三菱
          D/X/Y、欧姆龙 CIO/W/DM、Modbus 4xxxx、DL/T 645 数据标识、IEC 104 IOA…），
          校验与目标协议的兼容性并标出地址冲突，预览确认后一键建设备。
          表头支持中英文（点名/地址/数据类型/单位/读写/描述）。
        </div>
      </n-alert>

      <n-grid :cols="4" :x-gap="12">
        <n-gi :span="1">
          <n-form-item label="目标协议" size="small" :show-feedback="false">
            <n-select v-model:value="protocol" :options="protocolOptions" filterable />
          </n-form-item>
        </n-gi>
        <n-gi :span="1">
          <n-form-item label="设备 ID（留空自动）" size="small" :show-feedback="false">
            <n-input v-model:value="deviceId" placeholder="imported-..." />
          </n-form-item>
        </n-gi>
        <n-gi :span="1">
          <n-form-item label="设备名（留空自动）" size="small" :show-feedback="false">
            <n-input v-model:value="deviceName" placeholder="导入点表-..." />
          </n-form-item>
        </n-gi>
        <n-gi :span="1">
          <n-form-item label="地址风格（留空自动识别）" size="small" :show-feedback="false">
            <n-select v-model:value="styleHint" :options="styleOptions" clearable />
          </n-form-item>
        </n-gi>
      </n-grid>

      <n-space align="center">
        <n-upload :show-file-list="false" accept=".csv,.txt,.tsv,.xlsx" @change="handleFileUpload">
          <n-button size="small">选择文件（CSV / XLSX）</n-button>
        </n-upload>
        <span style="font-size:12px;color:#999">或直接粘贴到下方文本框</span>
      </n-space>

      <n-input v-model:value="content" type="textarea" :rows="8"
               placeholder="粘贴点表内容，例如：&#10;位号,地址,数据类型,单位,读写&#10;reactor_temp,DB1.DBD0,float32,℃,rw&#10;pump_run,M0.0,bool,,rw" />

      <n-space align="center">
        <n-button type="primary" size="small" :loading="previewing" :disabled="!content.trim()"
                  @click="doPreview">
          解析预览
        </n-button>
        <n-button size="small" :disabled="!previewOk || importing" :loading="importing" type="success"
                  @click="doImport">
          确认导入（{{ preview ? preview.total_points : 0 }} 点）
        </n-button>
        <span v-if="preview" style="font-size:12px;color:#666">
          识别风格:
          <n-tag v-for="(c, s) in preview.style_counts" :key="s" size="small" style="margin-right:4px">
            {{ styleLabel(s) }} × {{ c }}
          </n-tag>
        </span>
      </n-space>

      <template v-if="preview">
        <n-alert v-if="preview.errors && preview.errors.length" type="error" :bordered="false">
          <div v-for="(e, i) in preview.errors" :key="i" style="font-size:13px">{{ e }}</div>
        </n-alert>
        <n-alert v-if="preview.conflicts && preview.conflicts.length" type="error" :bordered="false">
          <b>地址冲突（需处理后才能导入）：</b>
          <div v-for="(c, i) in preview.conflicts" :key="i" style="font-size:13px">{{ c }}</div>
        </n-alert>
        <n-alert v-if="preview.warnings && preview.warnings.length" type="warning" :bordered="false">
          <div v-for="(w, i) in preview.warnings.slice(0, 8)" :key="i" style="font-size:13px">{{ w }}</div>
          <div v-if="preview.warnings.length > 8" style="font-size:12px;color:#999">
            …共 {{ preview.warnings.length }} 条提示
          </div>
        </n-alert>

        <n-data-table size="small" :columns="pointColumns" :data="preview.points || []"
                      :max-height="260" :row-key="r => r.row" />
      </template>
    </n-space>
  </n-modal>
</template>

<script setup>
import { ref, computed } from 'vue'
import { NModal, NSpace, NAlert, NButton, NInput, NSelect, NUpload, NGrid, NGi,
         NFormItem, NDataTable, NTag, useMessage } from 'naive-ui'
import api from '../api.js'
import { protocolLabels } from '../constants.js'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show', 'imported'])

const message = useMessage()
const protocol = ref('modbus_tcp')
const deviceId = ref('')
const deviceName = ref('')
const styleHint = ref(null)
const content = ref('')
const previewing = ref(false)
const importing = ref(false)
const preview = ref(null)

const protocolOptions = computed(() =>
  Object.entries(protocolLabels || {}).map(([v, label]) => ({ label: label || v, value: v })))

const styleOptions = [
  { label: '西门子 DB 块', value: 'siemens_db' },
  { label: '西门子 M 区', value: 'siemens_m' },
  { label: '西门子 I 区', value: 'siemens_i' },
  { label: '西门子 Q 区', value: 'siemens_q' },
  { label: '三菱 D/R/ZR', value: 'mitsubishi_dwr' },
  { label: '三菱 X/Y', value: 'mitsubishi_xy' },
  { label: '欧姆龙 CIO', value: 'omron_cio' },
  { label: '欧姆龙 W/HR', value: 'omron_w' },
  { label: '欧姆龙 DM', value: 'omron_dm' },
  { label: 'DL/T 645 数据标识', value: 'dlt645_di' },
  { label: 'Modbus 前缀 (4x0001)', value: 'modbus_prefix' },
  { label: 'Modbus 5 位编址', value: 'modbus_5digit' },
  { label: 'Modbus 6 位编址', value: 'modbus_6digit' },
  { label: 'IEC 104 IOA', value: 'iec104_ioa' },
]

function styleLabel(s) {
  const hit = styleOptions.find(o => o.value === s)
  return hit ? hit.label : s
}

const previewOk = computed(() => !!(preview.value && preview.value.ok))

const pointColumns = [
  { title: '行', key: 'row', width: 52 },
  { title: '点名', key: 'name', width: 150 },
  { title: '地址', key: 'address', width: 140 },
  { title: '类型', key: 'data_type', width: 90 },
  { title: '单位', key: 'unit', width: 80 },
  { title: '读写', key: 'access', width: 60 },
  { title: '风格', key: 'style', width: 130 },
  {
    title: '提示', key: 'warnings',
    render(row) {
      if (!row.warnings || !row.warnings.length) return ''
      return h('span', { style: 'color:#d97706; font-size:12px' }, row.warnings.join('; '))
    },
  },
]

import { h } from 'vue'

async function doPreview() {
  previewing.value = true
  preview.value = null
  try {
    preview.value = await api.importPointTable({
      content: content.value,
      file_format: isBase64.value ? 'excel' : 'csv',
      protocol: protocol.value,
      device_id: deviceId.value,
      device_name: deviceName.value,
      style_hint: styleHint.value || '',
      dry_run: true,
    })
  } catch (e) {
    message.error('解析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    previewing.value = false
  }
}

const isBase64 = ref(false)

async function doImport() {
  importing.value = true
  try {
    const res = await api.importPointTable({
      content: content.value,
      file_format: isBase64.value ? 'excel' : 'csv',
      protocol: protocol.value,
      device_id: deviceId.value,
      device_name: deviceName.value,
      style_hint: styleHint.value || '',
      dry_run: false,
    })
    message.success(`已创建设备 ${res.device_id}（${res.total_points} 点）`)
    emit('imported')
    emit('update:show', false)
    preview.value = null
    content.value = ''
  } catch (e) {
    const detail = e.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.points) {
      preview.value = detail  // 422 带回完整预览：直接展示冲突
    }
    message.error('导入被拒绝：请检查冲突与错误')
  } finally {
    importing.value = false
  }
}

function handleFileUpload({ file }) {
  const f = file?.file
  if (!f) return
  const name = (f.name || '').toLowerCase()
  if (name.endsWith('.xlsx')) {
    const reader = new FileReader()
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result)
      let bin = ''
      const CHUNK = 0x8000
      for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK))
      }
      content.value = btoa(bin)
      isBase64.value = true
    }
    reader.readAsArrayBuffer(f)
  } else {
    const reader = new FileReader()
    reader.onload = () => {
      content.value = String(reader.result || '')
      isBase64.value = false
    }
    reader.readAsText(f, 'utf-8')
  }
}
</script>
