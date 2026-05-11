<template>
  <n-space vertical>
    <div class="pf-section-title">联调集成</div>
    <div class="pf-section-desc">对接 EdgeLite 网关，完成设备注册→连接→采集→验证→监控的完整联调链路</div>

    <n-tabs type="card">
      <n-tab-pane name="edgelite-pipeline" tab="EdgeLite 联调">
        <n-space vertical size="large">
          <n-card size="small" title="EdgeLite 连接配置">
            <template #header-extra>
              <n-button text type="info" size="tiny" @click="$router.push('/settings')">在系统设置中管理</n-button>
            </template>
            <n-space vertical>
              <n-form :model="elConfig" label-placement="left" label-width="140" inline>
                <n-form-item label="EdgeLite地址">
                  <n-input v-model:value="elConfig.url" placeholder="http://edgelite-host:8100" style="width:260px" />
                </n-form-item>
                <n-form-item label="用户名">
                  <n-input v-model:value="elConfig.username" placeholder="admin" style="width:120px" />
                </n-form-item>
                <n-form-item label="密码">
                  <n-input v-model:value="elConfig.password" type="password" show-password-on="click" placeholder="密码" style="width:120px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="testConnection" :loading="testingConn">
                    测试连接
                  </n-button>
                </n-form-item>
              </n-form>
              <n-alert v-if="connResult" :type="connResult.ok ? 'success' : 'error'" :bordered="false" style="margin-top:4px">
                <template v-if="connResult.ok">
                  连接成功！EdgeLite 版本: {{ connResult.version || '未知' }}，设备总数: {{ connResult.devices || 0 }}
                </template>
                <template v-else>
                  连接失败: {{ connResult.error }}
                </template>
              </n-alert>
            </n-space>
          </n-card>

          <n-card size="small" title="联调链路说明">
            <n-space vertical size="small">
              <n-alert type="info" :bordered="false">
                <div style="font-weight:600;margin-bottom:8px">完整联调链路 (5步)</div>
                <div style="line-height:2">
                  <n-text code>1. 注册</n-text> ProtoForge 将设备配置推送到 EdgeLite，包含 driver_config 指向 ProtoForge 的 IP:端口<br/>
                  <n-text code>2. 连接</n-text> EdgeLite 的驱动根据 driver_config 反向连接 ProtoForge 的仿真设备<br/>
                  <n-text code>3. 采集</n-text> EdgeLite 定期从 ProtoForge 仿真设备读取数据<br/>
                  <n-text code>4. 验证</n-text> ProtoForge 从 EdgeLite 回读采集数据，与本地仿真数据对比<br/>
                  <n-text code>5. 监控</n-text> 持续查看 EdgeLite 上设备的在线状态和采集数据
                </div>
              </n-alert>
              <div style="padding:12px 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <div v-for="(step, idx) in pipelineSteps" :key="idx"
                  style="display:flex;align-items:center;gap:4px">
                  <div :style="{
                    width:'32px',height:'32px',borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',
                    fontSize:'14px',fontWeight:600,
                    background: step.color, color:'#fff'
                  }">{{ idx + 1 }}</div>
                  <span style="font-size:13px">{{ step.label }}</span>
                  <svg v-if="idx < pipelineSteps.length - 1" viewBox="0 0 24 24" width="20" height="20"
                    fill="none" stroke="#94a3b8" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                </div>
              </div>
            </n-space>
          </n-card>

          <n-card size="small" title="设备联调状态">
            <template #header-extra>
              <n-space>
                <n-button size="small" @click="loadDevices" :loading="loadingDevices">刷新</n-button>
                <n-button size="small" type="primary" @click="batchPushAndVerify" :loading="batchPipelineLoading">
                  批量推送并验证
                </n-button>
              </n-space>
            </template>
            <n-data-table :columns="deviceColumns" :data="elDevices" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="integration-status" tab="集成状态">
        <n-space vertical size="large">
          <n-grid :cols="4" :x-gap="12" :y-gap="12">
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">连接状态</div>
                <n-tag :type="intStatus.connection_state === 'connected' ? 'success' : 'error'" size="small" :bordered="false">
                  {{ intStatus.connection_state === 'connected' ? '已连接' : '未连接' }}
                </n-tag>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">推送成功</div>
                <div style="font-size:24px;font-weight:600;color:#6366f1">{{ intMetrics.push_success_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">推送失败</div>
                <div style="font-size:24px;font-weight:600;color:#ef4444">{{ intMetrics.push_failure_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">平均推送延迟</div>
                <div style="font-size:24px;font-weight:600;color:#f59e0b">{{ intMetrics.avg_push_latency_ms || 0 }}<span style="font-size:12px;font-weight:400">ms</span></div>
              </n-card>
            </n-gi>
          </n-grid>

          <n-grid :cols="4" :x-gap="12" :y-gap="12">
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">回传数据</div>
                <div style="font-size:24px;font-weight:600;color:#3b82f6">{{ intMetrics.data_backhaul_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">同步事件</div>
                <div style="font-size:24px;font-weight:600;color:#8b5cf6">{{ intMetrics.sync_event_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">告警转发</div>
                <div style="font-size:24px;font-weight:600;color:#ef4444">{{ intMetrics.alarm_forward_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">最后心跳</div>
                <div style="font-size:13px;font-weight:500;color:#64748b">{{ intMetrics.last_heartbeat_at ? new Date(intMetrics.last_heartbeat_at * 1000).toLocaleString() : '无' }}</div>
              </n-card>
            </n-gi>
          </n-grid>

          <n-card size="small" title="设备状态缓存">
            <template #header-extra>
              <n-button size="small" @click="loadDeviceStatusCache" :loading="loadingStatusCache">刷新</n-button>
            </template>
            <n-data-table :columns="statusCacheColumns" :data="deviceStatusCache" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" title="回传数据">
            <template #header-extra>
              <n-space size="small">
                <n-input v-model:value="backhaulDeviceId" size="small" placeholder="设备ID过滤" clearable style="width:180px" />
                <n-button size="small" @click="loadBackhaulData" :loading="loadingBackhaul">查询</n-button>
              </n-space>
            </template>
            <n-data-table :columns="backhaulColumns" :data="backhaulData" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" title="协议映射">
            <template #header-extra>
              <n-button size="small" @click="loadProtocolMappings" :loading="loadingProtocols">刷新</n-button>
            </template>
            <n-data-table :columns="protocolMapColumns" :data="protocolMappings" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" title="发送集成消息">
            <n-space vertical>
              <n-alert type="info" :bordered="false">
                向集成管理器发送自定义消息，触发特定动作或查询状态。支持自定义消息类型和载荷。
              </n-alert>
              <n-form :model="msgForm" label-placement="left" label-width="100" inline>
                <n-form-item label="消息类型">
                  <n-select v-model:value="msgForm.type" :options="msgTypeOptions" filterable tag placeholder="选择或输入消息类型" style="width:220px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="sendIntMessage" :loading="sendingMsg">发送</n-button>
                </n-form-item>
              </n-form>
              <n-input v-model:value="msgForm.payloadJson" type="textarea" :rows="3"
                placeholder='消息载荷 JSON（可选），如 {"device_id":"dev-001","action":"sync"}' />
              <n-alert v-if="msgResult" :type="msgResult.status === 'ok' ? 'success' : 'error'" :bordered="false">
                <div style="font-weight:600;margin-bottom:4px">{{ msgResult.status === 'ok' ? '发送成功' : '发送失败' }}</div>
                <div v-if="msgResult.data" style="font-size:12px;color:#94a3b8">{{ JSON.stringify(msgResult.data) }}</div>
                <div v-if="msgResult.error" style="font-size:12px;color:#ef4444">{{ msgResult.error }}</div>
              </n-alert>
            </n-space>
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="alarm-rules" tab="告警联动">
        <n-space vertical size="large">
          <n-card size="small" title="告警联动规则">
            <template #header-extra>
              <n-space size="small">
                <n-button size="small" @click="loadAlarmRules" :loading="loadingAlarmRules">刷新</n-button>
                <n-button size="small" type="primary" @click="showAddAlarmModal = true">添加规则</n-button>
              </n-space>
            </template>
            <n-alert v-if="alarmRules.length === 0 && !loadingAlarmRules" type="info" :bordered="false" style="margin-bottom:12px">
              暂无告警联动规则。添加规则后，当源设备产生告警时，系统将自动执行指定动作（如停止目标设备）。
            </n-alert>
            <n-data-table :columns="alarmRuleColumns" :data="alarmRules" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" title="设备兼容性验证">
            <n-space vertical>
              <n-form :model="validateForm" label-placement="left" label-width="100" inline>
                <n-form-item label="设备ID">
                  <n-select v-model:value="validateForm.device_id" :options="elDeviceOptions" filterable placeholder="选择或输入设备ID" style="width:220px" />
                </n-form-item>
                <n-form-item label="协议">
                  <n-input v-model:value="validateForm.protocol" placeholder="如 modbus_tcp" style="width:140px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="validateDevice" :loading="validating">验证兼容性</n-button>
                </n-form-item>
              </n-form>
              <n-alert v-if="validateResult" :type="validateResult.compatible ? 'success' : 'error'" :bordered="false">
                <div style="font-weight:600;margin-bottom:4px">
                  {{ validateResult.compatible ? '设备兼容' : '设备不兼容' }}
                </div>
                <div v-if="validateResult.warnings && validateResult.warnings.length > 0" style="margin-top:4px">
                  <div style="font-weight:500;color:#f59e0b">警告:</div>
                  <ul style="margin:4px 0;padding-left:20px">
                    <li v-for="w in validateResult.warnings" :key="w">{{ w }}</li>
                  </ul>
                </div>
                <div v-if="validateResult.errors && validateResult.errors.length > 0" style="margin-top:4px">
                  <div style="font-weight:500;color:#ef4444">错误:</div>
                  <ul style="margin:4px 0;padding-left:20px">
                    <li v-for="e in validateResult.errors" :key="e">{{ e }}</li>
                  </ul>
                </div>
                <div v-if="validateResult.protocol_result" style="margin-top:4px;font-size:12px;color:#94a3b8">
                  协议验证: {{ validateResult.protocol_result }}
                </div>
                <div v-if="validateResult.data_type_results" style="margin-top:4px;font-size:12px;color:#94a3b8">
                  数据类型: {{ JSON.stringify(validateResult.data_type_results) }}
                </div>
              </n-alert>
            </n-space>
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="edgelite-import" tab="EdgeLite 导入">
        <n-card size="small">
          <n-space vertical>
            <n-alert type="info" :bordered="false">
              导入 EdgeLite 设备配置，自动生成仿真设备。支持批量导入设备列表。
            </n-alert>
            <n-input v-model:value="edgeLiteJson" type="textarea" :rows="10"
              placeholder='粘贴 EdgeLite 设备配置 JSON...' />
            <n-button type="primary" @click="importEdgeLite" :loading="importing">导入</n-button>
          </n-space>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="pygbsentry" tab="PyGBSentry 对接">
        <n-card size="small">
          <n-space vertical>
            <n-alert type="info" :bordered="false">
              导入 PyGBSentry 摄像头配置，自动生成 GB28181 仿真设备并注册到视频平台。
            </n-alert>
            <n-input v-model:value="pygbsentryJson" type="textarea" :rows="10"
              placeholder='粘贴 PyGBSentry 摄像头配置 JSON...' />
            <n-button type="primary" @click="importPyGBSentry" :loading="importing">导入</n-button>
          </n-space>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="sdk" tab="SDK 示例">
        <n-card size="small">
          <template #header>
            <span>ProtoForge SDK 代码示例</span>
          </template>
          <template #header-extra>
            <n-button-group size="tiny">
              <n-button v-for="(_, lang) in sdkExamples" :key="lang"
                :type="sdkLang === lang ? 'primary' : 'default'"
                @click="sdkLang = lang">
                {{ {python:'Python',csharp:'C#',java:'Java',go:'Go'}[lang] || lang }}
              </n-button>
            </n-button-group>
          </template>
          <n-code :language="sdkLang" :code="sdkExamples[sdkLang] || ''" />
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="showPipelineModal" preset="card" title="联调链路验证" style="width:780px">
      <n-space vertical size="large" v-if="pipelineResult">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0">
          <div v-for="(step, idx) in pipelineSteps" :key="idx" style="display:flex;align-items:center;gap:4px">
            <div :style="{
              width:'36px',height:'36px',borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',
              fontSize:'15px',fontWeight:600,
              background: getStepStatus(idx) === 'success' ? '#10b981' : getStepStatus(idx) === 'error' ? '#ef4444' : '#64748b',
              color:'#fff'
            }">
              <svg v-if="getStepStatus(idx) === 'success'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              <svg v-else-if="getStepStatus(idx) === 'error'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              <span v-else>{{ idx + 1 }}</span>
            </div>
            <div>
              <div style="font-size:13px;font-weight:500">{{ step.label }}</div>
              <div style="font-size:11px;color:#94a3b8">{{ getStepDesc(idx) }}</div>
            </div>
            <svg v-if="idx < pipelineSteps.length - 1" viewBox="0 0 24 24" width="20" height="20"
              fill="none" stroke="#94a3b8" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
          </div>
        </div>

        <n-card v-if="pipelineResult.data_comparison && pipelineResult.data_comparison.length > 0"
          size="small" title="数据对比 (ProtoForge vs EdgeLite)">
          <n-data-table :columns="comparisonColumns" :data="pipelineResult.data_comparison"
            :bordered="false" size="small" />
        </n-card>

        <n-card v-if="pipelineResult?.steps?.collect?.data"
          size="small" title="EdgeLite 采集数据">
          <n-descriptions label-placement="left" :column="2" bordered size="small">
            <n-descriptions-item v-for="(val, key) in pipelineResult.steps.collect.data" :key="key" :label="key">
              {{ val }}
            </n-descriptions-item>
          </n-descriptions>
        </n-card>

        <n-alert v-if="pipelineResult.skipped" type="warning" :bordered="false">
          未配置 EdgeLite 网关地址。请编辑设备，在协议配置中填写 EdgeLite网关地址、用户名和密码。
        </n-alert>
        <n-alert v-else-if="pipelineResult.ok" type="success" :bordered="false">
          联调链路验证通过！EdgeLite 已成功连接 ProtoForge 并采集到数据。
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.auth?.ok === false" type="error" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">认证失败</div>
          <div>{{ pipelineResult?.steps?.auth?.error || '认证失败' }}</div>
          <div style="margin-top:4px;font-size:12px;color:#94a3b8">请检查 EdgeLite 网关地址是否正确、用户名密码是否正确</div>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.register?.ok === false" type="warning" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">设备未在 EdgeLite 注册</div>
          <div>需要先将设备配置推送到 EdgeLite，EdgeLite 才能连接 ProtoForge 采集数据</div>
          <n-button type="primary" size="small" style="margin-top:8px" @click="pushFromPipeline" :loading="pipelinePushLoading">
            推送注册到 EdgeLite
          </n-button>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.connect?.ok === false" type="error" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">EdgeLite 无法连接 ProtoForge</div>
          <div style="white-space:pre-line">{{ pipelineResult?.steps?.connect?.error || '连接失败' }}</div>
          <div v-if="pipelineResult?.steps?.connect?.driver_config" style="margin-top:8px;padding:8px;background:rgba(0,0,0,0.04);border-radius:4px;font-size:12px">
            <div style="font-weight:500;margin-bottom:4px">driver_config (EdgeLite 用此配置连接 ProtoForge):</div>
            <code style="white-space:pre-wrap">{{ JSON.stringify(pipelineResult.steps.connect.driver_config, null, 2) }}</code>
          </div>
          <div v-if="!pipelineResult.steps.connect.driver_host || pipelineResult.steps.connect.driver_host === ''" style="margin-top:8px">
            <n-button size="small" type="primary" @click="$router.push('/settings')">前往设置 ProtoForge 地址</n-button>
          </div>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.collect?.ok === false" type="warning" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">EdgeLite 未能采集到数据</div>
          <div>{{ pipelineResult.steps.collect.error }}</div>
          <div style="margin-top:4px;font-size:12px;color:#94a3b8">设备已注册且在线，但 EdgeLite 采集数据失败，请检查测点配置和采集间隔</div>
        </n-alert>
      </n-space>
      <n-space v-else-if="pipelineLoading" vertical align="center" style="padding:40px 0">
        <n-spin size="large" />
        <n-text depth="3">正在验证联调链路...</n-text>
      </n-space>
      <template #action>
        <n-button @click="showPipelineModal = false">关闭</n-button>
        <n-button type="primary" @click="rerunPipeline" :loading="pipelineLoading">重新验证</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="showAddAlarmModal" preset="card" title="添加告警联动规则" style="width:560px">
      <n-form :model="alarmForm" label-placement="left" label-width="120">
        <n-form-item label="规则ID">
          <n-input v-model:value="alarmForm.rule_id" placeholder="如 alarm-stop-001" />
        </n-form-item>
        <n-form-item label="源设备ID">
          <n-input v-model:value="alarmForm.source_device_id" placeholder="产生告警的设备ID" />
        </n-form-item>
        <n-form-item label="告警级别">
          <n-select v-model:value="alarmForm.alarm_severity" :options="severityOptions" />
        </n-form-item>
        <n-form-item label="执行动作">
          <n-select v-model:value="alarmForm.action" :options="actionOptions" />
        </n-form-item>
        <n-form-item label="目标设备ID">
          <n-input v-model:value="alarmForm.target_device_id" placeholder="被控制的设备ID" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="alarmForm.enabled" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="cancelAddAlarm">取消</n-button>
          <n-button type="primary" @click="addAlarmRule" :loading="addingAlarm">添加</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEdgelitePointsModal" preset="card" title="EdgeLite 采集测点" style="width:600px">
      <n-spin :show="loadingElPoints">
        <n-data-table v-if="edgelitePoints.length > 0"
          :columns="edgelitePointColumns" :data="edgelitePoints" :bordered="false" size="small" />
        <n-empty v-else description="暂无采集数据" />
      </n-spin>
      <template #action>
        <n-button @click="showEdgelitePointsModal = false">关闭</n-button>
      </template>
    </n-modal>

    <template v-if="importResults.length > 0">
      <div class="pf-section-title" style="font-size:16px;margin-top:16px">导入结果</div>
      <n-data-table :columns="resultColumns" :data="importResults" :bordered="false" size="small"
        :pagination="{ pageSize: 10 }" />
    </template>
  </n-space>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { NSpace, NTabs, NTabPane, NCard, NInput, NButton, NButtonGroup, NAlert, NDataTable, NCode,
  NForm, NFormItem, NTag, NModal, NSpin, NDescriptions, NDescriptionsItem, NText, NGrid, NGi,
  NSelect, NSwitch, NPopconfirm, NEmpty, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import config from '../config.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()
const edgeLiteJson = ref('')
const pygbsentryJson = ref('')
const importing = ref(false)
const importResults = ref([])

const elConfig = ref({ url: '', username: 'admin', password: '' })
const testingConn = ref(false)
const connResult = ref(null)
const loadingDevices = ref(false)
const batchPipelineLoading = ref(false)
const showPipelineModal = ref(false)
const pipelineResult = ref(null)
const pipelineLoading = ref(false)
const pipelinePushLoading = ref(false)
const pipelineDeviceId = ref('')

const allDevices = ref([])

const intStatus = ref({ connection_state: 'disconnected' })
const intMetrics = ref({})
const loadingStatusCache = ref(false)
const deviceStatusCache = ref([])
const loadingBackhaul = ref(false)
const backhaulData = ref([])
const backhaulDeviceId = ref('')
const loadingProtocols = ref(false)
const protocolMappings = ref([])

const loadingAlarmRules = ref(false)
const alarmRules = ref([])
const showAddAlarmModal = ref(false)
const addingAlarm = ref(false)
const alarmForm = ref({ rule_id: '', source_device_id: '', alarm_severity: 'critical', action: 'stop_device', target_device_id: '', enabled: true })

const validateForm = ref({ device_id: '', protocol: '' })
const validating = ref(false)
const validateResult = ref(null)

const msgForm = ref({ type: 'sync', payloadJson: '' })
const sendingMsg = ref(false)
const msgResult = ref(null)
const msgTypeOptions = [
  { label: '同步 (sync)', value: 'sync' },
  { label: '心跳 (heartbeat)', value: 'heartbeat' },
  { label: '状态查询 (status_query)', value: 'status_query' },
  { label: '重新连接 (reconnect)', value: 'reconnect' },
  { label: '刷新配置 (reload_config)', value: 'reload_config' },
]

const showEdgelitePointsModal = ref(false)
const loadingElPoints = ref(false)
const edgelitePoints = ref([])
const edgelitePointColumns = [
  { title: '测点', key: 'name', width: 120 },
  { title: '值', key: 'value', width: 120 },
  { title: '质量', key: 'quality', width: 80 },
  { title: '时间戳', key: 'timestamp', width: 180 },
]

const severityOptions = [
  { label: '严重 (critical)', value: 'critical' },
  { label: '重要 (major)', value: 'major' },
  { label: '一般 (minor)', value: 'minor' },
  { label: '提示 (info)', value: 'info' },
]
const actionOptions = [
  { label: '停止设备', value: 'stop_device' },
  { label: '启动设备', value: 'start_device' },
  { label: '注入故障', value: 'inject_fault' },
  { label: '调整生成器', value: 'adjust_generator' },
  { label: '仅记录日志', value: 'log_only' },
]

const pipelineSteps = [
  { label: '认证', color: '#6366f1', key: 'auth' },
  { label: '注册', color: '#3b82f6', key: 'register' },
  { label: '连接', color: '#f59e0b', key: 'connect' },
  { label: '采集', color: '#10b981', key: 'collect' },
  { label: '验证', color: '#8b5cf6', key: 'verify' },
]

const EL_UNSUPPORTED_PROTOCOLS = new Set(config.edgeLite.unsupportedProtocols)

const elDevices = computed(() => {
  return allDevices.value.filter(d => {
    const cfg = d.protocol_config || {}
    if (cfg.edgelite_url) return true
    if (cfg.edgelite_enabled) return true
    if (!EL_UNSUPPORTED_PROTOCOLS.has(d.protocol)) return true
    return false
  }).map(d => {
    const cfg = d.protocol_config || {}
    return {
      ...d,
      edgelite_url: cfg.edgelite_url || '',
      collect_interval: cfg.collect_interval || 5,
    }
  })
})

const elDeviceOptions = computed(() => {
  return allDevices.value.map(d => ({ label: `${d.name || d.id} (${d.protocol})`, value: d.id }))
})

const resultColumns = [
  { title: '设备ID', key: 'id', width: 180 },
  { title: '名称', key: 'name', width: 180 },
  { title: '协议', key: 'protocol', width: 100 },
  { title: '状态', key: 'status', width: 80 },
]

const comparisonColumns = [
  { title: '测点', key: 'point', width: 120 },
  { title: 'ProtoForge值', key: 'protoforge_value', width: 140 },
  { title: 'EdgeLite值', key: 'edgelite_value', width: 140 },
  {
    title: '匹配', key: 'match', width: 80,
    render: (row) => {
      if (row.match === null || row.match === undefined) return h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => '无数据')
      return row.match
        ? h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => '匹配')
        : h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => '不一致')
    }
  },
]

const deviceColumns = [
  { title: '设备', key: 'name', width: 150, render: (row) => h('div', {}, [
    h('div', { style: 'font-weight:500' }, row.name || row.id),
    h('div', { style: 'font-size:11px;color:#94a3b8' }, row.id),
  ]) },
  { title: '协议', key: 'protocol', width: 110, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => row.protocol) },
  {
    title: '本地状态', key: 'status', width: 90,
    render: (row) => h(NTag, {
      type: row.status === 'online' ? 'success' : 'default', size: 'tiny', bordered: false
    }, () => row.status === 'online' ? '在线' : '离线')
  },
  {
    title: 'EdgeLite', key: 'edgelite_status', width: 100,
    render: (row) => {
      const s = row._el_status
      if (!s) return h(NText, { depth: 3, style: 'font-size:12px' }, () => '未查询')
      if (s === 'error') return h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => '错误')
      if (s === 'not_registered') return h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => '未注册')
      if (s === 'online') return h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => '在线')
      if (s === 'offline') return h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => '离线')
      return h(NTag, { size: 'tiny', bordered: false }, () => s)
    }
  },
  { title: '采集间隔', key: 'collect_interval', width: 80, render: (row) => `${row.collect_interval || 5}s` },
  {
    title: '操作', key: 'actions', width: 400,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => pushDevice(row.id) }, () => '推送注册'),
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => startCollect(row.id) }, () => '启动采集'),
      h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => stopCollect(row.id) }, () => '停止采集'),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => readEdgelitePoints(row.id) }, () => '读测点'),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => openPipeline(row.id) }, () => '验证链路'),
      h(NButton, { size: 'tiny', type: 'error', secondary: true, onClick: () => removeFromEdgelite(row.id) }, () => '移除'),
    ])
  },
]

const statusCacheColumns = [
  { title: '设备ID', key: 'device_id', width: 180 },
  { title: '状态', key: 'status', width: 100, render: (row) => {
    const map = { online: 'success', offline: 'error' }
    return h(NTag, { size: 'tiny', type: map[row.status] || 'default', bordered: false }, () => row.status || '未知')
  }},
  { title: '协议', key: 'protocol', width: 120 },
  { title: '最后更新', key: 'last_updated', width: 180 },
]

const backhaulColumns = [
  { title: '设备ID', key: 'device_id', width: 160 },
  { title: '测点', key: 'point_name', width: 120 },
  { title: '值', key: 'value', width: 120 },
  { title: '时间戳', key: 'timestamp', width: 180 },
]

const protocolMapColumns = [
  { title: '源协议', key: 'source_protocol', width: 160 },
  { title: '目标协议', key: 'target_protocol', width: 160 },
  { title: '驱动类型', key: 'driver_type', width: 140 },
  { title: '状态', key: 'status', width: 100, render: (row) => {
    const m = { ok: ['success', '可用'], available: ['success', '可用'], unsupported: ['warning', '不支持'], target_unavailable: ['warning', '目标不可用'], unknown: ['default', '未知'], disabled: ['default', '已禁用'] }
    const [t, l] = m[row.status] || ['info', row.status || '未知']
    return h(NTag, { size: 'tiny', type: t, bordered: false }, () => l)
  }},
]

const alarmRuleColumns = [
  { title: '规则ID', key: 'rule_id', width: 150 },
  { title: '源设备', key: 'source_device_id', width: 150 },
  {
    title: '告警级别', key: 'alarm_severity', width: 100,
    render: (row) => {
      const map = { critical: 'error', major: 'warning', minor: 'info', info: 'default' }
      return h(NTag, { size: 'tiny', type: map[row.alarm_severity] || 'default', bordered: false }, () => row.alarm_severity)
    }
  },
  { title: '动作', key: 'action', width: 120 },
  { title: '目标设备', key: 'target_device_id', width: 150 },
  {
    title: '状态', key: 'enabled', width: 80,
    render: (row) => h(NTag, { size: 'tiny', type: row.enabled ? 'success' : 'default', bordered: false }, () => row.enabled ? '启用' : '禁用')
  },
  {
    title: '操作', key: 'actions', width: 100,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => deleteAlarmRule(row.rule_id) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => '删除'),
      default: () => `确定删除规则 "${row.rule_id}" 吗？`,
    })
  },
]

const sdkLang = ref('python')
const sdkExamples = config.sdk.examples
let _batchPollTimer = null

async function loadIntStatus() {
  try {
    intStatus.value = await api.getIntegrationStatus()
  } catch (e) {
    message.error('加载集成状态失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadIntMetrics() {
  try {
    intMetrics.value = await api.getIntegrationMetrics()
  } catch (e) {
    message.error('加载集成指标失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadDeviceStatusCache() {
  loadingStatusCache.value = true
  try {
    const res = await api.getDeviceStatusCache()
    const raw = res.devices || res
    if (Array.isArray(raw)) {
      deviceStatusCache.value = raw
    } else if (raw && typeof raw === 'object') {
      deviceStatusCache.value = Object.entries(raw)
        .filter(([_, status]) => status !== null && status !== undefined)
        .map(([device_id, status]) => ({
          device_id,
          status: typeof status === 'object' ? (status.status || 'unknown') : status,
          protocol: typeof status === 'object' ? (status.protocol || '') : '',
          last_updated: typeof status === 'object' ? (status.last_updated || '') : '',
        }))
    } else {
      deviceStatusCache.value = []
    }
  } catch (e) {
    message.error('加载设备状态失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingStatusCache.value = false }
}

async function loadBackhaulData() {
  loadingBackhaul.value = true
  try {
    const params = {}
    if (backhaulDeviceId.value) params.device_id = backhaulDeviceId.value
    const res = await api.getBackhaulData(params)
    if (res && typeof res === 'object' && Array.isArray(res.data)) {
      backhaulData.value = res.data
    } else if (Array.isArray(res)) {
      backhaulData.value = res
    } else {
      backhaulData.value = []
    }
  } catch (e) {
    message.error('加载回传数据失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingBackhaul.value = false }
}

async function loadProtocolMappings() {
  loadingProtocols.value = true
  try {
    const res = await api.getIntegrationProtocols()
    const pmap = res.protocol_map || {}
    if (pmap && typeof pmap === 'object') {
      protocolMappings.value = Object.entries(pmap)
        .filter(([_, target]) => target !== null && target !== undefined)
        .map(([source, target]) => ({
          source_protocol: source,
          target_protocol: typeof target === 'string' ? target : target.protocol || '',
          driver_type: typeof target === 'object' ? target.driver || '' : '',
          status: typeof target === 'object' ? target.status || 'unknown' : (target ? 'available' : 'unsupported'),
        }))
    } else {
      protocolMappings.value = []
    }
  } catch (e) {
    message.error('加载协议映射失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingProtocols.value = false }
}

async function loadAlarmRules() {
  loadingAlarmRules.value = true
  try {
    const res = await api.getAlarmRules()
    alarmRules.value = res || []
  } catch (e) {
    message.error('加载告警规则失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingAlarmRules.value = false }
}

function cancelAddAlarm() {
  showAddAlarmModal.value = false
  alarmForm.value = { rule_id: '', source_device_id: '', alarm_severity: 'critical', action: 'stop_device', target_device_id: '', enabled: true }
}

async function addAlarmRule() {
  if (!alarmForm.value.rule_id || !alarmForm.value.source_device_id || !alarmForm.value.target_device_id) {
    message.warning('请填写规则ID、源设备ID和目标设备ID')
    return
  }
  addingAlarm.value = true
  try {
    await api.addAlarmRule(alarmForm.value)
    showAddAlarmModal.value = false
    alarmForm.value = { rule_id: '', source_device_id: '', alarm_severity: 'critical', action: 'stop_device', target_device_id: '', enabled: true }
    message.success('告警规则已添加')
    await loadAlarmRules()
  } catch (e) {
    message.error('添加失败: ' + (e.response?.data?.detail || e.message))
  } finally { addingAlarm.value = false }
}

async function deleteAlarmRule(ruleId) {
  try {
    await api.deleteAlarmRule(ruleId)
    message.success('规则已删除')
    await loadAlarmRules()
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function validateDevice() {
  if (!validateForm.value.device_id) {
    message.warning('请输入设备ID')
    return
  }
  validating.value = true
  validateResult.value = null
  try {
    const dev = allDevices.value.find(d => d.id === validateForm.value.device_id)
    const payload = {
      device_id: validateForm.value.device_id,
      protocol: validateForm.value.protocol || (dev ? dev.protocol : ''),
      points: dev ? (dev.points || []) : [],
      config: dev ? (dev.protocol_config || {}) : {},
    }
    validateResult.value = await api.validateDeviceCompatibility(payload)
  } catch (e) {
    validateResult.value = { compatible: false, errors: [e.response?.data?.detail || e.message], warnings: [] }
  } finally { validating.value = false }
}

async function loadElConfig() {
  try {
    const settings = await api.getSettings()
    elConfig.value = {
      url: settings.edgelite_url || '',
      username: settings.edgelite_username || 'admin',
      password: (settings.edgelite_password && settings.edgelite_password !== '***') ? settings.edgelite_password : '',
    }
  } catch (e) {
    message.warning('加载 EdgeLite 配置失败，使用默认值')
  }
}

async function testConnection() {
  if (!elConfig.value.url) { message.warning('请填写 EdgeLite 地址'); return }
  testingConn.value = true
  try {
    connResult.value = await api.testEdgeliteConnection(elConfig.value)
    if (connResult.value.ok) {
      try {
        const syncPayload = {
          edgelite_url: elConfig.value.url,
          edgelite_username: elConfig.value.username,
        }
        if (elConfig.value.password) {
          syncPayload.edgelite_password = elConfig.value.password
        }
        await api.updateSettings(syncPayload)
      } catch (e) {
        message.warning('EdgeLite 配置同步到系统设置失败，请手动保存')
      }
    }
  } catch (e) {
    connResult.value = { ok: false, error: e.response?.data?.detail || e.message }
  } finally { testingConn.value = false }
}

async function loadDevices() {
  loadingDevices.value = true
  try {
    const devs = await api.getDevices()
    allDevices.value = (devs || []).map(d => ({ ...d, _el_status: null }))
  } catch (e) { message.error('加载设备失败: ' + (e.response?.data?.detail || e.message)) }
  finally { loadingDevices.value = false }
}

async function pushDevice(deviceId) {
  try {
    const res = await api.pushToEdgelite(deviceId)
    if (res.skipped) {
      const reason = res.reason || ''
      if (reason.includes('not supported') || reason.includes('不支持')) { message.warning('EdgeLite 不支持该协议，无法推送'); return }
      message.warning('该设备未配置 EdgeLite 地址'); return
    }
    if (!res.ok) {
      const errMsg = res.error || '未知错误'
      const hint = res.suggestion ? ` (${res.suggestion})` : ''
      message.error('推送失败: ' + errMsg + hint)
      return
    }
    const dc = res.driver_config
    const dcHint = dc ? ` (连接地址: ${dc.host || dc.url || ''}:${dc.port || ''})` : ''
    message.success((res.action === 'created' ? '设备已注册到 EdgeLite' : '设备配置已更新') + dcHint)
    await checkStatus(deviceId)
  } catch (e) {
    message.error('推送失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function removeFromEdgelite(deviceId) {
  dialog.warning({
    title: '确认移除设备',
    content: `将从 EdgeLite 移除设备 ${deviceId}，移除后 EdgeLite 将停止采集该设备数据。确定继续？`,
    positiveText: '移除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await api.removeDeviceFromEdgelite(deviceId)
        if (res.skipped) { message.warning('该设备未配置 EdgeLite 地址'); return }
        if (!res.ok) { message.error('移除失败: ' + (res.error || '未知错误')); return }
        message.success('设备已从 EdgeLite 移除')
        await checkStatus(deviceId)
      } catch (e) {
        message.error('移除失败: ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function startCollect(deviceId) {
  try {
    await api.startIntegrationDevice(deviceId)
    message.success('采集已启动')
  } catch (e) {
    message.error('启动采集失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function stopCollect(deviceId) {
  try {
    await api.stopIntegrationDevice(deviceId)
    message.success('采集已停止')
  } catch (e) {
    message.error('停止采集失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function checkStatus(deviceId) {
  try {
    const res = await api.getEdgeliteDeviceStatus(deviceId)
    const dev = allDevices.value.find(d => d.id === deviceId)
    if (dev) dev._el_status = res.ok ? res.status : 'error'
    if (!res.ok) {
      message.error('查询失败: ' + (res.error || '未知错误'))
    } else if (res.status === 'not_registered') message.info('设备未在 EdgeLite 注册')
    else if (res.status === 'online') message.success('EdgeLite 设备在线')
    else if (res.status === 'offline') message.warning('EdgeLite 设备离线（驱动未连接到 ProtoForge）')
    else message.info(`EdgeLite 状态: ${res.status}`)
  } catch (e) {
    message.error('查询失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function openPipeline(deviceId) {
  pipelineDeviceId.value = deviceId
  pipelineResult.value = null
  showPipelineModal.value = true
  await runPipeline()
}

async function runPipeline() {
  pipelineLoading.value = true
  pipelineResult.value = null
  try {
    pipelineResult.value = await api.verifyEdgelitePipeline(pipelineDeviceId.value)
  } catch (e) {
    pipelineResult.value = {
      ok: false,
      steps: { auth: { ok: false, error: e.response?.data?.detail || e.message } }
    }
  } finally { pipelineLoading.value = false }
}

function rerunPipeline() { runPipeline() }

async function pushFromPipeline() {
  pipelinePushLoading.value = true
  try {
    const res = await api.pushToEdgelite(pipelineDeviceId.value)
    if (res.skipped) {
      message.warning('该设备未配置 EdgeLite 地址')
    } else if (res.ok) {
      const dc = res.driver_config
      const dcHint = dc ? ` (连接地址: ${dc.host || dc.url || ''}:${dc.port || ''})` : ''
      message.success((res.action === 'created' ? '设备已注册到 EdgeLite' : '设备配置已更新') + dcHint)
      await runPipeline()
    } else {
      const errMsg = res.error || '未知错误'
      const hint = res.suggestion ? ` (${res.suggestion})` : ''
      message.error('推送失败: ' + errMsg + hint)
    }
  } catch (e) {
    message.error('推送失败: ' + (e.response?.data?.detail || e.message))
  } finally { pipelinePushLoading.value = false }
}

function getStepStatus(idx) {
  if (!pipelineResult.value || !pipelineResult.value.steps) return 'pending'
  const key = pipelineSteps[idx].key
  if (key === 'verify') {
    const collectOk = pipelineResult.value.steps.collect?.ok
    const hasComparison = pipelineResult.value.data_comparison?.length > 0
    if (collectOk && hasComparison) return 'success'
    if (collectOk && !hasComparison) return 'warning'
    return 'pending'
  }
  const step = pipelineResult.value.steps[key]
  if (!step) return 'pending'
  return step.ok ? 'success' : 'error'
}

function getStepDesc(idx) {
  if (!pipelineResult.value || !pipelineResult.value.steps) return ''
  const key = pipelineSteps[idx].key
  if (key === 'verify') {
    const comp = pipelineResult.value.data_comparison
    if (comp && comp.length > 0) {
      const matched = comp.filter(c => c.match).length
      return `${matched}/${comp.length} 测点匹配`
    }
    return '等待采集数据'
  }
  const step = pipelineResult.value.steps[key]
  if (!step) return '未执行'
  if (step.ok) {
    if (key === 'auth') return '认证成功'
    if (key === 'register') return `已注册 (状态: ${step.status || 'ok'})`
    if (key === 'connect') return `已连接 (状态: ${step.status || 'ok'})`
    if (key === 'collect') return step.has_real_data || (step.data && Object.keys(step.data).length > 0) ? '已采集到数据' : '暂无实际数据'
    return '成功'
  }
  return step.error || '失败'
}

async function batchPushAndVerify() {
  if (elDevices.value.length === 0) { message.warning('没有配置了 EdgeLite 的设备'); return }
  batchPipelineLoading.value = true
  try {
    const deviceIds = elDevices.value.map(d => d.id)
    const res = await api.batchPushDevices({ device_ids: deviceIds })
    const pushed = res.success ?? 0
    const failed = res.failure ?? 0
    message.info(`已推送 ${pushed} 个设备${failed ? `，${failed} 个失败` : ''}，等待 EdgeLite 采集数据...`)

    const pollInterval = (elConfig.value.collect_interval || 5) * 1000
    const maxPolls = 6
    let pollCount = 0

    await new Promise((resolve) => {
      _batchPollTimer = setInterval(async () => {
        pollCount++
        let verified = 0
        for (const dev of elDevices.value) {
          try {
            const statusRes = await api.getEdgeliteDeviceStatus(dev.id)
            dev._el_status = statusRes.ok ? statusRes.status : 'error'
            if (statusRes.ok && statusRes.status === 'online') verified++
          } catch (e) { /* ignore individual status errors during polling */ }
        }
        if (verified > 0 || pollCount >= maxPolls) {
          clearInterval(_batchPollTimer)
          _batchPollTimer = null
          message.success(`推送: ${pushed} 个, EdgeLite在线: ${verified} 个` + (failed ? `, 失败: ${failed} 个` : ''))
          resolve()
        }
      }, pollInterval)
    })
  } catch (e) {
    message.error('批量推送失败: ' + (e.response?.data?.detail || e.message))
  } finally { batchPipelineLoading.value = false }
}

async function readEdgelitePoints(deviceId) {
  showEdgelitePointsModal.value = true
  loadingElPoints.value = true
  edgelitePoints.value = []
  try {
    const res = await api.readEdgeliteDevicePoints(deviceId)
    if (Array.isArray(res)) {
      edgelitePoints.value = res
    } else if (res && Array.isArray(res.points)) {
      edgelitePoints.value = res.points
    } else if (res && !res.ok) {
      message.error('读取EdgeLite测点失败: ' + (res.error || '未知错误'))
    } else {
      edgelitePoints.value = []
    }
  } catch (e) {
    message.error('读取EdgeLite测点失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingElPoints.value = false }
}

async function importEdgeLite() {
  if (!edgeLiteJson.value.trim()) {
    message.warning('请输入 EdgeLite 设备配置 JSON')
    return
  }
  importing.value = true
  try {
    const config = JSON.parse(edgeLiteJson.value)
    const res = await api.importEdgelite(config)
    importResults.value = res.devices || []
    message.success(`成功导入 ${res.imported || 0} 个设备`)
  } catch (e) {
    if (e instanceof SyntaxError) message.error('JSON 格式错误: ' + e.message)
    else message.error('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally { importing.value = false }
}

async function importPyGBSentry() {
  if (!pygbsentryJson.value.trim()) {
    message.warning('请输入 PyGBSentry 摄像头配置 JSON')
    return
  }
  importing.value = true
  try {
    const config = JSON.parse(pygbsentryJson.value)
    const res = await api.importPygbsentry(config)
    importResults.value = res.devices || []
    message.success(`成功导入 ${res.imported || 0} 个设备`)
  } catch (e) {
    if (e instanceof SyntaxError) message.error('JSON 格式错误: ' + e.message)
    else message.error('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally { importing.value = false }
}

async function sendIntMessage() {
  if (!msgForm.value.type) {
    message.warning('请选择或输入消息类型')
    return
  }
  sendingMsg.value = true
  msgResult.value = null
  try {
    let payload = {}
    if (msgForm.value.payloadJson.trim()) {
      try {
        payload = JSON.parse(msgForm.value.payloadJson)
      } catch {
        message.error('载荷 JSON 格式错误')
        sendingMsg.value = false
        return
      }
    }
    msgResult.value = await api.sendIntegrationMessage(msgForm.value.type, payload)
    message.success('消息已发送')
  } catch (e) {
    msgResult.value = { status: 'error', error: e.response?.data?.detail || e.message }
  } finally { sendingMsg.value = false }
}

onMounted(() => {
  loadElConfig()
  loadDevices()
  loadIntStatus()
  loadIntMetrics()
  loadAlarmRules()
  loadProtocolMappings()
})

onUnmounted(() => {
  if (_batchPollTimer) {
    clearInterval(_batchPollTimer)
    _batchPollTimer = null
  }
})
</script>
