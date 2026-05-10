<template>
  <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:60vh">
    <svg viewBox="0 0 24 24" width="80" height="80" fill="none" stroke="#cbd5e1" stroke-width="1">
      <circle cx="12" cy="12" r="10"/>
      <path d="M12 8v4 M12 16h.01"/>
    </svg>
    <h1 style="font-size:64px;font-weight:800;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:16px 0 0">404</h1>
    <p style="font-size:16px;color:#64748b;margin:8px 0 24px">{{ t('notFound.pageNotExist') }}</p>
    <n-button type="primary" size="large" @click="$router.push('/')">
      <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M9 22V12h6v10"/></svg></template>
      {{ t('notFound.backToHome') }}
    </n-button>
  </div>
</template>

<script setup>
import { NButton } from 'naive-ui'
import { useI18n } from '../i18n.js'
const { t } = useI18n()
</script>
