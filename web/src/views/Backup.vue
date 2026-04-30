<template>
  <div>
    <n-card size="small">
      <template #header>
        <n-space align="center" size="small">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3"/></svg>
          <span style="font-weight:600">备份与恢复</span>
        </n-space>
      </template>
      <n-grid :cols="2" :x-gap="24" :y-gap="16">
        <n-gi>
          <n-card title="创建备份" size="small" :bordered="true">
            <n-p>将当前所有设备、场景、模板和审计日志导出为 JSON 备份文件。</n-p>
            <n-button type="primary" @click="handleExport" :loading="exporting">
              <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3"/></svg></template>
              导出备份
            </n-button>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card title="恢复备份" size="small" :bordered="true">
            <n-p>从 JSON 备份文件恢复数据。注意：恢复操作会覆盖现有数据。</n-p>
            <n-upload :max="1" accept=".json" :custom-request="handleImport" :show-file-list="false">
              <n-button type="warning" :loading="importing">
                <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M17 8l-5-5-5 5 M12 3v12"/></svg></template>
                选择备份文件恢复
              </n-button>
            </n-upload>
          </n-card>
        </n-gi>
      </n-grid>
    </n-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { NCard, NGrid, NGi, NButton, NP, NUpload, NSpace, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const exporting = ref(false)
const importing = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    const data = await api.exportBackup()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `protoforge_backup_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('备份已导出')
  } catch (e) {
    message.error('导出备份失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    exporting.value = false
  }
}

async function handleImport({ file }) {
  importing.value = true
  try {
    const text = await file.file.text()
    const payload = JSON.parse(text)
    if (!payload.data) {
      message.error('无效的备份文件格式')
      return
    }
    const result = await api.importBackup(payload)
    message.success(`恢复成功，恢复了 ${result.restored || 0} 项数据`)
  } catch (e) {
    message.error('恢复备份失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    importing.value = false
  }
}
</script>
