<template>
  <div class="pf-empty-state">
    <div class="pf-empty-icon">
      <slot name="icon">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5">
          <path :d="iconPath" />
        </svg>
      </slot>
    </div>
    <h3 class="pf-empty-title">{{ title }}</h3>
    <p v-if="description" class="pf-empty-desc">{{ description }}</p>
    <n-button v-if="actionText" type="primary" @click="$emit('action')" style="margin-top:12px">
      <template v-if="actionIcon" #icon>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="actionIcon" />
        </svg>
      </template>
      {{ actionText }}
    </n-button>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  actionText: { type: String, default: '' },
  actionIcon: { type: String, default: '' },
  iconPath: { type: String, default: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },
})

defineEmits(['action'])
</script>

<style scoped>
.pf-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.pf-empty-icon {
  margin-bottom: 16px;
}

.pf-empty-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
  letter-spacing: -0.3px;
}

.pf-empty-desc {
  font-size: 13px;
  color: #94a3b8;
  margin: 4px 0 0;
  max-width: 360px;
  line-height: 1.5;
}
</style>
