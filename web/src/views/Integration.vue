<template>
  <n-space vertical>
    <div class="pf-section-title">{{ t('integration.title') }}</div>
    <div class="pf-section-desc">{{ t('integration.subtitle') }}</div>

    <n-tabs type="card">
      <n-tab-pane name="edgelite-pipeline" :tab="t('integration.edgelitePipeline')">
        <n-space vertical size="large">
          <n-card size="small" :title="t('integration.edgeliteConnectionConfig')">
            <template #header-extra>
              <n-button text type="info" size="tiny" @click="$router.push('/settings')">{{ t('integration.manageInSettings') }}</n-button>
            </template>
            <n-space vertical>
              <n-form :model="elConfig" label-placement="left" label-width="140" inline>
                <n-form-item :label="t('integration.edgeliteAddress')">
                  <n-input v-model:value="elConfig.url" placeholder="http://edgelite-host:8100" style="width:260px" />
                </n-form-item>
                <n-form-item :label="t('integration.username')">
                  <n-input v-model:value="elConfig.username" placeholder="admin" style="width:120px" />
                </n-form-item>
                <n-form-item :label="t('integration.password')">
                  <n-input v-model:value="elConfig.password" type="password" show-password-on="click" :placeholder="t('integration.password')" style="width:120px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="testConnection" :loading="testingConn">
                    {{ t('integration.testConnection') }}
                  </n-button>
                </n-form-item>
              </n-form>
              <n-alert v-if="connResult" :type="connResult.ok ? 'success' : 'error'" :bordered="false" style="margin-top:4px">
                <template v-if="connResult.ok">
                  {{ t('integration.connectionSuccess', { version: connResult.version || t('common.unknown'), count: connResult.devices ?? 0 }) }}
                </template>
                <template v-else>
                  {{ t('integration.connectionFailed', { error: connResult.error }) }}
                </template>
              </n-alert>
            </n-space>
          </n-card>

          <n-card size="small" :title="t('integration.pipelineExplanation')">
            <n-space vertical size="small">
              <n-alert type="info" :bordered="false">
                <div style="font-weight:600;margin-bottom:8px">{{ t('integration.fullPipeline5Steps') }}</div>
                <div style="line-height:2">
                  <n-text code>1. {{ t('integration.stepRegister') }}</n-text> {{ t('integration.stepRegisterDesc') }}<br/>
                  <n-text code>2. {{ t('integration.stepConnect') }}</n-text> {{ t('integration.stepConnectDesc') }}<br/>
                  <n-text code>3. {{ t('integration.stepCollect') }}</n-text> {{ t('integration.stepCollectDesc') }}<br/>
                  <n-text code>4. {{ t('integration.stepVerify') }}</n-text> {{ t('integration.stepVerifyDesc') }}<br/>
                  <n-text code>5. {{ t('integration.stepMonitor') }}</n-text> {{ t('integration.stepMonitorDesc') }}
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

          <n-card size="small" :title="t('integration.deviceIntegrationStatus')">
            <template #header-extra>
              <n-space>
                <n-button size="small" @click="loadDevices" :loading="loadingDevices">{{ t('common.refresh') }}</n-button>
                <n-button size="small" type="primary" @click="batchPushAndVerify" :loading="batchPipelineLoading">
                  {{ t('integration.batchPushAndVerify') }}
                </n-button>
              </n-space>
            </template>
            <n-data-table :columns="deviceColumns" :data="elDevices" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" :row-key="row => row.id" />
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="integration-status" :tab="t('integration.integrationStatus')">
        <n-space vertical size="large">
          <n-grid :cols="4" :x-gap="12" :y-gap="12">
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.connectionStatus') }}</div>
                <n-tag :type="intStatus.connection_state === 'connected' ? 'success' : 'error'" size="small" :bordered="false">
                  {{ intStatus.connection_state === 'connected' ? t('integration.connected') : t('integration.disconnected') }}
                </n-tag>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.pushSuccess') }}</div>
                <div style="font-size:24px;font-weight:600;color:#6366f1">{{ intMetrics.push_success_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.pushFailed') }}</div>
                <div style="font-size:24px;font-weight:600;color:#ef4444">{{ intMetrics.push_failure_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.avgPushLatency') }}</div>
                <div style="font-size:24px;font-weight:600;color:#f59e0b">{{ intMetrics.avg_push_latency_ms || 0 }}<span style="font-size:12px;font-weight:400">ms</span></div>
              </n-card>
            </n-gi>
          </n-grid>

          <n-grid :cols="4" :x-gap="12" :y-gap="12">
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.backhaulData') }}</div>
                <div style="font-size:24px;font-weight:600;color:#3b82f6">{{ intMetrics.data_backhaul_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.syncEvents') }}</div>
                <div style="font-size:24px;font-weight:600;color:#8b5cf6">{{ intMetrics.sync_event_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.alarmForward') }}</div>
                <div style="font-size:24px;font-weight:600;color:#ef4444">{{ intMetrics.alarm_forward_count || 0 }}</div>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" style="text-align:center">
                <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{{ t('integration.lastHeartbeat') }}</div>
                <div style="font-size:13px;font-weight:500;color:#64748b">{{ formatDate(intMetrics.last_heartbeat_at) || t('common.none') }}</div>
              </n-card>
            </n-gi>
          </n-grid>

          <n-card size="small" :title="t('integration.deviceStatusCache')">
            <template #header-extra>
              <n-button size="small" @click="loadDeviceStatusCache" :loading="loadingStatusCache">{{ t('common.refresh') }}</n-button>
            </template>
            <n-data-table :columns="statusCacheColumns" :data="deviceStatusCache" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" :title="t('integration.backhaulData')">
            <template #header-extra>
              <n-space size="small">
                <n-input v-model:value="backhaulDeviceId" size="small" :placeholder="t('integration.deviceIdFilter')" clearable style="width:180px" />
                <n-button size="small" @click="loadBackhaulData" :loading="loadingBackhaul">{{ t('common.query') }}</n-button>
              </n-space>
            </template>
            <n-data-table :columns="backhaulColumns" :data="backhaulData" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" :title="t('integration.protocolMapping')">
            <template #header-extra>
              <n-button size="small" @click="loadProtocolMappings" :loading="loadingProtocols">{{ t('common.refresh') }}</n-button>
            </template>
            <n-data-table :columns="protocolMapColumns" :data="protocolMappings" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" :title="t('integration.sendMessage')">
            <n-space vertical>
              <n-alert type="info" :bordered="false">
                {{ t('integration.sendMessageDesc') }}
              </n-alert>
              <n-form :model="msgForm" label-placement="left" label-width="100" inline>
                <n-form-item :label="t('integration.messageType')">
                  <n-select v-model:value="msgForm.type" :options="msgTypeOptions" filterable tag :placeholder="t('integration.selectOrInputMsgType')" style="width:220px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="sendIntMessage" :loading="sendingMsg">{{ t('common.send') }}</n-button>
                </n-form-item>
              </n-form>
              <n-input v-model:value="msgForm.payloadJson" type="textarea" :rows="3"
                :placeholder="t('integration.msgPayloadPlaceholder')" />
              <n-alert v-if="msgResult" :type="msgResult.status === 'ok' ? 'success' : 'error'" :bordered="false">
                <div style="font-weight:600;margin-bottom:4px">{{ msgResult.status === 'ok' ? t('common.sendSuccess') : t('common.sendFailed') }}</div>
                <div v-if="msgResult.data" style="font-size:12px;color:#94a3b8">{{ JSON.stringify(msgResult.data) }}</div>
                <div v-if="msgResult.error" style="font-size:12px;color:#ef4444">{{ msgResult.error }}</div>
              </n-alert>
            </n-space>
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="alarm-rules" :tab="t('integration.alarmLinkage')">
        <n-space vertical size="large">
          <n-card size="small" :title="t('integration.alarmRules')">
            <template #header-extra>
              <n-space size="small">
                <n-button size="small" @click="loadAlarmRules" :loading="loadingAlarmRules">{{ t('common.refresh') }}</n-button>
                <n-button size="small" type="primary" @click="showAddAlarmModal = true">{{ t('integration.addRule') }}</n-button>
              </n-space>
            </template>
            <n-alert v-if="alarmRules.length === 0 && !loadingAlarmRules" type="info" :bordered="false" style="margin-bottom:12px">
              {{ t('integration.noAlarmRules') }}
            </n-alert>
            <n-data-table :columns="alarmRuleColumns" :data="alarmRules" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
          </n-card>

          <n-card size="small" :title="t('integration.deviceCompatibility')">
            <n-space vertical>
              <n-form :model="validateForm" label-placement="left" label-width="100" inline>
                <n-form-item :label="t('integration.deviceId')">
                  <n-select v-model:value="validateForm.device_id" :options="elDeviceOptions" filterable :placeholder="t('integration.selectOrInputDeviceId')" style="width:220px" />
                </n-form-item>
                <n-form-item :label="t('integration.protocol')">
                  <n-input v-model:value="validateForm.protocol" :placeholder="t('integration.protocolPlaceholder')" style="width:140px" />
                </n-form-item>
                <n-form-item>
                  <n-button type="primary" @click="validateDevice" :loading="validating">{{ t('integration.verifyCompatibility') }}</n-button>
                </n-form-item>
              </n-form>
              <n-alert v-if="validateResult" :type="validateResult.compatible ? 'success' : 'error'" :bordered="false">
                <div style="font-weight:600;margin-bottom:4px">
                  {{ validateResult.compatible ? t('integration.deviceCompatible') : t('integration.deviceIncompatible') }}
                </div>
                <div v-if="validateResult.warnings && validateResult.warnings.length > 0" style="margin-top:4px">
                  <div style="font-weight:500;color:#f59e0b">{{ t('integration.warnings') }}</div>
                  <ul style="margin:4px 0;padding-left:20px">
                    <li v-for="w in validateResult.warnings" :key="w">{{ w }}</li>
                  </ul>
                </div>
                <div v-if="validateResult.errors && validateResult.errors.length > 0" style="margin-top:4px">
                  <div style="font-weight:500;color:#ef4444">{{ t('integration.errors') }}</div>
                  <ul style="margin:4px 0;padding-left:20px">
                    <li v-for="e in validateResult.errors" :key="e">{{ e }}</li>
                  </ul>
                </div>
                <div v-if="validateResult.protocol_result" style="margin-top:4px;font-size:12px;color:#94a3b8">
                  {{ t('integration.protocolVerify') }}: {{ validateResult.protocol_result }}
                </div>
                <div v-if="validateResult.data_type_results" style="margin-top:4px;font-size:12px;color:#94a3b8">
                  {{ t('integration.dataType') }}: {{ JSON.stringify(validateResult.data_type_results) }}
                </div>
              </n-alert>
            </n-space>
          </n-card>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="edgelite-import" :tab="t('integration.edgeliteImport')">
        <n-card size="small">
          <n-space vertical>
            <n-alert type="info" :bordered="false">
              {{ t('integration.edgeliteImportDesc') }}
            </n-alert>
            <n-input v-model:value="edgeLiteJson" type="textarea" :rows="10"
              :placeholder="t('integration.pasteEdgeliteJson')" />
            <n-button type="primary" @click="importEdgeLite" :loading="importing">{{ t('common.import') }}</n-button>
          </n-space>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="pygbsentry" :tab="t('integration.pygbsentryIntegration')">
        <n-card size="small">
          <n-space vertical>
            <n-alert type="info" :bordered="false">
              {{ t('integration.pygbsentryImportDesc') }}
            </n-alert>
            <n-input v-model:value="pygbsentryJson" type="textarea" :rows="10"
              :placeholder="t('integration.pastePygbsentryJson')" />
            <n-button type="primary" @click="importPyGBSentry" :loading="importing">{{ t('common.import') }}</n-button>
          </n-space>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="sdk" :tab="t('integration.sdkExamples')">
        <n-card size="small">
          <template #header>
            <span>{{ t('integration.sdkCodeExamples') }}</span>
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

    <n-modal v-model:show="showPipelineModal" preset="card" :title="t('integration.pipelineVerify')" style="width:780px">
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
          size="small" :title="t('integration.dataComparison')">
          <n-data-table :columns="comparisonColumns" :data="pipelineResult.data_comparison"
            :bordered="false" size="small" />
        </n-card>

        <n-card v-if="pipelineResult?.steps?.collect?.data"
          size="small" :title="t('integration.edgeliteCollectedData')">
          <n-descriptions label-placement="left" :column="2" bordered size="small">
            <n-descriptions-item v-for="(val, key) in pipelineResult.steps.collect.data" :key="key" :label="key">
              {{ val }}
            </n-descriptions-item>
          </n-descriptions>
        </n-card>

        <n-alert v-if="pipelineResult.skipped" type="warning" :bordered="false">
          {{ t('integration.edgeliteNotConfiguredDetail') }}
        </n-alert>
        <n-alert v-else-if="pipelineResult.ok" type="success" :bordered="false">
          {{ t('integration.pipelineVerifySuccess') }}
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.auth?.ok === false" type="error" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">{{ t('integration.authFailed') }}</div>
          <div>{{ pipelineResult?.steps?.auth?.error || t('integration.authFailed') }}</div>
          <div style="margin-top:4px;font-size:12px;color:#94a3b8">{{ t('integration.authFailedDesc') }}</div>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.register?.ok === false" type="warning" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">{{ t('integration.deviceNotRegistered') }}</div>
          <div>{{ t('integration.deviceNotRegisteredDesc') }}</div>
          <n-button type="primary" size="small" style="margin-top:8px" @click="pushFromPipeline" :loading="pipelinePushLoading">
            {{ t('integration.pushRegisterToEdgeLite') }}
          </n-button>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.connect?.ok === false" type="error" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">{{ t('integration.edgeliteCannotConnect') }}</div>
          <div style="white-space:pre-line">{{ pipelineResult?.steps?.connect?.error || t('integration.connectionFailed') }}</div>
          <div v-if="pipelineResult?.steps?.connect?.driver_config" style="margin-top:8px;padding:8px;background:rgba(0,0,0,0.04);border-radius:4px;font-size:12px">
            <div style="font-weight:500;margin-bottom:4px">{{ t('integration.driverConfigLabel') }}</div>
            <code style="white-space:pre-wrap">{{ JSON.stringify(pipelineResult.steps.connect.driver_config, null, 2) }}</code>
          </div>
          <div v-if="!pipelineResult.steps.connect.driver_host || pipelineResult.steps.connect.driver_host === ''" style="margin-top:8px">
            <n-button size="small" type="primary" @click="$router.push('/settings')">{{ t('integration.goToSettingsProtoforge') }}</n-button>
          </div>
        </n-alert>
        <n-alert v-else-if="pipelineResult.steps?.collect?.ok === false" type="warning" :bordered="false">
          <div style="font-weight:600;margin-bottom:4px">{{ t('integration.edgeliteNoData') }}</div>
          <div>{{ pipelineResult.steps.collect.error }}</div>
          <div style="margin-top:4px;font-size:12px;color:#94a3b8">{{ t('integration.edgeliteNoDataDesc') }}</div>
        </n-alert>
      </n-space>
      <n-space v-else-if="pipelineLoading" vertical align="center" style="padding:40px 0">
        <n-spin size="large" />
        <n-text depth="3">{{ t('integration.verifyingPipeline') }}</n-text>
      </n-space>
      <template #action>
        <n-button @click="showPipelineModal = false">{{ t('common.close') }}</n-button>
        <n-button type="primary" @click="rerunPipeline" :loading="pipelineLoading">{{ t('integration.reverify') }}</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="showAddAlarmModal" preset="card" :title="t('integration.addAlarmRule')" style="width:560px">
      <n-form :model="alarmForm" label-placement="left" label-width="120">
        <n-form-item :label="t('integration.ruleId')">
          <n-input v-model:value="alarmForm.rule_id" :placeholder="t('integration.ruleIdPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('integration.sourceDeviceId')">
          <n-select v-model:value="alarmForm.source_device_id" :options="alarmDeviceOptions" :placeholder="t('integration.sourceDeviceIdPlaceholder')" clearable filterable />
        </n-form-item>
        <n-form-item :label="t('integration.alarmSeverity')">
          <n-select v-model:value="alarmForm.alarm_severity" :options="severityOptions" />
        </n-form-item>
        <n-form-item :label="t('integration.executeAction')">
          <n-select v-model:value="alarmForm.action" :options="actionOptions" />
        </n-form-item>
        <n-form-item :label="t('integration.targetDeviceId')">
          <n-select v-model:value="alarmForm.target_device_id" :options="alarmDeviceOptions" :placeholder="t('integration.targetDeviceIdPlaceholder')" clearable filterable />
        </n-form-item>
        <n-form-item :label="t('integration.enabled')">
          <n-switch v-model:value="alarmForm.enabled" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space>
          <n-button @click="cancelAddAlarm">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="addAlarmRule" :loading="addingAlarm">{{ t('common.add') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEdgelitePointsModal" preset="card" :title="t('integration.edgeliteCollectedPoints')" style="width:600px">
      <n-spin :show="loadingElPoints">
        <n-data-table v-if="edgelitePoints.length > 0"
          :columns="edgelitePointColumns" :data="edgelitePoints" :bordered="false" size="small" />
        <n-empty v-else :description="t('integration.noCollectedData')" />
      </n-spin>
      <template #action>
        <n-button @click="showEdgelitePointsModal = false">{{ t('common.close') }}</n-button>
      </template>
    </n-modal>

    <template v-if="importResults.length > 0">
      <div class="pf-section-title" style="font-size:16px;margin-top:16px">{{ t('integration.importResults') }}</div>
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
const { t, formatDate } = useI18n()
const dialog = useDialog()
const edgeLiteJson = ref('')
const pygbsentryJson = ref('')
const importing = ref(false)
const importResults = ref([])

const elConfig = ref({ url: '', username: '', password: '' })  // FIXED: removed hardcoded 'admin' default
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
// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const msgTypeOptions = computed(() => [
  { label: t('integration.sync'), value: 'sync' },
  { label: t('integration.heartbeat'), value: 'heartbeat' },
  { label: t('integration.statusQuery'), value: 'status_query' },
  { label: t('integration.reconnect'), value: 'reconnect' },
  { label: t('integration.reloadConfig'), value: 'reload_config' },
])

const showEdgelitePointsModal = ref(false)
const loadingElPoints = ref(false)
const edgelitePoints = ref([])
// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const edgelitePointColumns = computed(() => [
  { title: t('integration.pointName'), key: 'name', width: 120 },
  { title: t('integration.pointValue'), key: 'value', width: 120 },
  { title: t('integration.pointQuality'), key: 'quality', width: 80 },
  { title: t('integration.pointTimestamp'), key: 'timestamp', width: 180 },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const severityOptions = computed(() => [
  { label: t('integration.severityCritical'), value: 'critical' },
  { label: t('integration.severityMajor'), value: 'major' },
  { label: t('integration.severityMinor'), value: 'minor' },
  { label: t('integration.severityInfo'), value: 'info' },
])
// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const actionOptions = computed(() => [
  { label: t('integration.actionStopDevice'), value: 'stop_device' },
  { label: t('integration.actionStartDevice'), value: 'start_device' },
  { label: t('integration.actionInjectFault'), value: 'inject_fault' },
  { label: t('integration.actionAdjustGenerator'), value: 'adjust_generator' },
  { label: t('integration.actionLogOnly'), value: 'log_only' },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const pipelineSteps = computed(() => [
  { label: t('integration.pipelineAuth'), color: '#6366f1', key: 'auth' },
  { label: t('integration.pipelineRegister'), color: '#3b82f6', key: 'register' },
  { label: t('integration.pipelineConnect'), color: '#f59e0b', key: 'connect' },
  { label: t('integration.pipelineCollect'), color: '#10b981', key: 'collect' },
  { label: t('integration.pipelineVerify'), color: '#8b5cf6', key: 'verify' },
])

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

const alarmDeviceOptions = computed(() => {
  return allDevices.value.map(d => ({ label: `${d.name || d.id} (${d.protocol})`, value: d.id }))
})

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const resultColumns = computed(() => [
  { title: t('integration.deviceId'), key: 'id', width: 180 },
  { title: t('integration.nameCol'), key: 'name', width: 180 },
  { title: t('integration.protocol'), key: 'protocol', width: 100 },
  { title: t('integration.status'), key: 'status', width: 80 },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const comparisonColumns = computed(() => [
  { title: t('integration.pointName'), key: 'point', width: 120 },
  { title: t('integration.protoforgeValue'), key: 'protoforge_value', width: 140 },
  { title: t('integration.edgeliteValue'), key: 'edgelite_value', width: 140 },
  {
    title: t('integration.matchCol'), key: 'match', width: 80,
    render: (row) => {
      if (row.match === null || row.match === undefined) return h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => t('integration.noData'))
      return row.match
        ? h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => t('integration.matched'))
        : h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => t('integration.inconsistent'))
    }
  },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const deviceColumns = computed(() => [
  { title: t('integration.deviceCol'), key: 'name', width: 150, render: (row) => h('div', {}, [
    h('div', { style: 'font-weight:500' }, row.name || row.id),
    h('div', { style: 'font-size:11px;color:#94a3b8' }, row.id),
  ]) },
  { title: t('integration.protocol'), key: 'protocol', width: 110, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => row.protocol) },
  {
    title: t('integration.localStatus'), key: 'status', width: 90,
    render: (row) => h(NTag, {
      type: row.status === 'online' ? 'success' : 'default', size: 'tiny', bordered: false
    }, () => row.status === 'online' ? t('integration.online') : t('integration.offline'))
  },
  {
    title: 'EdgeLite', key: 'edgelite_status', width: 100,
    render: (row) => {
      const s = row._el_status
      if (!s) return h(NText, { depth: 3, style: 'font-size:12px' }, () => t('integration.notQueried'))
      if (s === 'error') return h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => t('integration.error'))
      if (s === 'not_registered') return h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => t('integration.notRegistered'))
      if (s === 'online') return h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => t('integration.online'))
      if (s === 'offline') return h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => t('integration.offline'))
      return h(NTag, { size: 'tiny', bordered: false }, () => s)
    }
  },
  { title: t('integration.collectInterval'), key: 'collect_interval', width: 80, render: (row) => `${row.collect_interval || 5}s` },
  {
    title: t('integration.actions'), key: 'actions', width: 400,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => pushDevice(row.id) }, () => t('integration.pushRegister')),
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => startCollect(row.id) }, () => t('integration.startCollect')),
      h(NButton, { size: 'tiny', type: 'warning', secondary: true, onClick: () => stopCollect(row.id) }, () => t('integration.stopCollect')),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => readEdgelitePoints(row.id) }, () => t('integration.readPoints')),
      h(NButton, { size: 'tiny', type: 'info', secondary: true, onClick: () => openPipeline(row.id) }, () => t('integration.verifyLink')),
      h(NButton, { size: 'tiny', type: 'error', secondary: true, onClick: () => removeFromEdgelite(row.id) }, () => t('integration.remove')),
    ])
  },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const statusCacheColumns = computed(() => [
  { title: t('integration.deviceId'), key: 'device_id', width: 180 },
  { title: t('integration.status'), key: 'status', width: 100, render: (row) => {
    const map = { online: 'success', offline: 'error' }
    return h(NTag, { size: 'tiny', type: map[row.status] || 'default', bordered: false }, () => row.status || t('common.unknown'))
  }},
  { title: t('integration.protocol'), key: 'protocol', width: 120 },
  { title: t('integration.lastUpdated'), key: 'last_updated', width: 180 },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const backhaulColumns = computed(() => [
  { title: t('integration.deviceId'), key: 'device_id', width: 160 },
  { title: t('integration.pointName'), key: 'point_name', width: 120 },
  { title: t('integration.pointValue'), key: 'value', width: 120 },
  { title: t('integration.pointTimestamp'), key: 'timestamp', width: 180 },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const protocolMapColumns = computed(() => [
  { title: t('integration.sourceProtocol'), key: 'source_protocol', width: 160 },
  { title: t('integration.targetProtocol'), key: 'target_protocol', width: 160 },
  { title: t('integration.driverType'), key: 'driver_type', width: 140 },
  { title: t('integration.status'), key: 'status', width: 100, render: (row) => {
    const m = { ok: ['success', t('integration.available')], available: ['success', t('integration.available')], unsupported: ['warning', t('integration.unsupported')], target_unavailable: ['warning', t('integration.targetUnavailable')], unknown: ['default', t('common.unknown')], disabled: ['default', t('integration.disabled')] }
    const [tp, lb] = m[row.status] || ['info', row.status || t('common.unknown')]
    return h(NTag, { size: 'tiny', type: tp, bordered: false }, () => lb)
  }},
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const alarmRuleColumns = computed(() => [
  { title: t('integration.ruleId'), key: 'rule_id', width: 150 },
  { title: t('integration.sourceDevice'), key: 'source_device_id', width: 150 },
  {
    title: t('integration.alarmSeverity'), key: 'alarm_severity', width: 100,
    render: (row) => {
      const map = { critical: 'error', major: 'warning', minor: 'info', info: 'default' }
      return h(NTag, { size: 'tiny', type: map[row.alarm_severity] || 'default', bordered: false }, () => row.alarm_severity)
    }
  },
  { title: t('integration.actionCol'), key: 'action', width: 120 },
  { title: t('integration.targetDevice'), key: 'target_device_id', width: 150 },
  {
    title: t('integration.status'), key: 'enabled', width: 80,
    render: (row) => h(NTag, { size: 'tiny', type: row.enabled ? 'success' : 'default', bordered: false }, () => row.enabled ? t('integration.enabled') : t('integration.disabled'))
  },
  {
    title: t('integration.actions'), key: 'actions', width: 100,
    render: (row) => h(NPopconfirm, { onPositiveClick: () => deleteAlarmRule(row.rule_id) }, {
      trigger: () => h(NButton, { size: 'tiny', type: 'error' }, () => t('common.delete')),
      default: () => t('integration.confirmDeleteRule', { id: row.rule_id }),
    })
  },
])

const sdkLang = ref('python')
const sdkExamples = config.sdk.examples
let _batchPollTimer = null

async function loadIntStatus() {
  try {
    intStatus.value = await api.getIntegrationStatus()
  } catch (e) {
    message.error(t('integration.loadIntStatusFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function loadIntMetrics() {
  try {
    intMetrics.value = await api.getIntegrationMetrics()
  } catch (e) {
    message.error(t('integration.loadIntMetricsFailed') + ': ' + (e.response?.data?.detail || e.message))
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
          // FIXED: typeof null === 'object' 陷阱 — 添加显式 null 检查
          status: (status && typeof status === 'object') ? (status.status || 'unknown') : status,
          protocol: (status && typeof status === 'object') ? (status.protocol || '') : '',
          last_updated: (status && typeof status === 'object') ? (status.last_updated || '') : '',
        }))
    } else {
      deviceStatusCache.value = []
    }
  } catch (e) {
    message.error(t('integration.loadStatusCacheFailed') + ': ' + (e.response?.data?.detail || e.message))
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
    message.error(t('integration.loadBackhaulFailed') + ': ' + (e.response?.data?.detail || e.message))
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
          // FIXED: typeof null === 'object' 陷阱 — 添加显式 null 检查
          target_protocol: typeof target === 'string' ? target : (target && typeof target === 'object' ? target.protocol || '' : ''),
          driver_type: target && typeof target === 'object' ? target.driver || '' : '',
          status: target && typeof target === 'object' ? target.status || 'unknown' : (target ? 'available' : 'unsupported'),
        }))
    } else {
      protocolMappings.value = []
    }
  } catch (e) {
    message.error(t('integration.loadProtocolMappingsFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loadingProtocols.value = false }
}

async function loadAlarmRules() {
  loadingAlarmRules.value = true
  try {
    const res = await api.getAlarmRules()
    alarmRules.value = res || []
  } catch (e) {
    message.error(t('integration.loadAlarmRulesFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loadingAlarmRules.value = false }
}

function cancelAddAlarm() {
  showAddAlarmModal.value = false
  alarmForm.value = { rule_id: '', source_device_id: '', alarm_severity: 'critical', action: 'stop_device', target_device_id: '', enabled: true }
}

async function addAlarmRule() {
  if (!alarmForm.value.rule_id || !alarmForm.value.source_device_id || !alarmForm.value.target_device_id) {
    message.warning(t('integration.fillRequired'))
    return
  }
  addingAlarm.value = true
  try {
    await api.addAlarmRule(alarmForm.value)
    showAddAlarmModal.value = false
    alarmForm.value = { rule_id: '', source_device_id: '', alarm_severity: 'critical', action: 'stop_device', target_device_id: '', enabled: true }
    message.success(t('integration.ruleAdded'))
    await loadAlarmRules()
  } catch (e) {
    message.error(t('integration.addFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { addingAlarm.value = false }
}

async function deleteAlarmRule(ruleId) {
  try {
    await api.deleteAlarmRule(ruleId)
    message.success(t('integration.ruleDeleted'))
    await loadAlarmRules()
  } catch (e) {
    message.error(t('integration.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function validateDevice() {
  if (!validateForm.value.device_id) {
    message.warning(t('integration.fillDeviceId'))
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
      url: (settings && settings.edgelite_url) || '',  // FIXED: null guard for settings response
      username: (settings && settings.edgelite_username) || '',  // FIXED: removed hardcoded 'admin' fallback
      password: (settings && settings.edgelite_password && settings.edgelite_password !== '***') ? settings.edgelite_password : '',
    }
  } catch (e) {
    message.warning(t('integration.loadEdgeliteConfigFailed'))
  }
}

async function testConnection() {
  if (!elConfig.value.url) { message.warning(t('integration.fillEdgeliteAddress')); return }
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
        message.warning(t('integration.configSyncFailed'))
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
  } catch (e) { message.error(t('integration.loadDeviceFailed') + ': ' + (e.response?.data?.detail || e.message)) }
  finally { loadingDevices.value = false }
}

async function pushDevice(deviceId) {
  dialog.info({
    title: t('integration.confirmPushDevice'),
    content: t('integration.confirmPushDeviceDesc'),
    positiveText: t('integration.push'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const res = await api.pushToEdgelite(deviceId)
        if (res.skipped) {
          const reason = res.reason || ''
          if (res.error_type === 'unsupported' || reason.includes('not supported') || reason.includes('NOT_SUPPORTED')) { message.warning(t('integration.protocolNotSupported')); return }
          message.warning(t('integration.deviceNotConfiguredEdgeLite')); return
        }
        if (!res.ok) {
          const errMsg = res.error || t('common.unknownError')
          const hint = res.suggestion ? ` (${res.suggestion})` : ''
          message.error(t('integration.pushFailed') + ': ' + errMsg + hint)
          return
        }
        const dc = res.driver_config || {}  // FIXED: guard against null driver_config
        const dcHint = dc ? ` (${t('integration.connectAddress')}: ${dc.host || dc.url || ''}:${dc.port || ''})` : ''
        message.success((res.action === 'created' ? t('integration.deviceRegistered') : t('integration.deviceConfigUpdated')) + dcHint)
        await checkStatus(deviceId)
      } catch (e) {
        message.error(t('integration.pushFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function removeFromEdgelite(deviceId) {
  dialog.warning({
    title: t('integration.confirmRemoveDevice'),
    content: t('integration.confirmRemoveDeviceDesc', { id: deviceId }),
    positiveText: t('integration.remove'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const res = await api.removeDeviceFromEdgelite(deviceId)
        if (res.skipped) { message.warning(t('integration.deviceNotConfiguredEdgeLite')); return }
        if (!res.ok) { message.error(t('integration.removeFailed') + ': ' + (res.error || t('common.unknownError'))); return }
        message.success(t('integration.deviceRemoved'))
        await checkStatus(deviceId)
      } catch (e) {
        message.error(t('integration.removeFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function startCollect(deviceId) {
  dialog.info({
    title: t('integration.confirmStartCollect'),
    content: t('integration.confirmStartCollectDesc'),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.startIntegrationDevice(deviceId)
        message.success(t('integration.collectStarted'))
      } catch (e) {
        message.error(t('integration.startCollectFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function stopCollect(deviceId) {
  dialog.warning({
    title: t('integration.confirmStopCollect'),
    content: t('integration.confirmStopCollectDesc'),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.stopIntegrationDevice(deviceId)
        message.success(t('integration.collectStopped'))
      } catch (e) {
        message.error(t('integration.stopCollectFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function checkStatus(deviceId) {
  try {
    const res = await api.getEdgeliteDeviceStatus(deviceId)
    const dev = allDevices.value.find(d => d.id === deviceId)
    if (dev) dev._el_status = res.ok ? res.status : 'error'
    if (!res.ok) {
      message.error(t('integration.queryFailed') + ': ' + (res.error || t('common.unknownError')))
    } else if (res.status === 'not_registered') message.info(t('integration.deviceNotRegistered'))
    else if (res.status === 'online') message.success(t('integration.edgeliteOnline'))
    else if (res.status === 'offline') message.warning(t('integration.edgeliteOffline'))
    else message.info(t('integration.edgeliteStatus', { status: res.status }))
  } catch (e) {
    message.error(t('integration.queryFailed') + ': ' + (e.response?.data?.detail || e.message))
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
      message.warning(t('integration.deviceNotConfiguredEdgeLite'))
    } else if (res.ok) {
      const dc = res.driver_config
      const dcHint = dc ? ` (${t('integration.connectAddress')}: ${dc.host || dc.url || ''}:${dc.port || ''})` : ''
      message.success((res.action === 'created' ? t('integration.deviceRegistered') : t('integration.deviceConfigUpdated')) + dcHint)
      await runPipeline()
    } else {
      const errMsg = res.error || t('common.unknownError')
      const hint = res.suggestion ? ` (${res.suggestion})` : ''
      message.error(t('integration.pushFailed') + ': ' + errMsg + hint)
    }
  } catch (e) {
    message.error(t('integration.pushFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { pipelinePushLoading.value = false }
}

function getStepStatus(idx) {
  if (!pipelineResult.value || !pipelineResult.value.steps) return 'pending'
  const key = pipelineSteps.value[idx].key
  if (key === 'verify') {
    const collectOk = pipelineResult.value.steps.collect?.ok
    const hasComparison = pipelineResult.value?.data_comparison?.length > 0  // FIXED: added null check for pipelineResult.value
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
  const key = pipelineSteps.value[idx].key
  if (key === 'verify') {
    const comp = pipelineResult.value.data_comparison
    if (comp && comp.length > 0) {
      const matched = comp.filter(c => c.match).length
      return t('integration.pointMatchCount', { matched, total: comp.length })
    }
    return t('integration.waitingForData')
  }
  const step = pipelineResult.value.steps[key]
  if (!step) return t('integration.notExecuted')
  if (step.ok) {
    if (key === 'auth') return t('integration.authSuccess')
    if (key === 'register') return t('integration.registeredStatus', { status: step.status || 'ok' })
    if (key === 'connect') return t('integration.connectedStatus', { status: step.status || 'ok' })
    if (key === 'collect') return step.has_real_data || (step.data && Object.keys(step.data).length > 0) ? t('integration.dataCollected') : t('integration.noRealData')
    return t('common.success')
  }
  return step.error || t('common.failed')
}

async function batchPushAndVerify() {
  if (elDevices.value.length === 0) { message.warning(t('integration.noEdgeliteDevices')); return }
  dialog.info({
    title: t('integration.confirmBatchPush'),
    content: t('integration.confirmBatchPushDesc', { count: elDevices.value.length }),
    positiveText: t('integration.push'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchPipelineLoading.value = true
  try {
    const deviceIds = elDevices.value.map(d => d.id)
    const res = await api.batchPushDevices({ device_ids: deviceIds })
    const pushed = res.success ?? 0
    const failed = res.failure ?? 0
    message.info(t('integration.pushedAndWait', { pushed, failed }))

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
          } catch (e) { console.warn('Status check failed for device %s:', dev.id, e.message) }  // FIXED: log instead of silently ignoring
        }
        if (verified > 0 || pollCount >= maxPolls) {
          clearInterval(_batchPollTimer)
          _batchPollTimer = null
          message.success(t('integration.batchPushResult', { pushed, verified, failed }))
          resolve()
        }
      }, pollInterval)
    })
  } catch (e) {
    message.error(t('integration.batchPushFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { batchPipelineLoading.value = false }
    }
  })
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
      message.error(t('integration.readPointsFailed') + ': ' + (res.error || t('common.unknownError')))
    } else {
      edgelitePoints.value = []
    }
  } catch (e) {
    message.error(t('integration.readPointsFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loadingElPoints.value = false }
}

async function importEdgeLite() {
  if (!edgeLiteJson.value.trim()) {
    message.warning(t('integration.fillEdgeliteJson'))
    return
  }
  let config
  try { config = JSON.parse(edgeLiteJson.value) }
  catch (e) { message.error(t('integration.jsonFormatError') + ': ' + e.message); return }
  const deviceCount = Array.isArray(config.devices) ? config.devices.length : (Array.isArray(config) ? config.length : 1)
  dialog.info({
    title: t('integration.confirmImportEdgelite'),
    content: t('integration.confirmImportEdgeliteDesc', { count: deviceCount }),
    positiveText: t('common.import'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      importing.value = true
      try {
        const res = await api.importEdgelite(config)
        importResults.value = res.devices || []
        message.success(t('integration.importSuccess', { count: res.imported || 0 }))
      } catch (e) {
        message.error(t('integration.importFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { importing.value = false }
    }
  })
}

async function importPyGBSentry() {
  if (!pygbsentryJson.value.trim()) {
    message.warning(t('integration.fillPygbsentryJson'))
    return
  }
  let config
  try { config = JSON.parse(pygbsentryJson.value) }
  catch (e) { message.error(t('integration.jsonFormatError') + ': ' + e.message); return }
  const deviceCount = Array.isArray(config.cameras) ? config.cameras.length : (Array.isArray(config) ? config.length : 1)
  dialog.info({
    title: t('integration.confirmImportPygbsentry'),
    content: t('integration.confirmImportPygbsentryDesc', { count: deviceCount }),
    positiveText: t('common.import'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      importing.value = true
      try {
        const res = await api.importPygbsentry(config)
        importResults.value = res.devices || []
        message.success(t('integration.importSuccess', { count: res.imported || 0 }))
      } catch (e) {
        message.error(t('integration.importFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { importing.value = false }
    }
  })
}

async function sendIntMessage() {
  if (!msgForm.value.type) {
    message.warning(t('integration.selectMsgType'))
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
        message.error(t('integration.payloadJsonError'))
        sendingMsg.value = false
        return
      }
    }
    msgResult.value = await api.sendIntegrationMessage(msgForm.value.type, payload)
    message.success(t('integration.messageSent'))
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
