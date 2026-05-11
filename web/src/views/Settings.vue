<template>
  <div>
    <n-h2 style="margin-bottom: 4px">{{ t('settings.title') }}</n-h2>
    <n-text depth="3" style="font-size: 13px">{{ t('settings.subtitle') }}</n-text>

    <n-tabs type="line" animated style="margin-top: 20px">
      <n-tab-pane name="general" :tab="t('settings.general')">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item :label="t('settings.servicePort')">
              <n-input-number v-model:value="form.port" :min="1" :max="65535" style="width: 200px" />
            </n-form-item>
            <n-form-item :label="t('settings.logLevel')">
              <n-select v-model:value="form.log_level" :options="logLevelOptions" style="width: 200px" />
            </n-form-item>
            <n-form-item :label="t('settings.corsOrigin')">
              <n-input v-model:value="form.cors_origins" :placeholder="t('settings.corsPlaceholder')" />
            </n-form-item>
            <n-form-item :label="t('settings.demoMode')">
              <n-switch v-model:value="form.demo_mode" />
            </n-form-item>
            <n-form-item>
              <n-space>
                <n-button type="primary" :loading="saveLoading" @click="saveSettings">{{ t('settings.saveSettings') }}</n-button>
              </n-space>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="integration" :tab="t('settings.integrationConfig')">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item :label="t('settings.edgeliteUrl')">
              <n-input v-model:value="form.edgelite_url" placeholder="http://edgelite:8080" />
            </n-form-item>
            <n-form-item :label="t('settings.edgeliteUsername')">
              <n-input v-model:value="form.edgelite_username" />
            </n-form-item>
            <n-form-item :label="t('settings.edgelitePassword')">
              <n-input v-model:value="form.edgelite_password" type="password" show-password-on="click" :placeholder="form.edgelite_password ? PASSWORD_MASK : ''" />
            </n-form-item>
            <n-form-item>
              <n-space>
                <n-button type="primary" :loading="saveLoading" @click="saveSettings">{{ t('settings.saveSettings') }}</n-button>
                <n-button :loading="testEdgeLiteLoading" @click="testEdgeLiteConnection">{{ t('settings.testConnection') }}</n-button>
              </n-space>
            </n-form-item>
            <n-alert v-if="testEdgeLiteResult" :type="testEdgeLiteResult.ok ? 'success' : 'error'" :bordered="false" style="margin-bottom:12px">
              <template v-if="testEdgeLiteResult.ok">
                {{ t('settings.testConnectionSuccess', { version: testEdgeLiteResult.version || t('common.unknown'), devices: testEdgeLiteResult.devices || 0 }) }}
              </template>
              <template v-else>
                {{ t('settings.testConnectionFailed', { error: testEdgeLiteResult.error }) }}
              </template>
            </n-alert>
          </n-form>
          <n-divider style="max-width: 600px" />
          <n-form label-placement="left" label-width="140" style="max-width: 600px">
            <n-form-item :label="t('settings.influxdbUrl')">
              <n-input v-model:value="form.influxdb_url" placeholder="http://influxdb:8086" />
            </n-form-item>
            <n-form-item :label="t('settings.influxdbToken')">
              <n-input v-model:value="form.influxdb_token" type="password" show-password-on="click" :placeholder="form.influxdb_token ? PASSWORD_MASK : ''" />
            </n-form-item>
            <n-form-item :label="t('settings.influxdbOrg')">
              <n-input v-model:value="form.influxdb_org" />
            </n-form-item>
            <n-form-item :label="t('settings.influxdbBucket')">
              <n-input v-model:value="form.influxdb_bucket" />
            </n-form-item>
            <n-form-item :label="t('settings.publicHost')">
              <n-input v-model:value="form.protoforge_public_host" :placeholder="t('settings.publicHostPlaceholder')" />
            </n-form-item>
            <n-form-item>
              <n-button type="primary" :loading="saveLoading" @click="saveSettings">{{ t('settings.saveSettings') }}</n-button>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="ports" :tab="t('settings.protocolPort')">
        <n-spin :show="settingsLoading">
          <n-form label-placement="left" label-width="140" style="max-width: 600px; margin-top: 16px">
            <n-form-item v-for="(port, key) in form.protocol_ports" :key="key" :label="getProtocolLabel(key)">
              <n-input v-if="key === 'modbus_rtu'" v-model:value="form.protocol_ports[key]" />
              <n-input-number v-else v-model:value="form.protocol_ports[key]" :min="1" :max="65535" style="width: 200px" />
            </n-form-item>
            <n-form-item>
              <n-button type="primary" :loading="saveLoading" @click="saveSettings">{{ t('settings.saveSettings') }}</n-button>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="users" :tab="t('settings.userManagement')">
        <n-space style="margin: 16px 0">
          <n-button type="primary" @click="openAddUser">{{ t('settings.addUser') }}</n-button>
          <n-button @click="openChangePassword">{{ t('common.changePassword') }}</n-button>
        </n-space>
        <n-data-table :columns="userColumns" :data="users" :bordered="false" size="small" />
      </n-tab-pane>

      <n-tab-pane name="demo" :tab="t('settings.demoData')">
        <n-spin :show="setupLoading">
          <n-space vertical style="margin-top: 16px">
            <n-card size="small">
              <n-space align="center" justify="space-between">
                <div>
                  <n-text strong>{{ t('settings.systemStatus') }}</n-text>
                  <n-text depth="3" style="margin-left: 8px">{{ t('settings.deviceCount') }}: {{ setupStatus.device_count || 0 }} | {{ t('settings.scenarioCount') }}: {{ setupStatus.scenario_count || 0 }} | {{ t('settings.runningProtocols') }}: {{ setupStatus.protocols_running || 0 }} | {{ t('settings.templatesAvailable') }}: {{ setupStatus.templates_available || 0 }}</n-text>
                </div>
                <n-tag :type="setupStatus.initialized ? 'success' : 'warning'" size="small">
                  {{ setupStatus.initialized ? t('settings.initialized') : t('settings.notInitialized') }}
                </n-tag>
              </n-space>
            </n-card>
            <n-card size="small" :title="t('settings.demoData')">
              <n-text depth="3">{{ t('settings.demoDataDesc') }}</n-text>
              <template #action>
                <n-button type="primary" :loading="demoLoading" @click="setupDemo" :disabled="setupStatus.demo_initialized">
                  {{ setupStatus.demo_initialized ? t('settings.demoCreated') : t('settings.createDemoData') }}
                </n-button>
              </template>
            </n-card>
          </n-space>
        </n-spin>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="showAddUser" :title="t('settings.addUserTitle')" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-input v-model:value="newUser.username" :placeholder="t('common.username')" />
        <n-input v-model:value="newUser.password" type="password" :placeholder="t('common.passwordPolicy')" show-password-on="click" />
        <n-select v-model:value="newUser.role" :options="roleOptions" :placeholder="t('common.role')" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAddUser = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="addUserLoading" @click="handleAddUser">{{ t('common.create') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showResetPassword" :title="t('settings.resetPasswordTitle')" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-text>{{ t('settings.setPasswordFor', { username: resetTarget.username }) }}</n-text>
        <n-input v-model:value="resetTarget.new_password" type="password" :placeholder="t('common.passwordPolicy')" show-password-on="click" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showResetPassword = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="resetLoading" @click="handleResetPassword">{{ t('common.confirm') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showChangePassword" :title="t('settings.changePasswordTitle')" preset="card" style="width: 420px" :mask-closable="false">
      <n-space vertical>
        <n-input v-model:value="changePwdForm.username" :placeholder="t('common.username')" disabled />
        <n-input v-model:value="changePwdForm.old_password" type="password" :placeholder="t('common.currentPassword')" show-password-on="click" />
        <n-input v-model:value="changePwdForm.new_password" type="password" :placeholder="t('common.passwordPolicy')" show-password-on="click" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showChangePassword = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="changePwdLoading" @click="handleChangePassword">{{ t('common.confirm') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NButton, NSpace, NTag, NPopconfirm, NSelect, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { getProtocolLabel, PASSWORD_MASK } from '../constants.js'
import { validatePassword } from '../utils.js'

const message = useMessage()
const { t } = useI18n()
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

const roleOptions = computed(() => [
  { label: t('settings.admin'), value: 'admin' },
  { label: t('settings.operator'), value: 'operator' },
  { label: t('settings.user'), value: 'user' },
  { label: t('settings.viewer'), value: 'viewer' },
])

const users = ref([])
const setupStatus = ref({})
const showAddUser = ref(false)
const showResetPassword = ref(false)
const showChangePassword = ref(false)
const newUser = ref({ username: '', password: '', role: 'user' })
const resetTarget = ref({ username: '', new_password: '' })
const changePwdForm = ref({ username: '', old_password: '', new_password: '' })
const changePwdLoading = ref(false)

const userColumns = computed(() => [
  { title: t('common.username'), key: 'username', width: 150 },
  {
    title: t('common.role'), key: 'role', width: 120,
    render: (row) => h(NTag, { size: 'small', type: row.role === 'admin' ? 'error' : row.role === 'operator' ? 'warning' : 'info', bordered: false }, () => row.role),
  },
  {
    title: t('common.status'), key: 'locked', width: 100,
    render: (row) => row.locked ? h(NTag, { size: 'small', type: 'error', bordered: false }, () => t('common.locked')) : h(NTag, { size: 'small', type: 'success', bordered: false }, () => t('common.normal')),
  },
  {
    title: t('common.action'), key: 'actions', width: 320,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => openResetPassword(row) }, () => t('common.resetPassword')),
      row.locked ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => unlockUser(row) }, () => t('common.unlock')) : null,
      h(NSelect, {
        size: 'tiny',
        value: row.role,
        options: roleOptions.value,
        style: 'width: 100px',
        onUpdateValue: (val) => changeRole(row, val),
      }),
      row.username !== 'admin' ? h(NPopconfirm, { onPositiveClick: () => deleteUser(row) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error', secondary: true }, () => t('common.delete')),
        default: () => t('settings.confirmDeleteUser', { username: row.username }),
      }) : null,
    ]),
  },
])

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
    message.error(t('settings.loadSettingsFailed') + ': ' + (e.response?.data?.detail || e.message))
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
    message.success(t('settings.settingsSaved'))
  } catch (e) {
    message.error(t('common.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    saveLoading.value = false
  }
}

async function testEdgeLiteConnection() {
  if (!form.value.edgelite_url) {
    message.warning(t('settings.edgeliteUrlRequired'))
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
    message.error(t('settings.loadUsersFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function loadSetupStatus() {
  setupLoading.value = true
  try {
    setupStatus.value = await api.getSetupStatus()
  } catch (e) {
    message.warning(t('settings.loadStatusFailed'))
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
    message.warning(t('settings.usernameRequired'))
    return
  }
  const pwd = newUser.value.password
  const pwCheck = validatePassword(pwd)
  if (!pwCheck.valid) {
    message.warning(t('settings.passwordPolicy'))
    return
  }
  addUserLoading.value = true
  try {
    await api.register(newUser.value.username, newUser.value.password)
    if (newUser.value.role !== 'user') {
      try {
        await api.adminUpdateRole(newUser.value.username, newUser.value.role)
      } catch (roleErr) {
        try { await api.deleteUser(newUser.value.username) } catch { /* best effort cleanup */ }
        message.error(t('settings.updateRoleFailed') + ': ' + (roleErr.response?.data?.detail || roleErr.message))
        await loadUsers()
        return
      }
    }
    message.success(t('settings.userCreated'))
    showAddUser.value = false
    await loadUsers()
  } catch (e) {
    message.error(t('common.createFailed') + ': ' + (e.response?.data?.detail || e.message))
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
  const pwCheck = validatePassword(pwd)
  if (!pwCheck.valid) {
    message.warning(t('settings.passwordPolicy'))
    return
  }
  resetLoading.value = true
  try {
    await api.adminResetPassword(resetTarget.value.username, resetTarget.value.new_password)
    message.success(t('settings.passwordReset'))
    showResetPassword.value = false
  } catch (e) {
    message.error(t('common.operationFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    resetLoading.value = false
  }
}

async function unlockUser(row) {
  try {
    await api.adminUnlockUser(row.username)
    message.success(t('settings.userUnlocked'))
    await loadUsers()
  } catch (e) {
    message.error(t('common.operationFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function changeRole(row, newRole) {
  dialog.warning({
    title: t('settings.confirmChangeRole'),
    content: t('settings.confirmChangeRoleDesc', { username: row.username, oldRole: row.role, newRole }),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.adminUpdateRole(row.username, newRole)
        message.success(t('settings.roleUpdated'))
        await loadUsers()
      } catch (e) {
        message.error(t('settings.updateRoleFailed') + ': ' + (e.response?.data?.detail || e.message))
        await loadUsers()
      }
    },
    onNegativeClick: () => { loadUsers() },
  })
}

async function deleteUser(row) {
  try {
    await api.deleteUser(row.username)
    message.success(t('settings.userDeleted'))
    await loadUsers()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

function openChangePassword() {
  const currentUser = localStorage.getItem('username') || ''
  changePwdForm.value = { username: currentUser, old_password: '', new_password: '' }
  showChangePassword.value = true
}

async function handleChangePassword() {
  if (!changePwdForm.value.old_password || !changePwdForm.value.new_password) {
    message.warning(t('settings.fillOldAndNewPassword'))
    return
  }
  const pwd = changePwdForm.value.new_password
  const pwCheck = validatePassword(pwd)
  if (!pwCheck.valid) {
    message.warning(t('settings.passwordPolicy'))
    return
  }
  changePwdLoading.value = true
  try {
    await api.changePassword(changePwdForm.value.username, changePwdForm.value.old_password, changePwdForm.value.new_password)
    message.success(t('settings.passwordChanged'))
    showChangePassword.value = false
  } catch (e) {
    message.error(t('settings.changePasswordFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    changePwdLoading.value = false
  }
}

async function setupDemo() {
  dialog.warning({
    title: t('settings.confirmDemo') || '确认创建演示数据',
    content: t('settings.confirmDemoDesc') || '将批量创建演示设备和场景，此操作不可撤销。确定继续？',
    positiveText: t('common.create') || '创建',
    negativeText: t('common.cancel') || '取消',
    onPositiveClick: async () => {
      demoLoading.value = true
      try {
        const res = await api.setupDemo()
        message.success(t('settings.demoCreateSuccess', { devices: res.device_count || 0, scenarios: res.scenario_count || 0 }))
        await loadSetupStatus()
      } catch (e) {
        message.error(t('settings.demoCreateFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        demoLoading.value = false
      }
    }
  })
}

onMounted(() => {
  loadSettings()
  loadUsers()
  loadSetupStatus()
})
</script>
