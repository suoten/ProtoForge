<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <svg viewBox="0 0 512 512" width="48" height="48">
          <defs><linearGradient id="loginLogoBg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="rgba(255,255,255,0.3)"/><stop offset="100%" stop-color="rgba(255,255,255,0.1)"/></linearGradient></defs>
          <rect width="512" height="512" rx="96" fill="url(#loginLogoBg)"/>
          <g transform="translate(256,256)" fill="none" stroke="white" stroke-width="12">
            <polygon points="0,-130 112.6,-65 112.6,65 0,130 -112.6,65 -112.6,-65" opacity="0.3"/>
            <polygon points="0,-85 73.6,-42.5 73.6,42.5 0,85 -73.6,42.5 -73.6,-42.5" opacity="0.5"/>
          </g>
          <g transform="translate(256,256)">
            <circle r="24" fill="white" opacity="0.9"/>
            <circle r="14" fill="#fbbf24"/>
          </g>
        </svg>
        <h1 style="color:white;font-size:24px;font-weight:700;margin:0;letter-spacing:-0.5px">ProtoForge</h1>
        <p style="color:rgba(255,255,255,0.7);font-size:13px;margin:4px 0 0">物联网协议仿真与测试平台</p>
      </div>
      <div class="login-body">
        <n-form :model="form" @keyup.enter="handleLogin">
          <n-form-item label="用户名">
            <n-input v-model:value="form.username" placeholder="请输入用户名" size="large">
              <template #prefix>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#94a3b8" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              </template>
            </n-input>
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="form.password" type="password" show-password-on="click" placeholder="请输入密码" size="large">
              <template #prefix>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#94a3b8" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              </template>
            </n-input>
          </n-form-item>
          <n-button type="primary" block size="large" @click="handleLogin" :loading="loading" style="margin-top:8px;font-weight:600">登 录</n-button>
        </n-form>
        <div class="login-hint">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#94a3b8" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4 M12 8h.01"/></svg>
          <span v-if="isDev">默认账号: admin / admin</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const loading = ref(false)
const form = ref({ username: '', password: '' })
const isDev = ref(import.meta.env.DEV)
const emit = defineEmits(['login-success'])

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await api.login(form.value.username, form.value.password)
    localStorage.setItem('token', res.access_token)
    if (res.refresh_token) {
      localStorage.setItem('refresh_token', res.refresh_token)
    }
    if (res.username) localStorage.setItem('username', res.username)
    if (res.role) localStorage.setItem('role', res.role)
    message.success('登录成功')
    emit('login-success', res)
  } catch (e) {
    message.error('登录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}
.login-card {
  width: 420px;
  background: white;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
}
.login-header {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  padding: 32px 32px 24px;
  text-align: center;
}
.login-body {
  padding: 32px;
}
.login-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 16px;
  font-size: 12px;
  color: #94a3b8;
}
</style>
