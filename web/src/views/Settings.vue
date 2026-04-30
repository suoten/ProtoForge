<template>
  <div>
    <n-space vertical size="large">
      <div>
        <div class="pf-section-title">系统设置</div>
        <div class="pf-section-desc">管理服务器配置、用户权限、数据转发、录制回放和 Webhook 通知</div>
      </div>

      <n-tabs type="card">
        <n-tab-pane name="general" tab="通用配置">
          <n-space vertical size="large">
            <n-card size="small" title="快速设置">
              <template #header-extra>
                <n-space size="small">
                  <n-button size="small" @click="loadSetupStatus" :loading="loadingSetup">检查状态</n-button>
                  <n-button size="small" type="primary" @click="runSetupDemo" :loading="settingUpDemo">一键演示</n-button>
                </n-space>
              </template>
              <n-alert v-if="setupStatus" :type="setupStatus.demo_initialized ? 'success' : 'info'" :bordered="false">
                <template v-if="setupStatus.demo_initialized">
                  演示环境已初始化。设备数: {{ setupStatus.device_count || 0 }}，场景数: {{ setupStatus.scenario_count || 0 }}
                </template>
                <template v-else>
                  点击「一键演示」自动创建示例设备和场景，快速体验 ProtoForge 功能
                </template>
              </n-alert>
            </n-card>
            <n-card title="服务器配置" size="small">
              <n-form :model="serverConfig" label-placement="left" label-width="120">
                <n-form-item label="监听地址">
                  <n-input v-model:value="serverConfig.host" placeholder="0.0.0.0" />
                </n-form-item>
                <n-form-item label="Web端口">
                  <n-input-number v-model:value="serverConfig.port" :min="1" :max="65535" style="width:100%" />
                  <n-text depth="3" style="margin-left:8px;font-size:12px">重启服务后生效</n-text>
                </n-form-item>
                <n-form-item label="数据库路径">
                  <n-input v-model:value="serverConfig.db_path" placeholder="data/protoforge.db 或 postgresql://user:pass@host:5432/db" />
                </n-form-item>
                <n-form-item label="日志级别">
                  <n-select v-model:value="serverConfig.log_level" :options="logLevelOptions" style="width:200px" />
                </n-form-item>
                <n-form-item label="CORS源">
                  <n-input v-model:value="serverConfig.cors_origins" placeholder="* 或 https://example.com" />
                  <n-text depth="3" style="margin-left:8px;font-size:12px">多个用逗号分隔</n-text>
                </n-form-item>
              </n-form>
            </n-card>

            <n-card title="EdgeLite 网关联调配置（可选）" size="small">
              <template #header-extra>
                <n-text depth="3" style="font-size:12px">配置后可在设备中一键启用联调</n-text>
              </template>
              <n-form :model="edgeliteConfig" label-placement="left" label-width="120">
                <n-form-item label="网关地址">
                  <n-input v-model:value="edgeliteConfig.url" placeholder="http://192.168.1.200:8100" />
                </n-form-item>
                <n-form-item label="用户名">
                  <n-input v-model:value="edgeliteConfig.username" placeholder="admin" />
                </n-form-item>
                <n-form-item label="密码">
                  <n-input v-model:value="edgeliteConfig.password" type="password" show-password-on="click" placeholder="EdgeLite 登录密码" />
                </n-form-item>
                <n-form-item>
                  <n-button size="small" @click="testEdgeliteConnection" :loading="testingEdgelite">
                    <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></template>
                    测试连接
                  </n-button>
                  <n-text v-if="edgeliteTestResult" :type="edgeliteTestResult.ok ? 'success' : 'error'" style="margin-left:12px;font-size:13px">
                    {{ edgeliteTestResult.ok ? '连接成功' + (edgeliteTestResult.version ? ' (版本: ' + edgeliteTestResult.version + ')' : '') : '连接失败: ' + edgeliteTestResult.error }}
                  </n-text>
                </n-form-item>
              </n-form>
            </n-card>

            <n-card title="InfluxDB 转发配置（可选）" size="small">
              <n-form :model="influxdbConfig" label-placement="left" label-width="120">
                <n-form-item label="URL">
                  <n-input v-model:value="influxdbConfig.url" placeholder="http://localhost:8086" />
                </n-form-item>
                <n-form-item label="Token">
                  <n-input v-model:value="influxdbConfig.token" type="password" show-password-on="click" placeholder="InfluxDB API Token" />
                </n-form-item>
                <n-form-item label="组织">
                  <n-input v-model:value="influxdbConfig.org" placeholder="default" />
                </n-form-item>
                <n-form-item label="Bucket">
                  <n-input v-model:value="influxdbConfig.bucket" placeholder="protoforge" />
                </n-form-item>
              </n-form>
            </n-card>

            <n-card title="协议端口配置" size="small">
              <template #header-extra>
                <n-text depth="3" style="font-size:12px">修改后需重启对应协议</n-text>
              </template>
              <n-grid :cols="2" :x-gap="16" :y-gap="8">
                <n-gi v-for="item in protocolPortList" :key="item.key">
                  <n-form-item :label="item.label" label-placement="left" :show-feedback="false" style="margin-bottom:4px">
                    <n-input
                      v-if="item.key === 'modbus_rtu'"
                      v-model:value="protocolPorts[item.key]"
                      :placeholder="String(item.default)"
                      style="width:180px"
                      size="small"
                    />
                    <n-input-number
                      v-else
                      v-model:value="protocolPorts[item.key]"
                      :min="1" :max="65535"
                      :placeholder="String(item.default)"
                      style="width:140px"
                      size="small"
                    />
                    <n-tag size="tiny" :bordered="false" :type="item.running ? 'success' : 'default'" style="margin-left:8px">
                      {{ item.running ? '运行中' : '已停止' }}
                    </n-tag>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </n-card>

            <n-space>
              <n-button type="primary" @click="saveSettings" :loading="saving">
                <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg></template>
                保存配置
              </n-button>
              <n-button tertiary @click="loadSettings">重置</n-button>
            </n-space>

            <n-alert v-if="saveResult" :type="hasChanges ? 'success' : 'info'" :bordered="false">
              {{ saveResult }}
            </n-alert>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="users" tab="用户管理">
          <n-card size="small">
            <template #header>
              <n-space align="center" size="small">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#6366f1" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                <span style="font-weight:600">用户管理</span>
              </n-space>
            </template>
            <template #header-extra>
              <n-space size="small">
                <n-button size="small" @click="loadUsers" :loading="loadingUsers">刷新</n-button>
                <n-button size="small" type="primary" @click="showAddUserModal = true">添加用户</n-button>
              </n-space>
            </template>
            <n-data-table :columns="userColumns" :data="users" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" :loading="loadingUsers" />
          </n-card>
        </n-tab-pane>

        <n-tab-pane name="forward" tab="数据转发">
          <n-space vertical size="large">
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                  <span style="font-weight:600">转发目标</span>
                </n-space>
              </template>
              <template #header-extra>
                <n-space size="small">
                  <n-button size="small" @click="loadForwardTargets" :loading="loadingForward">刷新</n-button>
                  <n-button size="small" type="primary" @click="showAddForwardModal = true">添加目标</n-button>
                  <n-button size="small" :type="forwardRunning ? 'warning' : 'success'" @click="toggleForward" :loading="togglingForward">
                    {{ forwardRunning ? '停止转发' : '启动转发' }}
                  </n-button>
                </n-space>
              </template>
              <n-data-table :columns="forwardColumns" :data="forwardTargets" :bordered="false" size="small"
                :pagination="{ pageSize: 10 }" :loading="loadingForward" />
            </n-card>

            <n-card size="small" title="转发统计">
              <n-grid :cols="4" :x-gap="12" :y-gap="8">
                <n-gi>
                  <n-statistic label="总转发次数" :value="forwardStats.total_forwards || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="成功" :value="forwardStats.success_count || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="失败" :value="forwardStats.fail_count || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="目标数" :value="forwardTargets.length" />
                </n-gi>
              </n-grid>
            </n-card>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="recorder" tab="录制回放">
          <n-space vertical size="large">
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#f59e0b" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
                  <span style="font-weight:600">录制管理</span>
                </n-space>
              </template>
              <template #header-extra>
                <n-space size="small">
                  <n-button size="small" :type="recorderActive ? 'warning' : 'success'" @click="toggleRecorder" :loading="togglingRecorder">
                    {{ recorderActive ? '停止录制' : '开始录制' }}
                  </n-button>
                  <n-button size="small" @click="loadRecordings" :loading="loadingRecordings">刷新</n-button>
                </n-space>
              </template>
              <n-alert v-if="recorderActive" type="success" :bordered="false" style="margin-bottom:12px">
                录制进行中... 已录制 {{ recorderStats.frames_captured || 0 }} 帧，{{ recorderStats.duration_seconds ? Math.round(recorderStats.duration_seconds) + 's' : '0s' }}
              </n-alert>
              <n-data-table :columns="recordingColumns" :data="recordings" :bordered="false" size="small"
                :pagination="{ pageSize: 10 }" :loading="loadingRecordings" />
            </n-card>

            <n-card size="small" title="录制统计">
              <n-grid :cols="4" :x-gap="12" :y-gap="8">
                <n-gi>
                  <n-statistic label="总录制数" :value="recorderStats.total_recordings || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="已捕获帧" :value="recorderStats.frames_captured || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="总时长" :value="Math.round(recorderStats.duration_seconds || 0) + 's'" />
                </n-gi>
                <n-gi>
                  <n-statistic label="状态" :value="recorderActive ? '录制中' : '空闲'" />
                </n-gi>
              </n-grid>
            </n-card>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="webhooks" tab="Webhook 通知">
          <n-space vertical size="large">
            <n-card size="small">
              <template #header>
                <n-space align="center" size="small">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#8b5cf6" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                  <span style="font-weight:600">Webhook 管理</span>
                </n-space>
              </template>
              <template #header-extra>
                <n-space size="small">
                  <n-button size="small" @click="loadWebhooks" :loading="loadingWebhooks">刷新</n-button>
                  <n-button size="small" type="primary" @click="showAddWebhookModal = true">添加 Webhook</n-button>
                </n-space>
              </template>
              <n-data-table :columns="webhookColumns" :data="webhooks" :bordered="false" size="small"
                :pagination="{ pageSize: 10 }" :loading="loadingWebhooks" />
            </n-card>

            <n-card size="small" title="Webhook 统计">
              <n-grid :cols="4" :x-gap="12" :y-gap="8">
                <n-gi>
                  <n-statistic label="总调用次数" :value="webhookStats.total_calls || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="成功" :value="webhookStats.success_count || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="失败" :value="webhookStats.fail_count || 0" />
                </n-gi>
                <n-gi>
                  <n-statistic label="Webhook数" :value="webhooks.length" />
                </n-gi>
              </n-grid>
            </n-card>
          </n-space>
        </n-tab-pane>
      </n-tabs>

      <n-modal v-model:show="showAddUserModal" preset="card" title="添加用户" style="width:420px">
        <n-form :model="newUser" label-placement="left" label-width="80">
          <n-form-item label="用户名">
            <n-input v-model:value="newUser.username" placeholder="输入用户名" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="newUser.password" type="password" show-password-on="click" placeholder="输入密码" />
          </n-form-item>
          <n-form-item label="角色">
            <n-select v-model:value="newUser.role" :options="roleOptions" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAddUserModal = false">取消</n-button>
            <n-button type="primary" @click="addUser" :loading="addingUser">创建</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showResetPwdModal" preset="card" title="重置密码" style="width:420px">
        <n-form :model="resetPwdForm" label-placement="left" label-width="80">
          <n-form-item label="用户">
            <n-input :value="resetPwdForm.username" disabled />
          </n-form-item>
          <n-form-item label="新密码">
            <n-input v-model:value="resetPwdForm.new_password" type="password" show-password-on="click" placeholder="输入新密码" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showResetPwdModal = false">取消</n-button>
            <n-button type="primary" @click="doResetPassword" :loading="resettingPwd">重置</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showAddForwardModal" preset="card" title="添加转发目标" style="width:480px">
        <n-form :model="newForward" label-placement="left" label-width="100">
          <n-form-item label="名称">
            <n-input v-model:value="newForward.name" placeholder="如 influxdb-prod" />
          </n-form-item>
          <n-form-item label="协议">
            <n-select v-model:value="newForward.protocol" :options="forwardProtocolOptions" placeholder="选择协议" />
          </n-form-item>
          <n-form-item label="目标地址">
            <n-input v-model:value="newForward.host" placeholder="如 192.168.1.100 或 influxdb.example.com" />
          </n-form-item>
          <n-form-item label="端口">
            <n-input-number v-model:value="newForward.port" :min="1" :max="65535" style="width:100%" />
          </n-form-item>
          <n-form-item label="额外参数">
            <n-input v-model:value="newForward.params" type="textarea" :rows="3" placeholder='JSON 格式，如 {"org":"default","bucket":"protoforge"}' />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAddForwardModal = false">取消</n-button>
            <n-button type="primary" @click="addForwardTarget" :loading="addingForward">添加</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showAddWebhookModal" preset="card" title="添加 Webhook" style="width:520px">
        <n-form :model="newWebhook" label-placement="left" label-width="100">
          <n-form-item label="名称">
            <n-input v-model:value="newWebhook.name" placeholder="如 dingtalk-alert" />
          </n-form-item>
          <n-form-item label="URL">
            <n-input v-model:value="newWebhook.url" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
          </n-form-item>
          <n-form-item label="事件">
            <n-select v-model:value="newWebhook.events" :options="webhookEventOptions" multiple placeholder="选择触发事件" />
          </n-form-item>
          <n-form-item label="请求头">
            <n-input v-model:value="newWebhook.headers" type="textarea" :rows="2" placeholder='JSON 格式，如 {"Content-Type":"application/json"}' />
          </n-form-item>
          <n-form-item label="启用">
            <n-switch v-model:value="newWebhook.enabled" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showAddWebhookModal = false">取消</n-button>
            <n-button type="primary" @click="addWebhook" :loading="addingWebhook">添加</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showEditWebhookModal" preset="card" title="编辑 Webhook" style="width:520px">
        <n-form :model="editWebhookForm" label-placement="left" label-width="100">
          <n-form-item label="名称">
            <n-input v-model:value="editWebhookForm.name" />
          </n-form-item>
          <n-form-item label="URL">
            <n-input v-model:value="editWebhookForm.url" />
          </n-form-item>
          <n-form-item label="事件">
            <n-select v-model:value="editWebhookForm.events" :options="webhookEventOptions" multiple />
          </n-form-item>
          <n-form-item label="请求头">
            <n-input v-model:value="editWebhookForm.headersStr" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="启用">
            <n-switch v-model:value="editWebhookForm.enabled" />
          </n-form-item>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showEditWebhookModal = false">取消</n-button>
            <n-button type="primary" @click="doUpdateWebhook" :loading="updatingWebhook">保存</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showRecordingDetailModal" preset="card" title="录制详情" style="width:600px">
        <n-space vertical v-if="recordingDetail">
          <n-descriptions label-placement="left" :column="2" bordered size="small">
            <n-descriptions-item label="ID">{{ recordingDetail.id }}</n-descriptions-item>
            <n-descriptions-item label="设备ID">{{ recordingDetail.device_id || '-' }}</n-descriptions-item>
            <n-descriptions-item label="时长">{{ recordingDetail.duration_seconds ? recordingDetail.duration_seconds.toFixed(1) + 's' : '-' }}</n-descriptions-item>
            <n-descriptions-item label="帧数">{{ recordingDetail.frame_count || 0 }}</n-descriptions-item>
            <n-descriptions-item label="创建时间" :span="2">{{ recordingDetail.created_at || '-' }}</n-descriptions-item>
          </n-descriptions>
          <n-text strong style="font-size:13px" v-if="recordingDetail.frames && recordingDetail.frames.length > 0">帧数据 (前20帧)</n-text>
          <n-data-table v-if="recordingDetail.frames && recordingDetail.frames.length > 0"
            :columns="recordingFrameColumns" :data="recordingDetail.frames.slice(0, 20)" :bordered="false" size="small" />
        </n-space>
        <template #action>
          <n-button @click="showRecordingDetailModal = false">关闭</n-button>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NCard, NForm, NFormItem, NInput, NInputNumber, NButton, NGrid, NGi, NTag, NText, NAlert, NSelect, NDataTable, NModal, NPopconfirm, NTabs, NTabPane, NStatistic, NSwitch, NDescriptions, NDescriptionsItem, useMessage } from 'naive-ui'
import api from '../api.js'
import { protocolLabels, defaultPorts } from '../constants.js'

const message = useMessage()
const saving = ref(false)
const saveResult = ref('')
const hasChanges = ref(false)

const serverConfig = ref({ host: '0.0.0.0', port: 8000, db_path: 'data/protoforge.db', log_level: 'info', cors_origins: '*' })
const influxdbConfig = ref({ url: '', token: '', org: 'default', bucket: 'protoforge' })
const edgeliteConfig = ref({ url: '', username: 'admin', password: '' })
const edgeliteTestResult = ref(null)
const testingEdgelite = ref(false)
const protocolPorts = ref({})
const protocols = ref([])

const users = ref([])
const loadingUsers = ref(false)
const showAddUserModal = ref(false)
const addingUser = ref(false)
const newUser = ref({ username: '', password: '', role: 'user' })
const showResetPwdModal = ref(false)
const resettingPwd = ref(false)
const resetPwdForm = ref({ username: '', new_password: '' })

const currentUsername = computed(() => localStorage.getItem('username') || 'admin')

const roleOptions = [
  { label: '管理员 (admin)', value: 'admin' },
  { label: '操作员 (operator)', value: 'operator' },
  { label: '普通用户 (user)', value: 'user' },
  { label: '只读用户 (viewer)', value: 'viewer' },
]

const roleColorMap = { admin: 'error', operator: 'warning', user: 'info', viewer: 'default' }

const userColumns = [
  { title: '用户名', key: 'username', width: 140 },
  {
    title: '角色', key: 'role', width: 120,
    render: (row) => h(NTag, { size: 'tiny', type: roleColorMap[row.role] || 'default', bordered: false }, () => row.role),
  },
  {
    title: '状态', key: 'locked', width: 80,
    render: (row) => row.locked
      ? h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => '已锁定')
      : h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => '正常'),
  },
  {
    title: '操作', key: 'actions', width: 280,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NSelect, {
        value: row.role,
        options: roleOptions,
        size: 'tiny',
        style: 'width:140px',
        disabled: row.username === 'admin',
        onUpdateValue: (v) => changeRole(row.username, v),
      }),
      row.locked
        ? h(NButton, { size: 'tiny', type: 'warning', onClick: () => unlockUser(row.username) }, () => '解锁')
        : null,
      h(NButton, { size: 'tiny', onClick: () => openResetPassword(row.username) }, () => '重置密码'),
      row.username !== 'admin' && row.username !== currentUsername.value
        ? h(NPopconfirm, { onPositiveClick: () => deleteUser(row.username) }, {
            trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
            default: () => `确定删除用户 "${row.username}" 吗？`,
          })
        : null,
    ]),
  },
]

const logLevelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
]

const protocolPortList = computed(() => {
  return Object.keys(protocolLabels).map(key => ({
    key,
    label: protocolLabels[key],
    default: defaultPorts[key],
    running: protocols.value.find(p => p.name === key)?.status === 'running',
  }))
})

const forwardTargets = ref([])
const loadingForward = ref(false)
const forwardRunning = ref(false)
const togglingForward = ref(false)
const forwardStats = ref({})
const showAddForwardModal = ref(false)
const addingForward = ref(false)
const newForward = ref({ name: '', protocol: 'modbus_tcp', host: '', port: 502, params: '' })

const forwardProtocolOptions = [
  { label: 'Modbus TCP', value: 'modbus_tcp' },
  { label: 'Siemens S7', value: 'siemens_s7' },
  { label: 'OPC UA', value: 'opc_ua' },
  { label: 'InfluxDB', value: 'influxdb' },
  { label: 'MQTT', value: 'mqtt' },
]

const forwardColumns = [
  { title: '名称', key: 'name', width: 140 },
  { title: '协议', key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => row.protocol) },
  { title: '地址', key: 'host', width: 160 },
  { title: '端口', key: 'port', width: 80 },
  {
    title: '操作', key: 'actions', width: 100,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => removeForwardTarget(row.name) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
      default: () => `确定删除转发目标 "${row.name}" 吗？`,
    }),
  },
]

const recordings = ref([])
const loadingRecordings = ref(false)
const recorderActive = ref(false)
const togglingRecorder = ref(false)
const recorderStats = ref({})

const recordingColumns = [
  { title: 'ID', key: 'id', width: 180, ellipsis: { tooltip: true } },
  { title: '设备', key: 'device_id', width: 140 },
  {
    title: '时长', key: 'duration', width: 100,
    render: (row) => row.duration_seconds ? `${row.duration_seconds.toFixed(1)}s` : '-',
  },
  {
    title: '帧数', key: 'frame_count', width: 80,
  },
  {
    title: '创建时间', key: 'created_at', width: 160,
  },
  {
    title: '操作', key: 'actions', width: 280,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewRecordingDetail(row.id) }, () => '详情'),
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => replayRecording(row.id) }, () => '回放'),
      h(NButton, { size: 'tiny', secondary: true, onClick: () => exportRecording(row.id) }, () => '导出'),
      h(NPopconfirm, { onPositiveClick: () => deleteRecording(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
        default: () => '确定删除此录制吗？',
      }),
    ]),
  },
]

const webhooks = ref([])
const loadingWebhooks = ref(false)
const webhookStats = ref({})
const showAddWebhookModal = ref(false)
const addingWebhook = ref(false)
const newWebhook = ref({ name: '', url: '', events: [], headers: '', enabled: true })

const showEditWebhookModal = ref(false)
const updatingWebhook = ref(false)
const editWebhookForm = ref({ id: '', name: '', url: '', events: [], headersStr: '', enabled: true })

const setupStatus = ref(null)
const loadingSetup = ref(false)
const settingUpDemo = ref(false)

const showRecordingDetailModal = ref(false)
const recordingDetail = ref(null)

const recordingFrameColumns = [
  { title: '序号', key: 'index', width: 60 },
  { title: '时间戳', key: 'timestamp', width: 160 },
  { title: '设备ID', key: 'device_id', width: 140 },
  { title: '数据', key: 'data', ellipsis: { tooltip: true } },
]

const webhookEventOptions = [
  { label: '设备上线', value: 'device_online' },
  { label: '设备离线', value: 'device_offline' },
  { label: '数据变化', value: 'data_change' },
  { label: '告警触发', value: 'alarm' },
  { label: '场景启动', value: 'scenario_start' },
  { label: '场景停止', value: 'scenario_stop' },
  { label: '测试完成', value: 'test_complete' },
]

const webhookColumns = [
  { title: '名称', key: 'name', width: 140 },
  { title: 'URL', key: 'url', width: 240, ellipsis: { tooltip: true } },
  {
    title: '事件', key: 'events', width: 180,
    render: (row) => h(NSpace, { size: 2 }, () => (row.events || []).map(e => h(NTag, { size: 'tiny', bordered: false }, () => e))),
  },
  {
    title: '状态', key: 'enabled', width: 80,
    render: (row) => h(NTag, { size: 'tiny', type: row.enabled ? 'success' : 'default', bordered: false }, () => row.enabled ? '启用' : '禁用'),
  },
  {
    title: '操作', key: 'actions', width: 220,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', secondary: true, onClick: () => testWebhook(row.id) }, () => '测试'),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => openEditWebhook(row) }, () => '编辑'),
      h(NPopconfirm, { onPositiveClick: () => deleteWebhook(row.id) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
        default: () => `确定删除 Webhook "${row.name}" 吗？`,
      }),
    ]),
  },
]

async function loadUsers() {
  loadingUsers.value = true
  try {
    users.value = await api.listUsers()
  } catch (e) {
    if (e.response?.status === 403) {
      users.value = []
    } else {
      message.error('加载用户列表失败')
    }
  } finally {
    loadingUsers.value = false
  }
}

async function addUser() {
  if (!newUser.value.username || !newUser.value.password) {
    message.warning('请填写用户名和密码')
    return
  }
  addingUser.value = true
  try {
    await api.register(newUser.value.username, newUser.value.password)
    if (newUser.value.role !== 'user') {
      await api.adminUpdateRole(newUser.value.username, newUser.value.role)
    }
    showAddUserModal.value = false
    newUser.value = { username: '', password: '', role: 'user' }
    message.success('用户创建成功')
    await loadUsers()
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    addingUser.value = false
  }
}

async function changeRole(username, role) {
  try {
    await api.adminUpdateRole(username, role)
    message.success(`已将 ${username} 角色修改为 ${role}`)
    await loadUsers()
  } catch (e) {
    message.error('修改角色失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function unlockUser(username) {
  try {
    await api.adminUnlockUser(username)
    message.success(`用户 ${username} 已解锁`)
    await loadUsers()
  } catch (e) {
    message.error('解锁失败: ' + (e.response?.data?.detail || e.message))
  }
}

function openResetPassword(username) {
  resetPwdForm.value = { username, new_password: '' }
  showResetPwdModal.value = true
}

async function doResetPassword() {
  if (!resetPwdForm.value.new_password) {
    message.warning('请输入新密码')
    return
  }
  resettingPwd.value = true
  try {
    await api.adminResetPassword(resetPwdForm.value.username, resetPwdForm.value.new_password)
    showResetPwdModal.value = false
    message.success('密码已重置')
  } catch (e) {
    message.error('重置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    resettingPwd.value = false
  }
}

async function deleteUser(username) {
  try {
    await api.deleteUser(username)
    message.success(`用户 ${username} 已删除`)
    await loadUsers()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadForwardTargets() {
  loadingForward.value = true
  try {
    forwardTargets.value = await api.listForwardTargets()
  } catch { forwardTargets.value = [] }
  finally { loadingForward.value = false }
}

async function addForwardTarget() {
  if (!newForward.value.name || !newForward.value.host) {
    message.warning('请填写名称和地址')
    return
  }
  addingForward.value = true
  try {
    let params = {}
    if (newForward.value.params) {
      try { params = JSON.parse(newForward.value.params) } catch { message.warning('额外参数JSON格式错误，已忽略'); params = {} }
    }
    await api.addForwardTarget({
      name: newForward.value.name,
      protocol: newForward.value.protocol,
      host: newForward.value.host,
      port: newForward.value.port,
      ...params,
    })
    showAddForwardModal.value = false
    newForward.value = { name: '', protocol: 'modbus_tcp', host: '', port: 502, params: '' }
    message.success('转发目标已添加')
    await loadForwardTargets()
  } catch (e) {
    message.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally { addingForward.value = false }
}

async function removeForwardTarget(name) {
  try {
    await api.removeForwardTarget(name)
    message.success('转发目标已删除')
    await loadForwardTargets()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function toggleForward() {
  togglingForward.value = true
  try {
    if (forwardRunning.value) {
      await api.stopForward()
      forwardRunning.value = false
      message.success('转发已停止')
    } else {
      await api.startForward()
      forwardRunning.value = true
      message.success('转发已启动')
    }
  } catch (e) {
    message.error('操作失败: ' + (e.response?.data?.detail || e.message))
  } finally { togglingForward.value = false }
}

async function loadForwardStats() {
  try {
    forwardStats.value = await api.getForwardStats()
    forwardRunning.value = forwardStats.value.running || false
  } catch { forwardStats.value = {} }
}

async function loadRecordings() {
  loadingRecordings.value = true
  try {
    recordings.value = await api.listRecordings()
  } catch { recordings.value = [] }
  finally { loadingRecordings.value = false }
}

async function toggleRecorder() {
  togglingRecorder.value = true
  try {
    if (recorderActive.value) {
      await api.stopRecording()
      recorderActive.value = false
      message.success('录制已停止')
    } else {
      await api.startRecording()
      recorderActive.value = true
      message.success('录制已开始')
    }
    await loadRecorderStats()
  } catch (e) {
    message.error('操作失败: ' + (e.response?.data?.detail || e.message))
  } finally { togglingRecorder.value = false }
}

async function replayRecording(id) {
  try {
    await api.replayRecording(id)
    message.success('回放已启动')
  } catch (e) {
    message.error('回放失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function exportRecording(id) {
  try {
    const data = await api.exportRecording(id)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `recording-${id}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('录制已导出')
  } catch (e) {
    message.error('导出失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteRecording(id) {
  try {
    await api.deleteRecording(id)
    message.success('录制已删除')
    await loadRecordings()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadRecorderStats() {
  try {
    recorderStats.value = await api.getRecorderStats()
    recorderActive.value = recorderStats.value.is_recording || false
  } catch { recorderStats.value = {} }
}

async function loadWebhooks() {
  loadingWebhooks.value = true
  try {
    webhooks.value = await api.listWebhooks()
  } catch { webhooks.value = [] }
  finally { loadingWebhooks.value = false }
}

async function addWebhook() {
  if (!newWebhook.value.name || !newWebhook.value.url) {
    message.warning('请填写名称和 URL')
    return
  }
  if (newWebhook.value.events.length === 0) {
    message.warning('请至少选择一个事件')
    return
  }
  addingWebhook.value = true
  try {
    let headers = {}
    if (newWebhook.value.headers) {
      try { headers = JSON.parse(newWebhook.value.headers) } catch { headers = {} }
    }
    await api.addWebhook({
      name: newWebhook.value.name,
      url: newWebhook.value.url,
      events: newWebhook.value.events,
      headers,
      enabled: newWebhook.value.enabled,
    })
    showAddWebhookModal.value = false
    newWebhook.value = { name: '', url: '', events: [], headers: '', enabled: true }
    message.success('Webhook 已添加')
    await loadWebhooks()
  } catch (e) {
    message.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally { addingWebhook.value = false }
}

async function testWebhook(id) {
  try {
    await api.testWebhook(id)
    message.success('Webhook 测试成功')
  } catch (e) {
    message.error('测试失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteWebhook(id) {
  try {
    await api.deleteWebhook(id)
    message.success('Webhook 已删除')
    await loadWebhooks()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadWebhookStats() {
  try {
    webhookStats.value = await api.getWebhookStats()
  } catch { webhookStats.value = {} }
}

async function openEditWebhook(row) {
  editWebhookForm.value = {
    id: row.id,
    name: row.name || '',
    url: row.url || '',
    events: [...(row.events || [])],
    headersStr: row.headers ? JSON.stringify(row.headers, null, 2) : '',
    enabled: row.enabled !== false,
  }
  showEditWebhookModal.value = true
}

async function doUpdateWebhook() {
  if (!editWebhookForm.value.name || !editWebhookForm.value.url) {
    message.warning('请填写名称和 URL')
    return
  }
  updatingWebhook.value = true
  try {
    let headers = {}
    if (editWebhookForm.value.headersStr) {
      try { headers = JSON.parse(editWebhookForm.value.headersStr) } catch { headers = {} }
    }
    await api.updateWebhook(editWebhookForm.value.id, {
      name: editWebhookForm.value.name,
      url: editWebhookForm.value.url,
      events: editWebhookForm.value.events,
      headers,
      enabled: editWebhookForm.value.enabled,
    })
    showEditWebhookModal.value = false
    message.success('Webhook 已更新')
    await loadWebhooks()
  } catch (e) {
    message.error('更新失败: ' + (e.response?.data?.detail || e.message))
  } finally { updatingWebhook.value = false }
}

async function loadSetupStatus() {
  loadingSetup.value = true
  try {
    setupStatus.value = await api.getSetupStatus()
  } catch (e) {
    setupStatus.value = { demo_initialized: false }
  } finally { loadingSetup.value = false }
}

async function runSetupDemo() {
  settingUpDemo.value = true
  try {
    const res = await api.setupDemo()
    message.success(`演示环境已创建！设备: ${res.device_count || 0}，场景: ${res.scenario_count || 0}`)
    await loadSetupStatus()
  } catch (e) {
    message.error('创建演示失败: ' + (e.response?.data?.detail || e.message))
  } finally { settingUpDemo.value = false }
}

async function viewRecordingDetail(id) {
  try {
    const res = await api.getRecording(id)
    recordingDetail.value = res
    showRecordingDetailModal.value = true
  } catch (e) {
    message.error('获取录制详情失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadSettings() {
  try {
    const [settings, protoRes] = await Promise.all([api.getSettings(), api.getProtocols()])
    serverConfig.value.host = settings.host || '0.0.0.0'
    serverConfig.value.port = settings.port || 8000
    serverConfig.value.db_path = settings.db_path || 'data/protoforge.db'
    serverConfig.value.log_level = settings.log_level || 'info'
    serverConfig.value.cors_origins = settings.cors_origins || '*'
    influxdbConfig.value.url = settings.influxdb_url || ''
    influxdbConfig.value.token = settings.influxdb_token || ''
    influxdbConfig.value.org = settings.influxdb_org || 'default'
    influxdbConfig.value.bucket = settings.influxdb_bucket || 'protoforge'
    edgeliteConfig.value.url = settings.edgelite_url || ''
    edgeliteConfig.value.username = settings.edgelite_username || 'admin'
    if (settings.edgelite_password && settings.edgelite_password !== '***') {
      edgeliteConfig.value.password = settings.edgelite_password
    }
    protocolPorts.value = { ...(settings.protocol_ports || {}) }
    protocols.value = protoRes
    saveResult.value = ''
  } catch (e) {
    message.error('加载设置失败')
  }
}

async function testEdgeliteConnection() {
  if (!edgeliteConfig.value.url) {
    message.warning('请先填写 EdgeLite 网关地址')
    return
  }
  testingEdgelite.value = true
  edgeliteTestResult.value = null
  try {
    edgeliteTestResult.value = await api.testEdgeliteConnection({
      url: edgeliteConfig.value.url,
      username: edgeliteConfig.value.username,
      password: edgeliteConfig.value.password,
    })
  } catch (e) {
    edgeliteTestResult.value = { ok: false, error: e.response?.data?.detail || e.message }
  } finally {
    testingEdgelite.value = false
  }
}

async function saveSettings() {
  saving.value = true
  saveResult.value = ''
  try {
    const updates = {
      host: serverConfig.value.host,
      port: serverConfig.value.port,
      db_path: serverConfig.value.db_path,
      log_level: serverConfig.value.log_level,
      cors_origins: serverConfig.value.cors_origins,
      influxdb_url: influxdbConfig.value.url,
      influxdb_token: influxdbConfig.value.token,
      influxdb_org: influxdbConfig.value.org,
      influxdb_bucket: influxdbConfig.value.bucket,
      edgelite_url: edgeliteConfig.value.url,
      edgelite_username: edgeliteConfig.value.username,
      edgelite_password: edgeliteConfig.value.password,
    }
    for (const [key, value] of Object.entries(protocolPorts.value)) {
      updates[`${key}_port`] = value
    }
    const result = await api.updateSettings(updates)
    hasChanges.value = Object.keys(result.changed || {}).length > 0
    if (hasChanges.value) {
      const changedNames = Object.keys(result.changed).map(k => {
        if (k.endsWith('_port')) {
          const protoKey = k.slice(0, -5)
          return protocolLabels[protoKey] || protoKey
        }
        return k
      })
      saveResult.value = `已保存并更新: ${changedNames.join(', ')}。协议端口修改需重启对应协议生效，Web端口需重启服务生效。`
    } else {
      saveResult.value = '配置已保存，无变更'
    }
    message.success('设置已保存')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadSettings()
  loadUsers()
  loadForwardTargets()
  loadForwardStats()
  loadRecordings()
  loadRecorderStats()
  loadWebhooks()
  loadWebhookStats()
  loadSetupStatus()
})
</script>
