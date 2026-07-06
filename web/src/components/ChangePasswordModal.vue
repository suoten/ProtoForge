<template>
  <n-modal v-model:show="visible" :title="t('password.title')" preset="card" style="width:min(420px, 90vw)" :mask-closable="false">
    <input type="text" name="username" autocomplete="username" style="position:absolute;left:-9999px;width:1px;height:1px" tabindex="-1" aria-hidden="true" />
    <input type="password" autocomplete="current-password" style="position:absolute;left:-9999px;width:1px;height:1px" tabindex="-1" aria-hidden="true" />
    <n-form ref="formRef" :model="form" :rules="rules" label-placement="top">
      <n-form-item :label="t('password.oldPassword')" path="old_password">
        <n-input v-model:value="form.old_password" type="password" :placeholder="t('password.oldPassword')" show-password-on="click" :input-props="{ autocomplete: 'off' }" />
      </n-form-item>
      <n-form-item :label="t('password.newPassword')" path="new_password">
        <n-input v-model:value="form.new_password" type="password" :placeholder="t('password.newPassword')" show-password-on="click" :input-props="{ autocomplete: 'off' }" />
      </n-form-item>
      <n-form-item :label="t('password.confirmPassword')" path="confirm_password">
        <n-input v-model:value="form.confirm_password" type="password" :placeholder="t('password.confirmPassword')" show-password-on="click" :input-props="{ autocomplete: 'off' }" />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="visible = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="loading" @click="handleSubmit">{{ t('password.submit') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { NModal, NSpace, NInput, NButton, NForm, NFormItem, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { validatePassword } from '../utils.js'

const props = defineProps({
  show: { type: Boolean, default: false },
})

const emit = defineEmits(['update:show', 'success'])

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const visible = ref(props.show)
const loading = ref(false)
const form = ref({ old_password: '', new_password: '', confirm_password: '' })
const formRef = ref(null)

const rules = computed(() => ({
  old_password: [{ required: true, message: t('password.allRequired'), trigger: 'blur' }],
  new_password: [
    { required: true, message: t('password.allRequired'), trigger: 'blur' },
    {
      validator: (rule, value) => {
        if (!value) return true
        const pwCheck = validatePassword(value)
        return pwCheck.valid
      },
      message: t('password.tooWeak'),
      trigger: 'blur'
    },
  ],
  confirm_password: [
    { required: true, message: t('password.allRequired'), trigger: 'blur' },
    {
      validator: (rule, value) => {
        return value === form.value.new_password
      },
      message: t('password.mismatch'),
      trigger: 'blur'
    },
  ],
}))

watch(() => props.show, (val) => { visible.value = val })
watch(visible, (val) => { emit('update:show', val) })

watch(() => props.show, (val) => {
  if (val) {
    form.value = { old_password: '', new_password: '', confirm_password: '' }
  }
})

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await api.changePassword(form.value.old_password, form.value.new_password)
    message.success(t('password.success'))
    visible.value = false
    dialog.info({
      title: t('password.success'),
      content: t('password.reloginRequired'),
      positiveText: t('header.logout'),
      onPositiveClick: () => {
        localStorage.removeItem('token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('username')
        localStorage.removeItem('role')
        window.location.reload()
      },
    })
    emit('success')
  } catch (e) {
    const errMsg = e.response?.data?.message || e.response?.data?.detail || t('password.failed')
    message.error(errMsg)
  } finally {
    loading.value = false
  }
}
</script>
