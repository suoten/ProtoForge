<template>
  <div>
    <n-h2 style="margin-bottom: 4px">系统设置</n-h2>
    <n-text depth="3" style="font-size: 13px">管理系统配置、用户账户和演示数据</n-text>

    <n-tabs type="line" animated style="margin-top: 20px">
      <n-tab-pane name="general" tab="通用设置">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item label="服务端口">
              <n-input-number v-model:value="form.port" :min="1" :max="65535" style="width: 200px" />
            </n-form-item>
            <n-form-item label="日志级别">
              <n-select v-model:value="form.log_level" :options="logLevelOptions" style="width: 200px" />
            </n-form-item>
            <n-form-item label="CORS 来源">
              <n-input v-model:value="form.cors_origins" placeholder="* 或 https://example.com" />
            </n-form-item>
            <n-form-item label="演示模式">
              <n-switch v-model:value="form.demo_mode" />
            </n-form-item>
            <n-form-item>
              <n-space>
                <n-button type="primary" :loading="saveLoading" @click="saveSettings">保存设置</n-button>
              </n-space>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="integration" tab="集成配置">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item label="EdgeLite URL">
              <n-input v-model:value="form.edgelite_url" placeholder="http://edgelite:8080" />
            </n-form-item>
            <n-form-item label="EdgeLite 用户名">
              <n-input v-model:value="form.edgelite_username" />
            </n-form-item>
            <n-form-item label="EdgeLite 密码">
              <n-input v-model:value="form.edgelite_password" type="password" show-password-on="click" :placeholder="form.edgelite_password ? PASSWORD_MASK : ''" />
            </n-form-item>
            <n-form-item>
              <n-space>
                <n-button type="primary" :loading="saveLoading" @click="saveSettings">保存设置</n-button>
                <n-button :loading="testEdgeLiteLoading" @click="testEdgeLiteConnection">测试连接</n-button>
              </n-space>
            </n-form-item>
            <n-alert v-if="testEdgeLiteResult" :type="testEdgeLiteResult.ok ? 'success' : 'error'" :bordered="false" style="margin-bottom:12px">
              <template v-if="testEdgeLiteResult.ok">
                连接成功！EdgeLite 版本: {{ testEdgeLiteResult.version || '未知' }}，设备总数: {{ testEdgeLiteResult.devices || 0 }}
              </template>
              <template v-else>
                连接失败: {{ testEdgeLiteResult.error }}
              </template>
            </n-alert>
          </n-form>
          <n-divider style="max-width: 600px" />
          <n-form label-placement="left" label-width="140" style="max-width: 600px">
            <n-form-item label="InfluxDB URL">
              <n-input v-model:value="form.influxdb_url" placeholder="http://influxdb:8086" />
            </n-form-item>
            <n-form-item label="InfluxDB Token">
              <n-input v-model:value="form.influxdb_token" type="password" show-password-on="click" :placeholder="form.influxdb_token ? PASSWORD_MASK : ''" />
            </n-form-item>
            <n-form-item label="InfluxDB 组织">
              <n-input v-model:value="form.influxdb_org" />
            </n-form-item>
            <n-form-item label="InfluxDB Bucket">
              <n-input v-model:value="form.influxdb_bucket" />
            </n-form-item>
            <n-form-item label="公网地址">
              <n-input v-model:value="form.protoforge_public_host" placeholder="用于EdgeLite回调，如 http://1.2.3.4:8000" />
            </n-form-item>
            <n-form-item>
              <n-button type="primary" :loading="saveLoading" @click="saveSettings">保存设置</n-button>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="ports" tab="协议端口">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item v-for="(port, key) in form.protocol_ports" :key="key" :label="getProtocolLabel(key)">
              <n-input v-if="key === 'modbus_rtu'" v-model:value="form.protocol_ports[key]" />
              <n-input-number v-else v-model:value="form.protocol_ports[key]" :min="1" :max="65535" style="width: 200px" />
            </n-form-item>
            <n-form-item>
              <n-button type="primary" :loading="saveLoading" @click="saveSettings">保存设置</n-button>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="users" tab="用户管理">
        <n-space style="margin: 16px 0">
          <n-button type="primary" @click="openAddUser">添加用户</n-button>
          <n-button @click="openChangePassword">修改密码</n-button>
        </n-space>
        <n-data-table :columns="userColumns" :data="users" :bordered="false" size="small" />
      </n-tab-pane>

      <n-tab-pane name="demo" tab="演示数据">
        <n-spin :show="setupLoading">
          <n-space vertical style="margin-top: 16px">
            <n-card size="small">
              <n-space align="center" justify="space-between">
                <div>
                  <n-text strong>系统状态</n-text>
                  <n-text depth="3" style="margin-left: 8px">设备: {{ setupStatus.device_count || 0 }} | 场景: {{ setupStatus.scenario_count || 0 }} | 运行协议: {{ setupStatus.protocols_running || 0 }} | 模板: {{ setupStatus.templates_available || 0 }}</n-text>
                </div>
                <n-tag :type="setupStatus.initialized ? 'success' : 'warning'" size="small">
                  {{ setupStatus.initialized ? '已初始化' : '未初始化' }}
                </n-tag>
              </n-space>
            </n-card>
            <n-card size="small" title="演示数据">
              <n-text depth="3">创建一组演示设备和场景，用于快速体验 ProtoForge 功能。</n-text>
              <template #action>
                <n-button type="primary" :loading="demoLoading" @click="setupDemo" :disabled="setupStatus.demo_initialized">
                  {{ setupStatus.demo_initialized ? '已创建' : '创建演示数据' }}
                </n-button>
              </template>
            </n-card>
          </n-space>
        </n-spin>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="showAddUser" title="添加用户" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-input v-model:value="newUser.username" placeholder="用户名" />
        <n-input v-model:value="newUser.password" type="password" placeholder="密码（至少8位，含大小写/数字/特殊字符中3种）" show-password-on="click" />
        <n-select v-model:value="newUser.role" :options="roleOptions" placeholder="角色" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAddUser = false">取消</n-button>
          <n-button type="primary" :loading="addUserLoading" @click="handleAddUser">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showResetPassword" title="重置密码" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-text>为用户 <n-text strong>{{ resetTarget.username }}</n-text> 设置新密码</n-text>
        <n-input v-model:value="resetTarget.new_password" type="password" placeholder="新密码（至少8位，含大小写/数字/特殊字符中3种）" show-password-on="click" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showResetPassword = false">取消</n-button>
          <n-button type="primary" :loading="resetLoading" @click="handleResetPassword">确认重置</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showChangePassword" title="修改密码" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-input v-model:value="changePwdForm.username" placeholder="用户名" disabled />
        <n-input v-model:value="changePwdForm.old_password" type="password" placeholder="当前密码" show-password-on="click" />
        <n-input v-model:value="changePwdForm.new_password" type="password" placeholder="新密码（至少8位，含大小写/数字/特殊字符中3种）" show-password-on="click" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showChangePassword = false">取消</n-button>
          <n-button type="primary" :loading="changePwdLoading" @click="handleChangePassword">确认修改</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NButton, NSpace, NTag, NPopconfirm, NSelect, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { getProtocolLabel, PASSWORD_MASK } from '../constants.js'

const message = useMessage()
const dialog = useDialog()

const settingsLoading = ref(false)
const saveLoading = ref(false)
const setupLoading = ref(false)
const demoLoading = ref(false)
const addUserLoading = ref(false)
const resetLoading = ref(false)
const testEdgeLiteLoading = ref(false)
const testEdgeLiteResult = ref(null)

const form = ref({
  port: 8000,
  log_level: 'info',
  cors_origins: '*',
  demo_mode: false,
  edgelite_url: '',
  edgelite_username: 'admin',
  edgelite_password: '',
  influxdb_url: '',
  influxdb_token: '',
  influxdb_org: 'default',
  influxdb_bucket: 'protoforge',
  protoforge_public_host: '',
  protocol_ports: {},
})

const logLevelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
  { label: 'CRITICAL', value: 'critical' },
]

const roleOptions = [
  { label: '管理员', value: 'admin' },
  { label: '操作员', value: 'operator' },
  { label: '用户', value: 'user' },
  { label: '只读', value: 'viewer' },
]

const users = ref([])
const setupStatus = ref({})
const showAddUser = ref(false)
const showResetPassword = ref(false)
const showChangePassword = ref(false)
const newUser = ref({ username: '', password: '', role: 'user' })
const resetTarget = ref({ username: '', new_password: '' })
const changePwdForm = ref({ username: '', old_password: '', new_password: '' })
const changePwdLoading = ref(false)

const userColumns = [
  { title: '用户名', key: 'username', width: 150 },
  {
    title: '角色', key: 'role', width: 120,
    render: (row) => h(NTag, { size: 'small', type: row.role === 'admin' ? 'error' : row.role === 'operator' ? 'warning' : 'info', bordered: false }, () => row.role),
  },
  {
    title: '状态', key: 'locked', width: 100,
    render: (row) => row.locked ? h(NTag, { size: 'small', type: 'error', bordered: false }, () => '已锁定') : h(NTag, { size: 'small', type: 'success', bordered: false }, () => '正常'),
  },
  {
    title: '操作', key: 'actions', width: 320,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => openResetPassword(row) }, () => '重置密码'),
      row.locked ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => unlockUser(row) }, () => '解锁') : null,
      h(NSelect, {
        size: 'tiny',
        value: row.role,
        options: roleOptions,
        style: 'width: 100px',
        onUpdateValue: (val) => changeRole(row, val),
      }),
      row.username !== 'admin' ? h(NPopconfirm, { onPositiveClick: () => deleteUser(row) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error', secondary: true }, () => '删除'),
        default: () => `确定删除用户 ${row.username}？`,
      }) : null,
    ]),
  },
]

async function loadSettings() {
  settingsLoading.value = true
  try {
    const data = await api.getSettings()
    form.value = {
      port: data.port || 8000,
      log_level: data.log_level || 'info',
      cors_origins: data.cors_origins || '*',
      demo_mode: data.demo_mode || false,
      edgelite_url: data.edgelite_url || '',
      edgelite_username: data.edgelite_username || 'admin',
      edgelite_password: data.edgelite_password || '',
      influxdb_url: data.influxdb_url || '',
      influxdb_token: data.influxdb_token || '',
      influxdb_org: data.influxdb_org || 'default',
      influxdb_bucket: data.influxdb_bucket || 'protoforge',
      protoforge_public_host: data.protoforge_public_host || '',
      protocol_ports: data.protocol_ports || {},
    }
  } catch (e) {
    message.error('加载设置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings() {
  saveLoading.value = true
  try {
    const updates = { ...form.value }
    if (updates.edgelite_password === PASSWORD_MASK) delete updates.edgelite_password
    if (updates.influxdb_token === PASSWORD_MASK) delete updates.influxdb_token
    await api.updateSettings(updates)
    message.success('设置已保存，部分配置需重启生效')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saveLoading.value = false
  }
}

async function testEdgeLiteConnection() {
  if (!form.value.edgelite_url) {
    message.warning('请先填写 EdgeLite URL')
    return
  }
  testEdgeLiteLoading.value = true
  testEdgeLiteResult.value = null
  try {
    const testPayload = {
      url: form.value.edgelite_url,
      username: form.value.edgelite_username || 'admin',
    }
    if (form.value.edgelite_password && form.value.edgelite_password !== PASSWORD_MASK) {
      testPayload.password = form.value.edgelite_password
    }
    const res = await api.testEdgeliteConnection(testPayload)
    testEdgeLiteResult.value = res
  } catch (e) {
    testEdgeLiteResult.value = { ok: false, error: e.response?.data?.detail || e.message }
  } finally {
    testEdgeLiteLoading.value = false
  }
}

async function loadUsers() {
  try {
    const data = await api.listUsers()
    users.value = Array.isArray(data) ? data : []
  } catch (e) {
    message.error('加载用户列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadSetupStatus() {
  setupLoading.value = true
  try {
    setupStatus.value = await api.getSetupStatus()
  } catch (e) {
    message.warning('加载系统状态失败')
  } finally {
    setupLoading.value = false
  }
}

function openAddUser() {
  newUser.value = { username: '', password: '', role: 'user' }
  showAddUser.value = true
}

async function handleAddUser() {
  if (!newUser.value.username || !newUser.value.password) {
    message.warning('请填写用户名和密码')
    return
  }
  const pwd = newUser.value.password
  if (pwd.length < 8) {
    message.warning('密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  const types = [/[a-z]/.test(pwd), /[A-Z]/.test(pwd), /[0-9]/.test(pwd), /[^a-zA-Z0-9]/.test(pwd)].filter(Boolean).length
  if (types < 3) {
    message.warning('密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  addUserLoading.value = true
  try {
    await api.register(newUser.value.username, newUser.value.password)
    if (newUser.value.role !== 'user') {
      await api.adminUpdateRole(newUser.value.username, newUser.value.role)
    }
    message.success('用户创建成功')
    showAddUser.value = false
    await loadUsers()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    addUserLoading.value = false
  }
}

function openResetPassword(row) {
  resetTarget.value = { username: row.username, new_password: '' }
  showResetPassword.value = true
}

async function handleResetPassword() {
  const pwd = resetTarget.value.new_password
  if (!pwd || pwd.length < 8) {
    message.warning('新密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  const types = [/[a-z]/.test(pwd), /[A-Z]/.test(pwd), /[0-9]/.test(pwd), /[^a-zA-Z0-9]/.test(pwd)].filter(Boolean).length
  if (types < 3) {
    message.warning('新密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  resetLoading.value = true
  try {
    await api.adminResetPassword(resetTarget.value.username, resetTarget.value.new_password)
    message.success('密码已重置')
    showResetPassword.value = false
  } catch (e) {
    message.error('重置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    resetLoading.value = false
  }
}

async function unlockUser(row) {
  try {
    await api.adminUnlockUser(row.username)
    message.success('用户已解锁')
    await loadUsers()
  } catch (e) {
    message.error('解锁失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function changeRole(row, newRole) {
  dialog.warning({
    title: '确认更改角色',
    content: `将用户 ${row.username} 的角色从 ${row.role} 更改为 ${newRole}，确定继续？`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.adminUpdateRole(row.username, newRole)
        message.success('角色已更新')
        await loadUsers()
      } catch (e) {
        message.error('更新角色失败: ' + (e.response?.data?.detail || e.message))
      }
    },
    onNegativeClick: () => { loadUsers() },
  })
}

async function deleteUser(row) {
  try {
    await api.deleteUser(row.username)
    message.success('用户已删除')
    await loadUsers()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

function openChangePassword() {
  const currentUser = localStorage.getItem('username') || ''
  changePwdForm.value = { username: currentUser, old_password: '', new_password: '' }
  showChangePassword.value = true
}

async function handleChangePassword() {
  if (!changePwdForm.value.old_password || !changePwdForm.value.new_password) {
    message.warning('请填写当前密码和新密码')
    return
  }
  const pwd = changePwdForm.value.new_password
  if (pwd.length < 8) {
    message.warning('新密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  const types = [/[a-z]/.test(pwd), /[A-Z]/.test(pwd), /[0-9]/.test(pwd), /[^a-zA-Z0-9]/.test(pwd)].filter(Boolean).length
  if (types < 3) {
    message.warning('新密码至少8位，需包含大小写字母、数字、特殊字符中的至少3种')
    return
  }
  changePwdLoading.value = true
  try {
    await api.changePassword(changePwdForm.value.username, changePwdForm.value.old_password, changePwdForm.value.new_password)
    message.success('密码修改成功')
    showChangePassword.value = false
  } catch (e) {
    message.error('修改失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    changePwdLoading.value = false
  }
}

async function setupDemo() {
  demoLoading.value = true
  try {
    const res = await api.setupDemo()
    message.success(`演示数据已创建：${res.device_count || 0} 个设备，${res.scenario_count || 0} 个场景`)
    await loadSetupStatus()
  } catch (e) {
    message.error('创建演示数据失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    demoLoading.value = false
  }
}

onMounted(() => {
  loadSettings()
  loadUsers()
  loadSetupStatus()
})
</script>
