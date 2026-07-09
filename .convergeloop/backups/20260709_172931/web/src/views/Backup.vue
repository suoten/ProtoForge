<template>
  <div>
    <n-card size="small">
      <template #header>
        <n-space align="center" size="small">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3"/></svg>
          <span style="font-weight:600">{{ t('backup.title') }}</span>
        </n-space>
      </template>
      <n-grid :cols="2" :x-gap="24" :y-gap="16">
        <n-gi>
          <n-card :title="t('backup.createBackup')" size="small" :bordered="true">
            <n-p>{{ t('backup.createBackupDesc') }}</n-p>
            <n-button type="primary" @click="handleExport" :loading="exporting">
              <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3"/></svg></template>
              {{ t('backup.exportBackup') }}
            </n-button>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card :title="t('backup.restoreBackup')" size="small" :bordered="true">
            <n-p>{{ t('backup.restoreBackupDesc') }}</n-p>
            <n-upload :max="1" accept=".json" :custom-request="handleImport" :show-file-list="false">
              <n-button type="warning" :loading="importing">
                <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M17 8l-5-5-5 5 M12 3v12"/></svg></template>
                {{ t('backup.selectFile') }}
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
import { NCard, NGrid, NGi, NButton, NP, NUpload, NSpace, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
const exporting = ref(false)
const importing = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    const result = await api.exportBackup()
    if (result && result.downloaded) {
      message.success(t('backup.exportSuccess'))
    } else {
      const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `protoforge_backup_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      message.success(t('backup.exportSuccess'))
    }
  } catch (e) {
    message.error(t('backup.exportFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    exporting.value = false
  }
}

async function handleImport({ file }) {
  try {
    const text = await file.file.text()
    const payload = JSON.parse(text)
    if (!payload || typeof payload !== 'object') {
      message.error(t('backup.invalidFormat'))
      return
    }
    if (!payload.data) {
      message.error(t('backup.missingDataField'))
      return
    }
    if (!payload.version) {
      message.warning(t('backup.missingVersion'))
    }
    dialog.warning({
      title: t('backup.confirmRestore'),
      content: t('backup.confirmRestoreWarning'),
      positiveText: t('backup.restoreBackup'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        importing.value = true
        try {
          const result = await api.importBackup(payload)
          message.success(t('backup.restoreSuccess', { n: result.restored || 0 }))
          setTimeout(() => { window.location.reload() }, 1500)
        } catch (e) {
          message.error(t('backup.restoreFailed') + ': ' + (e.response?.data?.detail || e.message))
        } finally { importing.value = false }
      }
    })
  } catch (e) {
    message.error(t('backup.readFileFailed') + ': ' + e.message)
  }
}
</script>
