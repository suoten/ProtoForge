<template>
  <div>
    <n-space vertical size="large">
      <n-space justify="space-between" align="center" class="pf-device-toolbar">
        <div>
          <div class="pf-section-title">{{ t('devices.title') }}</div>
          <div class="pf-section-desc">{{ t('devices.subtitle') }}</div>
        </div>
        <n-space align="center" size="small">
          <!-- 筛选 -->
          <n-select v-model:value="filterProtocol" :options="protocolOptions" :placeholder="t('devices.filterByProtocol')" clearable size="small" style="width:160px" />

          <!-- 批量操作区：选中时淡入，固定分区避免布局抖动 -->
          <transition name="pf-fade">
            <n-space v-if="selectedIds.length > 0" align="center" size="small" class="pf-batch-actions">
              <n-tag size="small" :bordered="false" type="info" round>{{ selectedIds.length }}</n-tag>
              <n-button size="small" type="primary" secondary @click="batchStart" :loading="batchLoading">
                <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
                {{ t('devices.batchStart') }}
              </n-button>
              <n-button size="small" type="warning" secondary @click="batchStop" :loading="batchLoading">
                <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
                {{ t('devices.batchStop') }}
              </n-button>
              <n-button size="small" type="error" secondary @click="batchDelete" :loading="batchLoading">
                <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></template>
                {{ t('devices.batchDelete') }}
              </n-button>
              <n-dropdown :options="batchMoreOptions" @select="onBatchMoreSelect" placement="bottom-end">
                <n-button size="small" tertiary :title="t('common.more')">
                  <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg></template>
                </n-button>
              </n-dropdown>
              <n-button size="small" quaternary @click="selectedIds = []">{{ t('common.cancel') }}</n-button>
            </n-space>
          </transition>

          <!-- 全局操作：全部启停（图标按钮组，悬浮提示） -->
          <n-button-group size="small">
            <n-button @click="startAllDevices" :loading="batchLoading" :title="t('devices.startAll')">
              <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></template>
            </n-button>
            <n-button @click="stopAllDevices" :loading="batchLoading" :title="t('devices.stopAll')">
              <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></template>
            </n-button>
          </n-button-group>

          <!-- 创建操作：split button，主按钮快速创建，下拉提供高级/批量 -->
          <n-button-group size="small">
            <n-button type="primary" @click="openQuickCreate">
              <template #icon><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></template>
              {{ t('devices.quickCreate') }}
            </n-button>
            <n-dropdown :options="createOptions" @select="onCreateSelect" trigger="click" placement="bottom-end">
              <n-button type="primary" :title="t('common.more')">
                <template #icon><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></template>
              </n-button>
            </n-dropdown>
          </n-button-group>
        </n-space>
      </n-space>

      <n-alert v-if="noProtocolRunning" type="warning" :bordered="false">
        <template #icon><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01"/></svg></template>
        {{ t('devices.noProtocolRunning') }}
        <n-button size="tiny" type="primary" @click="goProtocols" style="margin-left:8px">{{ t('devices.goStartProtocol') }}</n-button>
      </n-alert>

      <template v-if="dataLoading && devices.length === 0">
        <n-card v-for="i in 3" :key="i" size="small" style="margin-bottom:8px">
          <n-skeleton text :repeat="2" />
          <n-skeleton text style="width:60%" />
        </n-card>
      </template>
      <n-data-table v-else :columns="columns" :data="filteredDevices" :bordered="false"
        :pagination="{ pageSize: 15 }" :row-key="row => row.id" :loading="dataLoading"
        v-model:checked-row-keys="selectedIds" :single-line="false" />

      <EmptyState v-if="filteredDevices.length === 0 && !dataLoading"
        :title="t('devices.noDevices')"
        :description="t('devices.noDevicesDesc')"
        :actionText="t('devices.quickCreate')"
        actionIcon="M12 5v14M5 12h14"
        @action="openQuickCreate"
      />

      <n-modal v-model:show="showQuickCreateModal" preset="card" :title="t('devices.quickCreateDevice')" style="width:min(560px, 90vw)">
        <n-form ref="qcFormRef" :model="{ qcDeviceName, qcTemplateId }" :rules="qcRules" label-placement="top">
          <n-form-item :label="t('devices.selectDeviceTemplate')" path="qcTemplateId">
            <n-select v-model:value="qcTemplateId" :options="quickTemplateOptions" :placeholder="t('devices.searchTemplate')" filterable @update:value="onQcTemplateChange" />
          </n-form-item>
          <n-form-item :label="t('devices.nameYourDevice')" path="qcDeviceName">
            <n-input v-model:value="qcDeviceName" :placeholder="t('devices.deviceNamePlaceholder')" size="large" />
          </n-form-item>
          <n-text v-if="qcTemplateId" depth="3" style="font-size:12px;margin-bottom:8px;display:block">
            {{ t('devices.protocol') }}: {{ qcTemplateName }} | {{ t('devices.points') }}: {{ qcTemplatePoints }}
          </n-text>
          <!-- 协议配置：选择模板后自动加载，无配置时自动隐藏，不再单独成步 -->
          <div v-if="qcDeviceConfigFields.length > 0" style="margin-top:8px">
            <div style="font-weight:600;margin-bottom:8px;font-size:14px">{{ t('devices.config') }}</div>
            <n-form-item v-for="f in qcDeviceConfigFields" :key="f.key" :label="f.label" label-placement="left" label-width="140">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="qcProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="qcProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="qcProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
              <n-text v-if="f.description" depth="3" style="margin-left:8px;font-size:12px">{{ f.description }}</n-text>
            </n-form-item>
          </div>
        </n-form>
        <template #action>
          <n-space justify="end" style="width:100%">
            <n-button @click="showQuickCreateModal = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="doQuickCreate" :loading="qcLoading" :disabled="!qcTemplateId || !qcDeviceName">{{ t('devices.createAndStart') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showCreateModal" preset="card" :title="t('devices.advancedCreateDevice')" style="width:min(640px, 90vw)">
        <n-form ref="createFormRef" :model="newDevice" :rules="createRules" label-placement="left" label-width="80">
          <n-form-item :label="t('devices.deviceId')" path="id"><n-input v-model:value="newDevice.id" :placeholder="t('devices.deviceIdPlaceholder')" /></n-form-item>
          <n-form-item :label="t('devices.deviceName')" path="name"><n-input v-model:value="newDevice.name" :placeholder="t('devices.deviceNamePlaceholder2')" /></n-form-item>
          <n-form-item :label="t('devices.protocol')" path="protocol"><n-select v-model:value="newDevice.protocol" :options="protocolOptions.filter(o => o.value)" @update:value="onAdvancedProtocolChange" /></n-form-item>
          <n-form-item :label="t('devices.createFromTemplate')"><n-select v-model:value="selectedTemplate" :options="templateOptions" :placeholder="t('devices.selectTemplate')" clearable /></n-form-item>
        </n-form>
        <div v-if="advancedConfigFields.length > 0" style="margin-top:8px">
          <div style="font-weight:600;margin-bottom:8px;font-size:14px">{{ t('devices.protocolConfig') }}</div>
          <!-- GB28181 设备配置引导 -->
          <n-alert v-if="newDevice.protocol === 'gb28181'" type="warning" :bordered="false" style="margin-bottom:8px">
            <div style="font-size:13px;line-height:1.6">
              <div style="font-weight:600;margin-bottom:4px">GB28181 设备注册到视频平台，必须填写以下关键字段：</div>
              <div>• <b>Upstream SIP Server Address</b>：您的视频平台 IP 地址（必填，否则不会注册）</div>
              <div>• <b>Upstream SIP Port</b>：视频平台 SIP 信令端口（默认 5060）</div>
              <div>• <b>Upstream SIP Server ID</b>：视频平台的 20 位国标编码</div>
              <div>• <b>Device National Standard Code</b>：本设备的 20 位国标编码（类型 132=IPC）</div>
              <div>• <b>SIP Password</b>：如果平台启用了 Digest 认证，填写认证密码</div>
            </div>
          </n-alert>
          <n-form :model="advancedProtocolConfig" label-placement="left" label-width="140">
            <n-form-item v-for="f in advancedConfigFields" :key="f.key" :label="f.label">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="advancedProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="advancedProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="advancedProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
            </n-form-item>
          </n-form>
        </div>
        <template #action>
          <n-space>
            <n-button @click="showCreateModal = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="createDevice" :loading="creating">{{ t('common.create') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showEditModal" preset="card" :title="t('devices.editDevice')" style="width:min(640px, 90vw)">
        <n-form ref="editFormRef" :model="editDevice" :rules="editRules" label-placement="left" label-width="80">
          <n-form-item :label="t('devices.deviceName')" path="name"><n-input v-model:value="editDevice.name" /></n-form-item>
          <n-form-item :label="t('devices.protocol')"><n-input :value="editDevice.protocol" disabled /></n-form-item>
        </n-form>
        <div v-if="editConfigFields.length > 0" style="margin-top:8px">
          <div style="font-weight:600;margin-bottom:8px;font-size:14px">{{ t('devices.protocolConfig') }}</div>
          <n-form :model="editProtocolConfig" label-placement="left" label-width="140">
            <n-form-item v-for="f in editConfigFields" :key="f.key" :label="f.label">
              <template v-if="f.type === 'select'">
                <n-select v-model:value="editProtocolConfig[f.key]" :options="f.options.map(o => ({ label: String(o), value: o }))" />
              </template>
              <template v-else-if="f.type === 'number'">
                <n-input-number v-model:value="editProtocolConfig[f.key]" :min="f.min" :max="f.max" style="width:100%" />
              </template>
              <template v-else>
                <n-input v-model:value="editProtocolConfig[f.key]" :placeholder="f.default || ''" />
              </template>
            </n-form-item>
          </n-form>
        </div>
        <template #action>
          <n-space>
            <n-button @click="showEditModal = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="saveEditDevice" :loading="saving">{{ t('common.save') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showPointsModal" preset="card" :title="t('devices.devicePoints')" style="width:min(700px, 90vw)">
        <n-space v-if="currentViewDeviceInfo" align="center" size="small" style="margin-bottom:8px">
          <n-tag :type="currentViewDeviceInfo.status === 'online' ? 'success' : currentViewDeviceInfo.status === 'error' ? 'error' : 'default'" size="small" :bordered="false">{{ currentViewDeviceInfo.status || 'offline' }}</n-tag>
          <n-text depth="3" style="font-size:12px">{{ currentViewDeviceInfo.name }} ({{ currentViewDeviceInfo.protocol }})</n-text>
        </n-space>
        <n-data-table :columns="pointColumns" :data="currentPoints" :bordered="false" size="small" />
        <n-space vertical style="margin-top:12px">
          <n-text strong style="font-size:13px">{{ t('devices.quickWritePoint') }}</n-text>
          <n-space align="center" size="small">
            <n-select v-model:value="writePointName" :options="currentPoints.map(p => ({ label: p.name, value: p.name }))" :placeholder="t('devices.selectPoint')" style="width:160px" size="small" />
            <n-input v-model:value="writePointValue" :placeholder="t('devices.inputValue')" style="width:120px" size="small" />
            <n-button type="primary" size="small" @click="writeDevicePointQuick" :loading="writeLoading">{{ t('devices.write') }}</n-button>
          </n-space>
        </n-space>
      </n-modal>

      <n-modal v-model:show="showGuideModal" preset="card" :title="t('devices.connectionGuide')" style="width:min(680px, 90vw)">
        <div v-if="guideData">
          <n-space vertical size="large">
            <n-alert v-if="guideData.protocol_status !== 'running'" type="warning" :bordered="false">
              <div style="font-weight:600;margin-bottom:4px">{{ t('devices.protocolNotRunning') }}</div>
              <div>{{ t('devices.protocolNotRunningDesc') }}</div>
            </n-alert>
            <n-alert :type="guideData.mode === 'client' ? 'warning' : 'info'" :bordered="false">
              <template #icon>
                <svg v-if="guideData.mode === 'server'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/></svg>
                <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4 M10 17l5-5-5-5 M15 12H3"/></svg>
              </template>
              <div style="font-weight:600;margin-bottom:4px">{{ guideData.mode_label }}</div>
              <div>{{ guideData.mode_desc }}</div>
            </n-alert>

            <div v-if="guideData.mode === 'server'">
              <div style="font-weight:600;margin-bottom:8px">{{ guideData.connect_hint }}</div>
              <n-card size="small" embedded>
                <div v-for="(val, key) in (guideData.connection_info || {})" :key="key" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                  <n-text depth="3">{{ key }}</n-text>
                  <n-text code>{{ val }}</n-text>
                </div>
              </n-card>
            </div>

            <div v-if="guideData.mode === 'client'">
              <div style="font-weight:600;margin-bottom:8px">{{ guideData.connect_hint }}</div>
              <n-card size="small" embedded>
                <div v-for="(val, key) in (guideData.connection_info || {})" :key="key" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                  <n-text depth="3">{{ key }}</n-text>
                  <n-text code>{{ val }}</n-text>
                </div>
              </n-card>
            </div>

            <div v-if="guideData.code_examples && Object.keys(guideData.code_examples).length > 0">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <div style="font-weight:600">{{ t('devices.codeExamples') }}</div>
                <n-button-group size="tiny">
                  <n-button v-for="(_, lang) in (guideData.code_examples || {})" :key="lang"
                    :type="guideLang === lang ? 'primary' : 'default'"
                    @click="guideLang = lang">
                    {{ {python:'Python',csharp:'C#',java:'Java',go:'Go'}[lang] || lang }}
                  </n-button>
                </n-button-group>
              </div>
              <n-card size="small" embedded>
                <pre style="margin:0;white-space:pre-wrap;font-size:13px;line-height:1.6;font-family:Consolas,Monaco,monospace">{{ (guideData.code_examples || {})[guideLang] || guideData.code_example }}</pre>
              </n-card>
            </div>
            <div v-else-if="guideData.code_example">
              <div style="font-weight:600;margin-bottom:8px">{{ t('devices.codeExamples') }}</div>
              <n-card size="small" embedded>
                <pre style="margin:0;white-space:pre-wrap;font-size:13px;line-height:1.6;font-family:Consolas,Monaco,monospace">{{ guideData.code_example }}</pre>
              </n-card>
            </div>
          </n-space>
        </div>
        <template #action>
          <n-button @click="showGuideModal = false">{{ t('common.close') }}</n-button>
          <n-button type="primary" @click="copyGuide">{{ t('devices.copyCode') }}</n-button>
        </template>
      </n-modal>

      <n-modal v-model:show="showBatchCreateModal" preset="card" :title="t('devices.batchCreateDevice')" style="width:min(640px, 90vw)">
        <n-space vertical>
          <n-alert type="info" :bordered="false">{{ t('devices.batchCreateDesc') }}</n-alert>
          <n-form ref="batchFormRef" :model="batchForm" :rules="batchRules" label-placement="left" label-width="100">
            <n-form-item :label="t('devices.template')" path="templateId">
              <n-select v-model:value="batchForm.templateId" :options="quickTemplateOptions" :placeholder="t('devices.selectDeviceTemplate')" filterable />
            </n-form-item>
            <n-form-item :label="t('devices.count')">
              <n-input-number v-model:value="batchForm.count" :min="1" :max="50" style="width:100%" />
            </n-form-item>
            <n-form-item :label="t('devices.namePrefix')" path="namePrefix">
              <n-input v-model:value="batchForm.namePrefix" :placeholder="t('devices.namePrefixPlaceholder')" />
            </n-form-item>
            <n-form-item :label="t('devices.idPrefix')" path="idPrefix">
              <n-input v-model:value="batchForm.idPrefix" :placeholder="t('devices.idPrefixPlaceholder')" />
            </n-form-item>
          </n-form>
        </n-space>
        <template #action>
          <n-space>
            <n-button @click="showBatchCreateModal = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="doBatchCreate" :loading="batchCreating">{{ t('devices.batchCreate') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showPipelineModal" preset="card" :title="t('devices.pipelineVerify')" style="width:min(780px, 90vw)">
        <n-space vertical size="large" v-if="pipelineResult">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0">
            <div v-for="(step, idx) in pipelineSteps" :key="idx" style="display:flex;align-items:center;gap:4px">
              <div :style="{
                width:'36px',height:'36px',borderRadius:'50%',display:'flex',alignItems:'center',justifyContent:'center',
                fontSize:'15px',fontWeight:600,
                background: getPipelineStepStatus(idx) === 'success' ? '#10b981' : getPipelineStepStatus(idx) === 'error' ? '#ef4444' : '#64748b',
                color:'#fff'
              }">
                <svg v-if="getPipelineStepStatus(idx) === 'success'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                <svg v-else-if="getPipelineStepStatus(idx) === 'error'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                <span v-else>{{ idx + 1 }}</span>
              </div>
              <div>
                <div style="font-size:13px;font-weight:500">{{ step.label }}</div>
                <div style="font-size:11px;color:#94a3b8">{{ getPipelineStepDesc(idx) }}</div>
              </div>
              <svg v-if="idx < pipelineSteps.length - 1" viewBox="0 0 24 24" width="20" height="20"
                fill="none" stroke="#94a3b8" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            </div>
          </div>

          <n-card v-if="pipelineResult.data_comparison && pipelineResult.data_comparison.length > 0"
            size="small" :title="t('devices.dataComparison')">
            <n-data-table :columns="pipelineComparisonColumns" :data="pipelineResult.data_comparison"
              :bordered="false" size="small" />
          </n-card>

          <n-alert v-if="pipelineResult.skipped" type="warning" :bordered="false">
            <div style="font-weight:600;margin-bottom:4px">{{ t('devices.edgeliteNotConfigured') }}</div>
            <div>{{ pipelineResult.suggestion || t('devices.edgeliteNotConfiguredDesc') }}</div>
            <n-button type="primary" size="small" style="margin-top:8px" @click="$router.push('/settings')">
              {{ t('devices.goToSettings') }}
            </n-button>
          </n-alert>
          <n-alert v-else-if="pipelineResult.ok" type="success" :bordered="false">
            {{ t('devices.pipelineVerifySuccess') }}
          </n-alert>
          <n-alert v-else-if="pipelineResult.steps?.auth?.ok === false" type="error" :bordered="false">
            <div style="font-weight:600;margin-bottom:4px">{{ t('devices.authFailed') }}</div>
            <div>{{ pipelineResult.steps.auth.error }}</div>
            <div style="margin-top:4px;font-size:12px;color:#94a3b8">{{ pipelineResult.steps.auth.suggestion || t('devices.authFailedDesc') }}</div>
            <n-button type="primary" size="small" style="margin-top:8px" @click="$router.push('/settings')">
              {{ t('devices.goToSettings') }}
            </n-button>
          </n-alert>
          <n-alert v-else-if="pipelineResult.steps?.register?.ok === false" type="warning" :bordered="false">
            <div style="font-weight:600;margin-bottom:4px">{{ t('devices.deviceNotRegistered') }}</div>
            <div>{{ t('devices.deviceNotRegisteredDesc') }}</div>
            <n-button type="primary" size="small" style="margin-top:8px" @click="pushFromPipeline" :loading="pipelinePushLoading">
              {{ t('devices.pushRegisterToEdgeLite') }}
            </n-button>
          </n-alert>
          <n-alert v-else-if="pipelineResult.steps?.connect?.ok === false" type="error" :bordered="false">
            <div style="font-weight:600;margin-bottom:4px">{{ t('devices.edgeliteCannotConnect') }}</div>
            <div style="white-space:pre-line">{{ pipelineResult.steps.connect.error }}</div>
            <div v-if="pipelineResult.steps.connect.driver_config" style="margin-top:8px;padding:8px;background:rgba(0,0,0,0.04);border-radius:4px;font-size:12px">
              <div style="font-weight:500;margin-bottom:4px">{{ t('devices.driverConfigLabel') }}</div>
              <code style="white-space:pre-wrap">{{ JSON.stringify(pipelineResult.steps.connect.driver_config, null, 2) }}</code>
            </div>
          </n-alert>
          <n-alert v-else-if="pipelineResult.steps?.collect?.ok === false" type="warning" :bordered="false">
            <div style="font-weight:600;margin-bottom:4px">{{ t('devices.edgeliteNoData') }}</div>
            <div>{{ pipelineResult.steps.collect.error }}</div>
            <div style="margin-top:4px;font-size:12px;color:#94a3b8">{{ t('devices.edgeliteNoDataDesc') }}</div>
          </n-alert>
        </n-space>
        <n-space v-else-if="pipelineLoading" vertical align="center" style="padding:40px 0">
          <n-spin size="large" />
          <n-text depth="3">{{ t('devices.verifyingPipeline') }}</n-text>
        </n-space>
        <template #action>
          <n-button @click="showPipelineModal = false">{{ t('common.close') }}</n-button>
          <n-button type="primary" @click="rerunPipelineVerify" :loading="pipelineLoading">{{ t('devices.reverify') }}</n-button>
        </template>
      </n-modal>

      <n-modal v-model:show="showDetailModal" preset="card" :title="t('devices.deviceDetail')" style="width:min(860px, 95vw)">
        <n-spin :show="detailLoading">
          <n-space v-if="detailData" vertical size="large">
            <!-- 状态机 -->
            <n-card size="small" :title="t('devices.stateMachine')">
              <n-space align="center" size="small" style="margin-bottom:8px">
                <n-text depth="3">{{ t('devices.currentState') }}:</n-text>
                <n-tag :type="stateTagType(detailData.state?.state)" size="small" :bordered="false">{{ detailData.state?.state || '-' }}</n-tag>
                <n-text v-if="detailData.state?.uptime" depth="3" style="font-size:12px">({{ detailData.state.uptime }})</n-text>
              </n-space>
              <n-space align="center" size="small" style="margin-bottom:8px">
                <n-select v-model:value="stateEventValue" :options="stateEventOptions" :placeholder="t('devices.stateEvent')" size="small" style="width:160px" />
                <n-input v-model:value="stateReasonValue" :placeholder="t('devices.stateReason')" size="small" style="width:200px" />
                <n-button type="primary" size="small" @click="doStateTransition" :loading="stateTransitionLoading">{{ t('devices.stateTransition') }}</n-button>
              </n-space>
              <n-text v-if="detailData.state?.history?.length" depth="3" style="font-size:12px">{{ t('devices.stateHistory') }}:</n-text>
              <n-data-table v-if="detailData.state?.history?.length" :columns="stateHistoryColumns" :data="detailData.state.history" :bordered="false" size="small" :max-height="200" />
            </n-card>

            <!-- 故障注入 -->
            <n-card size="small" :title="t('devices.faultInjection')">
              <n-space align="center" wrap size="small" style="margin-bottom:8px">
                <n-select v-model:value="faultForm.fault_type" :options="faultTypeOptions" :placeholder="t('devices.faultType')" size="small" style="width:140px" />
                <n-input v-model:value="faultForm.target" :placeholder="t('devices.faultTarget')" size="small" style="width:120px" />
                <n-input-number v-model:value="faultForm.duration" :placeholder="t('devices.faultDuration')" size="small" style="width:100px" />
                <n-select v-model:value="faultForm.severity" :options="severityOptions" :placeholder="t('devices.faultSeverity')" size="small" style="width:90px" />
                <n-select v-model:value="faultForm.trigger_mode" :options="triggerModeOptions" :placeholder="t('devices.faultTriggerMode')" size="small" style="width:90px" />
                <n-button type="warning" size="small" @click="doInjectFault" :loading="faultInjectLoading">{{ t('devices.injectFault') }}</n-button>
              </n-space>
              <n-space v-if="detailData.faults?.length > 0" align="center" size="small" style="margin-bottom:4px">
                <n-text depth="3" style="font-size:12px">{{ detailData.faults.length }} {{ t('devices.faultInjection') }}</n-text>
                <n-button size="tiny" type="error" tertiary @click="doClearFaults">{{ t('devices.clearAllFaults') }}</n-button>
              </n-space>
              <n-data-table v-if="detailData.faults?.length > 0" :columns="faultColumns" :data="detailData.faults" :bordered="false" size="small" :max-height="200" />
              <n-text v-else depth="3" style="font-size:12px">{{ t('devices.noFaults') }}</n-text>
            </n-card>

            <!-- 控制回路 -->
            <n-card size="small" :title="t('devices.controlLoops')">
              <n-space align="center" wrap size="small" style="margin-bottom:8px">
                <n-input v-model:value="loopForm.loop_id" :placeholder="t('devices.loopId')" size="small" style="width:100px" />
                <n-select v-model:value="loopForm.loop_type" :options="loopTypeOptions" :placeholder="t('devices.loopType')" size="small" style="width:100px" />
                <n-input v-model:value="loopForm.setpoint_point" :placeholder="t('devices.setpoint')" size="small" style="width:120px" />
                <n-input v-model:value="loopForm.measurement_point" :placeholder="t('devices.measurement')" size="small" style="width:120px" />
                <n-input v-model:value="loopForm.output_point" :placeholder="t('devices.outputPoint')" size="small" style="width:120px" />
                <n-button type="primary" size="small" @click="doAddControlLoop" :loading="loopAddLoading">{{ t('devices.addControlLoop') }}</n-button>
              </n-space>
              <n-data-table v-if="detailData.control_loops?.length > 0" :columns="controlLoopColumns" :data="detailData.control_loops" :bordered="false" size="small" :max-height="200" />
              <n-text v-else depth="3" style="font-size:12px">{{ t('devices.noControlLoops') }}</n-text>
            </n-card>

            <!-- 网络仿真状态 -->
            <n-card v-if="detailData.network_sim" size="small" :title="t('devices.networkSimulation')">
              <n-space align="center" size="small">
                <n-tag :type="detailData.network_sim.enabled ? 'success' : 'default'" size="small" :bordered="false">
                  {{ detailData.network_sim.enabled ? t('devices.networkEnabled') : t('devices.networkDisabled') }}
                </n-tag>
                <n-text v-if="detailData.network_sim.enabled && detailData.network_sim.profile" depth="3" style="font-size:12px">
                  {{ t('devices.networkLatency') }}: {{ detailData.network_sim.profile.latency_ms }}ms |
                  {{ t('devices.networkJitter') }}: {{ detailData.network_sim.profile.jitter_ms }}ms |
                  {{ t('devices.networkPacketLoss') }}: {{ (detailData.network_sim.profile.packet_loss_rate * 100).toFixed(1) }}%
                </n-text>
              </n-space>
            </n-card>
          </n-space>
        </n-spin>
        <template #action>
          <n-button @click="showDetailModal = false">{{ t('common.close') }}</n-button>
        </template>
      </n-modal>

    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NSpace, NSelect, NButton, NButtonGroup, NDataTable, NModal, NForm, NFormItem, NInput, NInputNumber, NTag,
  NText, NAlert, NSpin, NCard, NSkeleton, NDropdown, useMessage, useDialog } from 'naive-ui'
import { useRouter } from 'vue-router'
import api from '../api.js'
import { useI18n } from '../i18n.js'
import { protocolLabels, deviceStatusMap, popularTemplateIds, defaultPointConfig, defaultProtocol } from '../constants.js'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const message = useMessage()
const { t, formatDate } = useI18n()
const dialog = useDialog()
const devices = ref([])
const selectedIds = ref([])
const batchLoading = ref(false)
const dataLoading = ref(false)
const pushLoading = ref(false)
const protocols = ref([])
const templates = ref([])
const filterProtocol = ref(null)
const showCreateModal = ref(false)
const showQuickCreateModal = ref(false)
const showEditModal = ref(false)
const showPointsModal = ref(false)
const showGuideModal = ref(false)
const guideData = ref(null)
const guideLang = ref('python')
const creating = ref(false)
const saving = ref(false)
const currentPoints = ref([])
const selectedTemplate = ref(null)
const editDevice = ref({ id: '', name: '', protocol: '', protocol_config: {} })
const editProtocolConfig = ref({})
const editConfigFields = ref([])
const newDevice = ref({ id: '', name: '', protocol: defaultProtocol, points: [] })
const advancedProtocolConfig = ref({})
const advancedConfigFields = ref([])
const qcTemplateId = ref(null)
const qcDeviceName = ref('')
const qcLoading = ref(false)
const qcProtocolConfig = ref({})
const qcDeviceConfigFields = ref([])
const qcProtocol = ref('')

const showPipelineModal = ref(false)
const pipelineResult = ref(null)
const pipelineLoading = ref(false)
const pipelinePushLoading = ref(false)
const pipelineDeviceId = ref('')

const showBatchCreateModal = ref(false)
const batchCreating = ref(false)
const batchForm = ref({ templateId: null, count: 5, namePrefix: '', idPrefix: '' })

const writePointName = ref('')
const writePointValue = ref('')
const writeLoading = ref(false)
const currentViewDeviceId = ref('')
const currentViewDeviceInfo = ref(null)
const togglingIds = ref(new Set())
const deletingIds = ref(new Set())

const qcFormRef = ref(null)
const createFormRef = ref(null)
const editFormRef = ref(null)
const batchFormRef = ref(null)

// 设备详情
const showDetailModal = ref(false)
const detailLoading = ref(false)
const detailData = ref(null)
const detailDeviceId = ref('')
const stateTransitionLoading = ref(false)
const stateEventValue = ref('')
const stateReasonValue = ref('')
const faultInjectLoading = ref(false)
const loopAddLoading = ref(false)
const faultForm = ref({ fault_type: 'sensor_drift', target: '*', duration: -1, severity: 'medium', trigger_mode: 'manual' })
const loopForm = ref({ loop_id: '', loop_type: 'simple', setpoint_point: '', measurement_point: '', output_point: '' })

const faultTypeOptions = computed(() => [
  { label: t('devices.faultTypeSensorStuck'), value: 'sensor_stuck' },
  { label: t('devices.faultTypeSensorDrift'), value: 'sensor_drift' },
  { label: t('devices.faultTypeSensorNoise'), value: 'sensor_noise' },
  { label: t('devices.faultTypeSensorFailure'), value: 'sensor_failure' },
  { label: t('devices.faultTypeCommLoss'), value: 'comm_loss' },
  { label: t('devices.faultTypeCommDelay'), value: 'comm_delay' },
  { label: t('devices.faultTypeCommIntermittent'), value: 'comm_intermittent' },
  { label: t('devices.faultTypeDeviceFailure'), value: 'device_failure' },
  { label: t('devices.faultTypeActuatorStuck'), value: 'actuator_stuck' },
])

const severityOptions = computed(() => [
  { label: t('devices.severityLow'), value: 'low' },
  { label: t('devices.severityMedium'), value: 'medium' },
  { label: t('devices.severityHigh'), value: 'high' },
  { label: t('devices.severityCritical'), value: 'critical' },
])

const triggerModeOptions = computed(() => [
  { label: t('devices.triggerManual'), value: 'manual' },
  { label: t('devices.triggerRandom'), value: 'random' },
  { label: t('devices.triggerScheduled'), value: 'scheduled' },
  { label: t('devices.triggerConditional'), value: 'conditional' },
])

const stateEventOptions = computed(() => [
  { label: t('devices.eventStart'), value: 'start' },
  { label: t('devices.eventStop'), value: 'stop' },
  { label: t('devices.eventStartupComplete'), value: 'startup_complete' },
  { label: t('devices.eventStopComplete'), value: 'stop_complete' },
  { label: t('devices.eventFault'), value: 'fault' },
  { label: t('devices.eventReset'), value: 'reset' },
  { label: t('devices.eventMaintenance'), value: 'maintenance' },
  { label: t('devices.eventMaintenanceComplete'), value: 'maintenance_complete' },
  { label: t('devices.eventProgramMode'), value: 'program_mode' },
  { label: t('devices.eventProgramExit'), value: 'program_exit' },
  { label: t('devices.eventDeviceFailure'), value: 'device_failure' },
])

const loopTypeOptions = computed(() => [
  { label: 'Simple', value: 'simple' },
  { label: 'Cascade', value: 'cascade' },
  { label: 'Feedforward', value: 'feedforward' },
])

const stateHistoryColumns = computed(() => [
  { title: t('devices.stateEvent'), key: 'trigger', width: 120 },
  { title: t('devices.currentState'), key: 'from_state', width: 120, render: (row) => `${row.from_state || '-'} → ${row.to_state || '-'}` },
  { title: t('devices.stateReason'), key: 'reason', width: 160 },
  { title: t('common.detail'), key: 'timestamp', width: 160, render: (row) => row.timestamp ? formatDate(row.timestamp) : '-' },
])

const faultColumns = computed(() => [
  { title: t('devices.faultType'), key: 'fault_type', width: 120 },
  { title: t('devices.faultTarget'), key: 'target_point', width: 100 },
  { title: t('devices.faultSeverity'), key: 'severity', width: 80 },
  { title: t('devices.faultTriggerMode'), key: 'trigger_mode', width: 90 },
  { title: t('common.status'), key: 'active', width: 70, render: (row) => h(NTag, { size: 'tiny', type: row.active ? 'error' : 'default', bordered: false }, () => row.active ? t('devices.faultActive') : t('devices.faultInactive')) },
  {
    title: t('common.action'), key: 'actions', width: 70,
    render: (row) => h(NButton, { size: 'tiny', type: 'error', tertiary: true, onClick: () => doRemoveFault(row.fault_id || row.id) }, () => t('common.remove')),
  },
])

const controlLoopColumns = computed(() => [
  { title: t('devices.loopId'), key: 'loop_id', width: 100 },
  { title: t('devices.loopType'), key: 'loop_type', width: 90 },
  { title: t('devices.setpoint'), key: 'setpoint_point', width: 110 },
  { title: t('devices.measurement'), key: 'measurement_point', width: 110 },
  { title: t('devices.outputPoint'), key: 'output_point', width: 110 },
  {
    title: t('common.action'), key: 'actions', width: 80,
    render: (row) => h(NButton, { size: 'tiny', type: 'error', tertiary: true, onClick: () => doRemoveControlLoop(row.loop_id) }, () => t('devices.removeLoop')),
  },
])

function stateTagType(state) {
  const map = { RUN: 'success', STARTING: 'info', STOPPING: 'warning', STOP: 'default', ERROR: 'error', MAINTENANCE: 'warning', PROGRAM: 'info' }
  return map[state] || 'default'
}

const qcRules = computed(() => ({
  qcTemplateId: [{ required: true, message: t('devices.pleaseSelectTemplate'), trigger: 'change' }],
  qcDeviceName: [{ required: true, message: t('devices.pleaseEnterDeviceName'), trigger: 'blur' }],
}))

const createRules = computed(() => ({
  id: [{ required: true, message: t('devices.pleaseEnterDeviceId'), trigger: 'blur' }],
  name: [{ required: true, message: t('devices.pleaseEnterDeviceName'), trigger: 'blur' }],
  protocol: [{ required: true, message: t('devices.protocolRequired'), trigger: 'change' }],
}))

const editRules = computed(() => ({
  name: [{ required: true, message: t('devices.pleaseEnterDeviceName'), trigger: 'blur' }],
}))

const batchRules = computed(() => ({
  templateId: [{ required: true, message: t('devices.pleaseSelectTemplate'), trigger: 'change' }],
  namePrefix: [{ required: true, message: t('devices.pleaseEnterNamePrefix'), trigger: 'blur' }],
  idPrefix: [{ required: true, message: t('devices.pleaseEnterIdPrefix'), trigger: 'blur' }],
}))

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const pipelineSteps = computed(() => [
  { label: t('devices.pipelineAuth'), key: 'auth' },
  { label: t('devices.pipelineRegister'), key: 'register' },
  { label: t('devices.pipelineConnect'), key: 'connect' },
  { label: t('devices.pipelineCollect'), key: 'collect' },
  { label: t('devices.pipelineVerify'), key: 'verify' },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const pipelineComparisonColumns = computed(() => [
  { title: t('devices.point'), key: 'point', width: 120 },
  { title: t('devices.protoforgeValue'), key: 'protoforge_value', width: 140 },
  { title: t('devices.edgeliteValue'), key: 'edgelite_value', width: 140 },
  {
    title: t('devices.match'), key: 'match', width: 80,
    render: (row) => {
      if (row.match === null || row.match === undefined) return h(NTag, { size: 'tiny', type: 'warning', bordered: false }, () => t('devices.noData'))
      return row.match
        ? h(NTag, { size: 'tiny', type: 'success', bordered: false }, () => t('devices.matched'))
        : h(NTag, { size: 'tiny', type: 'error', bordered: false }, () => t('devices.inconsistent'))
    }
  },
])

const protocolOptions = computed(() => [
  { label: t('common.all'), value: null },
  ...protocols.value.map(p => ({ label: p.display_name, value: p.name })),
])

const templateOptions = computed(() => {
  const list = newDevice.value.protocol
    ? templates.value.filter(t => t.protocol === newDevice.value.protocol)
    : templates.value
  return list.map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
})

const quickTemplateOptions = computed(() => {
  const popularSet = new Set(popularTemplateIds)
  const popularItems = templates.value
    .filter(t => popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  const otherItems = templates.value
    .filter(t => !popularSet.has(t.id))
    .map(t => ({ label: `${t.name} (${t.protocol})`, value: t.id }))
  return [...popularItems, ...otherItems]
})

const qcTemplateName = computed(() => {
  const t = templates.value.find(t => t.id === qcTemplateId.value)
  return t ? t.name : ''
})

const qcTemplatePoints = computed(() => {
  const t = templates.value.find(t => t.id === qcTemplateId.value)
  return t ? (t.points?.length || t.point_count || 0) : 0
})

const filteredDevices = computed(() => {
  if (!filterProtocol.value) return devices.value
  return devices.value.filter(d => d.protocol === filterProtocol.value)
})

const noProtocolRunning = computed(() => protocols.value.length > 0 && protocols.value.every(p => p.status !== 'running'))

const batchMoreOptions = computed(() => [
  { label: t('devices.pushToEdgeLite'), key: 'push' },
  { label: t('devices.verifyPipeline'), key: 'pipeline' },
])

// 优化：创建操作合并为 split button 下拉，消除第二个"更多"
const createOptions = computed(() => [
  { label: t('devices.advancedCreate'), key: 'advanced' },
  { label: t('devices.batchCreate'), key: 'batch' },
])

function onBatchMoreSelect(key) {
  if (key === 'push') batchPushToEdgelite()
  else if (key === 'pipeline') batchVerifyPipeline()
}

function onCreateSelect(key) {
  if (key === 'advanced') openAdvancedCreate()
  else if (key === 'batch') openBatchCreateModal()
}

function goProtocols() { router.push('/protocols') }

async function loadDeviceConfig(protocol) {
  if (!protocol) return { fields: [], defaults: {} }
  try {
    const res = await api.getProtocolDeviceConfig(protocol)
    const defaults = {}
    ;(res.fields || []).forEach(f => { defaults[f.key] = f.default })
    return { fields: res.fields || [], defaults }
  } catch (e) { message.warning(t('devices.loadConfigFailed')); return { fields: [], defaults: {} } }
}

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const columns = computed(() => [
  { type: 'selection' },
  { title: t('devices.device'), key: 'name', width: 160, render: (row) => h('div', {}, [
    h('div', { style: 'font-weight:500' }, row.name || row.id),
    h('div', { style: 'font-size:11px;color:#94a3b8' }, row.id),
  ]) },
  { title: t('devices.protocol'), key: 'protocol', width: 120, render: (row) => h(NTag, { size: 'tiny', type: 'info', bordered: false }, () => protocolLabels[row.protocol] || row.protocol) },
  {
    title: t('devices.status'), key: 'status', width: 100,
    render: (row) => {
      const statusI18nMap = {
        online: t('devices.online'), running: t('devices.running'),
        error: t('devices.error'), stopped: t('devices.stopped'),
        offline: t('devices.offline'), disabled: t('devices.disabled'),
      }
      const statusTypeMap = {
        online: 'success', running: 'success',
        error: 'error', stopped: 'default',
        offline: 'default', disabled: 'default',
      }
      const type = statusTypeMap[row.status] || 'default'
      const label = statusI18nMap[row.status] || row.status || t('devices.offline')
      return h(NTag, { type, size: 'small', bordered: false }, () => label)
    }
  },
  { title: t('devices.points'), key: 'points', width: 70, render: (row) => (row.points || []).length },
  {
    title: t('devices.actions'), key: 'actions', width: 220,
    render: (row) => h(NSpace, { size: 4 }, () => [
      // 测点（图标直显）
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewPoints(row.id), title: t('devices.points') }, () => [
        h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
          h('circle', { cx: 12, cy: 12, r: 3 }),
          h('circle', { cx: 12, cy: 12, r: 9, opacity: 0.3 }),
        ])
      ]),
      // 启停（图标直显，颜色区分破坏性）
      row.status === 'online' || row.status === 'running'
        ? h(NButton, { size: 'tiny', type: 'warning', secondary: true, loading: togglingIds.value.has(row.id), onClick: () => toggleDevice(row.id, 'stop'), title: t('common.stop') }, () => [
            h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
              h('rect', { x: 6, y: 4, width: 4, height: 16 }),
              h('rect', { x: 14, y: 4, width: 4, height: 16 }),
            ])
          ])
        : h(NButton, { size: 'tiny', type: 'primary', secondary: true, loading: togglingIds.value.has(row.id), onClick: () => toggleDevice(row.id, 'start'), title: t('common.start') }, () => [
            h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
              h('polygon', { points: '5 3 19 12 5 21 5 3' })
            ])
          ]),
      // 编辑（图标直显，高频操作不再隐藏）
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => openEditDevice(row), title: t('common.edit') }, () => [
        h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
          h('path', { d: 'M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7 M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z' })
        ])
      ]),
      // 删除（图标直显，高频操作不再隐藏）
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => confirmDeleteDevice(row), title: t('common.delete') }, () => [
        h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
          h('polyline', { points: '3 6 5 6 21 6' }),
          h('path', { d: 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' })
        ])
      ]),
      // 更多：仅保留低频的指南/链路验证
      h(NDropdown, {
        options: [
          { label: t('devices.deviceDetail'), key: 'detail' },
          { label: t('devices.guide'), key: 'guide' },
          { label: t('devices.pipeline'), key: 'pipeline' },
        ],
        onSelect: (key) => {
          if (key === 'detail') openDeviceDetail(row.id)
          else if (key === 'guide') showGuide(row.id)
          else if (key === 'pipeline') openPipelineVerify(row.id)
        },
      }, () => h(NButton, { size: 'tiny', tertiary: true, title: t('common.more') }, () => [
        h('svg', { viewBox: '0 0 24 24', width: 14, height: 14, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
          h('circle', { cx: 12, cy: 12, r: 1 }),
          h('circle', { cx: 19, cy: 12, r: 1 }),
          h('circle', { cx: 5, cy: 12, r: 1 }),
        ])
      ])),
    ])
  },
])

// FIXED: P3 - Q7: 顶层t()数组改为computed，语言切换后自动刷新
const pointColumns = computed(() => [
  { title: t('devices.name'), key: 'name', width: 120 },
  { title: t('devices.value'), key: 'value', width: 120 },
  { title: t('devices.time'), key: 'timestamp', width: 180, render: (row) => row.timestamp ? formatDate(row.timestamp) : '-' },
  { title: t('devices.quality'), key: 'quality', width: 80 },
])

function openQuickCreate() {
  qcTemplateId.value = null; qcDeviceName.value = ''
  qcProtocolConfig.value = {}; qcDeviceConfigFields.value = []; qcProtocol.value = ''
  showQuickCreateModal.value = true
}

// 优化：选择模板时自动加载协议配置，替代原来的多步向导
async function onQcTemplateChange(templateId) {
  if (!templateId) {
    qcDeviceConfigFields.value = []
    qcProtocolConfig.value = {}
    qcProtocol.value = ''
    return
  }
  const tmpl = templates.value.find(t => t.id === templateId)
  if (tmpl && tmpl.protocol && tmpl.protocol !== qcProtocol.value) {
    qcProtocol.value = tmpl.protocol
    const { fields, defaults } = await loadDeviceConfig(tmpl.protocol)
    qcDeviceConfigFields.value = fields
    qcProtocolConfig.value = defaults
  }
}

async function doQuickCreate() {
  try {
    await qcFormRef.value?.validate()
  } catch { return }
  qcLoading.value = true
  try {
    await api.quickCreateDevice(qcTemplateId.value, qcDeviceName.value, null, qcProtocolConfig.value)
    message.success(t('devices.deviceCreatedAndStarted', { name: qcDeviceName.value }))
    showQuickCreateModal.value = false
    await loadData()
  } catch (e) {
    message.error(t('devices.createFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { qcLoading.value = false }
}

function openAdvancedCreate() {
  newDevice.value = { id: '', name: '', protocol: defaultProtocol, points: [] }
  advancedProtocolConfig.value = {}; advancedConfigFields.value = []
  selectedTemplate.value = null
  showCreateModal.value = true
}

async function onAdvancedProtocolChange(protocol) {
  selectedTemplate.value = null
  const { fields, defaults } = await loadDeviceConfig(protocol)
  advancedConfigFields.value = fields
  advancedProtocolConfig.value = defaults
}

async function loadData() {
  dataLoading.value = true
  try {
    const results = await Promise.allSettled([
      api.getDevices(),
      api.getProtocols(),
      api.getTemplates()
    ])
    devices.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
    protocols.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    templates.value = results[2].status === 'fulfilled' ? (results[2].value || []) : []
    const failedIdx = results.map((r, i) => r.status === 'rejected' ? i : -1).filter(i => i >= 0)
    if (failedIdx.length > 0) {
      const names = [t('devices.device'), t('devices.protocol'), t('devices.template')]
    message.warning(t('devices.partialLoadFailed', { items: failedIdx.map(i => names[i]).join(t('common.separator')) }))
    }
  } catch (e) { message.error(t('devices.loadDataFailed') + ': ' + (e.response?.data?.detail || e.message)) }
  finally { dataLoading.value = false }
}

async function batchStart() {
  dialog.info({
    title: t('devices.confirmBatchStart'),
    content: t('devices.confirmBatchStartDesc', { count: selectedIds.value.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      try {
        const res = await api.batchStartDevices(selectedIds.value)
        const ok = res.started || 0
        const fail = res.errors?.length || 0
        await loadData()
        selectedIds.value = []  // FIXED: W12 - clear selection after loadData succeeds
        message.success(t('devices.batchStarted', { ok, fail }))
      } catch (e) {
        message.error(t('devices.batchStartFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { batchLoading.value = false }
    }
  })
}

async function batchStop() {
  dialog.warning({
    title: t('devices.confirmBatchStop'),
    content: t('devices.confirmBatchStopDesc', { count: selectedIds.value.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      try {
        const res = await api.batchStopDevices(selectedIds.value)
        const ok = res.stopped || 0
        const fail = res.errors?.length || 0
        await loadData()
        selectedIds.value = []  // FIXED: W12 - clear selection after loadData succeeds
        message.success(t('devices.batchStopped', { ok, fail }))
      } catch (e) {
        message.error(t('devices.batchStopFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { batchLoading.value = false }
    }
  })
}

async function batchDelete() {
  dialog.warning({
    title: t('devices.confirmBatchDelete'),
    content: t('devices.confirmBatchDeleteDesc', { count: selectedIds.value.length }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      try {
        const res = await api.batchDeleteDevices(selectedIds.value)
        const ok = res.deleted || 0
        const fail = res.errors?.length || 0
        await loadData()
        selectedIds.value = []  // FIXED: W12 - clear selection after loadData succeeds
        message.success(t('devices.batchDeleted', { ok, fail }))
      } catch (e) {
        message.error(t('devices.batchDeleteFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally { batchLoading.value = false }
    }
  })
}

async function startAllDevices() {
  const toStart = filteredDevices.value.filter(d => d.status !== 'online' && d.status !== 'running')
  if (!toStart.length) { message.info(t('devices.allDevicesRunning')); return }
  dialog.warning({
    title: t('devices.confirmStartAll'),
    content: t('devices.confirmStartAllDesc', { count: toStart.length }),
    positiveText: t('common.start'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      try {
        const results = await Promise.allSettled(toStart.map(dev => api.startDevice(dev.id)))
        let ok = 0, fail = 0
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') ok++
          else { fail++; message.warning(t('devices.deviceStartFailed', { id: toStart[i].id, error: r.reason?.response?.data?.detail || r.reason?.message || t('common.unknownError') })) }
        })
        if (fail > 0) { message.warning(t('devices.startedWithFailures', { ok, fail })) } else { message.success(t('devices.startedCount', { ok })) }
        await loadData()  // FIXED: await loadData to prevent stale data display
      } finally { batchLoading.value = false }
    }
  })
}

async function stopAllDevices() {
  const toStop = filteredDevices.value.filter(d => d.status === 'online' || d.status === 'running')
  if (!toStop.length) { message.info(t('devices.noRunningDevices')); return }
  dialog.warning({
    title: t('devices.confirmStopAll'),
    content: t('devices.confirmStopAllDesc', { count: toStop.length }),
    positiveText: t('common.stop'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      batchLoading.value = true
      try {
        const results = await Promise.allSettled(toStop.map(dev => api.stopDevice(dev.id)))
        let ok = 0, fail = 0
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') ok++
          else { fail++; message.warning(t('devices.deviceStopFailed', { id: toStop[i].id, error: r.reason?.response?.data?.detail || r.reason?.message || t('common.unknownError') })) }
        })
        if (fail > 0) { message.warning(t('devices.stoppedWithFailures', { ok, fail })) } else { message.success(t('devices.stoppedCount', { ok })) }
        await loadData()  // FIXED: was not awaited, could cause race condition
      } finally { batchLoading.value = false }
    }
  })
}

async function batchPushToEdgelite() {
  dialog.info({
    title: t('devices.confirmBatchPush'),
    content: t('devices.confirmBatchPushDesc', { count: selectedIds.value.length }),
    positiveText: t('devices.push'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      pushLoading.value = true
      try {
        let ok = 0, fail = 0, skip = 0, unsupported = 0, notConfigured = 0
        const results = await Promise.allSettled(selectedIds.value.map(id => api.pushToEdgelite(id)))
        results.forEach((r) => {
          if (r.status === 'rejected') { fail++; return }
          const res = r.value
          if (res.skipped) {
            const reason = res.reason || ''
            if (res.error_type === 'unsupported' || reason.includes('not supported') || reason.includes('NOT_SUPPORTED')) { unsupported++ }
            else if (res.error_type === 'not_configured') { notConfigured++ }
            else { skip++ }
          } else if (res.ok) { ok++ }
          else { fail++ }
        })

        // 优化：统一为一条汇总消息，避免多消息轰炸
        const parts = []
        if (ok) parts.push(t('devices.pushSuccessCount', { count: ok }))
        if (notConfigured + skip) parts.push(t('devices.edgeliteNotConfiguredCount', { count: notConfigured + skip }))
        if (unsupported) parts.push(t('devices.protocolUnsupportedCount', { count: unsupported }))
        if (fail) parts.push(t('devices.failedCount', { count: fail }))
        const msg = parts.join(t('common.separator')) || t('devices.noOperation')
        if (fail > 0 && ok === 0) message.error(msg)
        else if (fail > 0 || notConfigured > 0) message.warning(msg)
        else message.success(msg)

        await loadData()
        selectedIds.value = []
      } finally { pushLoading.value = false }
    }
  })
}

async function createDevice() {
  try {
    await createFormRef.value?.validate()
  } catch { return }
  creating.value = true
  try {
    let config = { ...newDevice.value, points: [], protocol_config: advancedProtocolConfig.value }
    if (selectedTemplate.value) {
      const tmplRes = await api.getTemplate(selectedTemplate.value)
      config.points = tmplRes?.points || []; config.protocol = tmplRes?.protocol || config.protocol
    }
    if (!config.points.length) config.points = [{ ...defaultPointConfig }]
    await api.createDevice(config)
    showCreateModal.value = false
    newDevice.value = { id: '', name: '', protocol: defaultProtocol, points: [] }
    selectedTemplate.value = null
    message.success(t('devices.deviceCreated'))
    await loadData()
  } catch (e) { message.error(t('devices.createFailed') + ': ' + (e.response?.data?.detail || e.message)) }
  finally { creating.value = false }
}

async function openEditDevice(row) {
  try {
    const config = await api.getDeviceConfig(row.id)
    editDevice.value = { id: config.id, name: config.name, protocol: config.protocol, protocol_config: config.protocol_config || {}, points: config.points || [] }
    const { fields, defaults } = await loadDeviceConfig(row.protocol)
    editConfigFields.value = fields
    editProtocolConfig.value = { ...defaults, ...(config.protocol_config || {}) }
    showEditModal.value = true
  } catch (e) {
    message.error(t('devices.getConfigFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function saveEditDevice() {
  try {
    await editFormRef.value?.validate()
  } catch { return }
  saving.value = true
  try {
    await api.updateDevice(editDevice.value.id, {
      id: editDevice.value.id, name: editDevice.value.name,
      protocol: editDevice.value.protocol, points: editDevice.value.points || [],
      protocol_config: editProtocolConfig.value,
    })
    showEditModal.value = false
    message.success(t('devices.deviceUpdated'))
    const protoConfig = editProtocolConfig.value || {}
    if (protoConfig.edgelite_url) {
      message.info(t('devices.edgeliteConfigDetected'))
    }
    await loadData()
  } catch (e) { message.error(t('devices.updateFailed') + ': ' + (e.response?.data?.detail || e.message)) }
  finally { saving.value = false }
}

// 优化：单设备启停均不弹确认（用按钮颜色传达破坏性），批量操作保留确认
async function toggleDevice(id, action) {
  togglingIds.value.add(id)
  try {
    if (action === 'stop') {
      await api.stopDevice(id)
      message.success(t('devices.deviceStopped'))
    } else {
      await api.startDevice(id)
      message.success(t('devices.deviceStarted'))
    }
    await loadData()
  } catch (e) {
    message.error((action === 'stop' ? t('devices.stopFailed') : t('devices.startFailed')) + ': ' + (e.response?.data?.detail || e.message))
  } finally { togglingIds.value.delete(id) }
}

function confirmDeleteDevice(row) {
  deleteDevice(row.id)  // FIXED: removed duplicate confirmation dialog - deleteDevice already shows confirmation
}

async function deleteDevice(id) {
  dialog.warning({
    title: t('devices.confirmDeleteDevice'),
    content: t('devices.confirmDeleteDeviceDesc', { id }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      deletingIds.value.add(id)
      try { await api.deleteDevice(id); message.success(t('devices.deviceDeleted')); await loadData() }
      catch (e) { message.error(t('devices.deleteFailed') + ': ' + (e.response?.data?.detail || e.message)) }
      finally { deletingIds.value.delete(id) }
    }
  })
}

async function viewPoints(id) {
  try {
    const [res, deviceInfo] = await Promise.all([
      api.getDevicePoints(id),
      api.getDevice(id).catch(() => null),
    ])
    currentPoints.value = Array.isArray(res?.points) ? res.points : (Array.isArray(res) ? res : [])
    currentViewDeviceId.value = id
    currentViewDeviceInfo.value = deviceInfo
    writePointName.value = ''
    writePointValue.value = ''
    showPointsModal.value = true
  } catch (e) { message.error(t('devices.readPointsFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function writeDevicePointQuick() {
  if (!currentViewDeviceId.value || !writePointName.value) {
    message.warning(t('devices.pleaseSelectPoint'))
    return
  }
  writeLoading.value = true
  try {
    const numVal = Number(writePointValue.value)
    const value = isNaN(numVal) ? writePointValue.value : numVal
    await api.writeDevicePoint(currentViewDeviceId.value, writePointName.value, value)
    message.success(t('devices.pointWriteSuccess', { name: writePointName.value }))
    const res = await api.getDevicePoints(currentViewDeviceId.value)
    currentPoints.value = Array.isArray(res?.points) ? res.points : (Array.isArray(res) ? res : [])
  } catch (e) {
    message.error(t('devices.writeFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { writeLoading.value = false }
}

function openBatchCreateModal() {
  batchForm.value = { templateId: null, count: 5, namePrefix: '', idPrefix: '' }
  showBatchCreateModal.value = true
}

async function doBatchCreate() {
  try {
    await batchFormRef.value?.validate()
  } catch { return }
  batchCreating.value = true
  try {
    const tmpl = templates.value.find(t => t.id === batchForm.value.templateId)
    const configs = []
    for (let i = 1; i <= batchForm.value.count; i++) {
      configs.push({
        id: `${batchForm.value.idPrefix}-${String(i).padStart(3, '0')}`,
        name: `${batchForm.value.namePrefix}-${i}`,
        protocol: tmpl?.protocol || defaultProtocol,
        points: tmpl?.points || [{ ...defaultPointConfig }],
      })
    }
    const res = await api.batchCreateDevices(configs)
    showBatchCreateModal.value = false
    message.success(t('devices.batchCreatedSuccess', { count: res.created || configs.length }))
    await loadData()
  } catch (e) {
    message.error(t('devices.batchCreateFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { batchCreating.value = false }
}

async function showGuide(id) {
  try {
    guideData.value = await api.getDeviceConnectionGuide(id)
    guideLang.value = 'python'
    showGuideModal.value = true
  } catch (e) { message.error(t('devices.getGuideFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function copyGuide() {
  const code = guideData.value?.code_examples?.[guideLang.value] || guideData.value?.code_example
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
    message.success(t('devices.codeCopied'))
  } catch (e) {
    message.error(t('devices.copyFailed'))
  }
}

async function openPipelineVerify(deviceId) {
  pipelineDeviceId.value = deviceId
  pipelineResult.value = null
  showPipelineModal.value = true
  await runPipelineVerify()
}

async function runPipelineVerify() {
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

function rerunPipelineVerify() { runPipelineVerify() }

async function pushFromPipeline() {
  pipelinePushLoading.value = true
  try {
    const res = await api.pushToEdgelite(pipelineDeviceId.value)
    if (res.skipped) {
      const reason = res.reason || ''
      if (res.error_type === 'unsupported' || reason.includes('not supported') || reason.includes('NOT_SUPPORTED')) {
        message.warning(t('devices.protocolNotSupportedByEdgeLite'))
      } else if (res.error_type === 'not_configured') {
        message.warning(t('devices.edgeliteNotConfiguredInSettings'))
      } else {
        message.warning(t('devices.deviceNotConfiguredEdgeLite'))
      }
    } else if (res.ok) {
      message.success(res.action === 'created' ? t('devices.deviceRegisteredToEdgeLite') : t('devices.deviceConfigUpdated'))
      await runPipelineVerify()
    } else {
      const errMsg = res.suggestion || res.error || t('common.unknownError')
      message.error(t('devices.pushFailed') + ': ' + errMsg)
    }
  } catch (e) {
    message.error(t('devices.pushFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { pipelinePushLoading.value = false }
}

function getPipelineStepStatus(idx) {
  if (!pipelineResult.value || !pipelineResult.value.steps) return 'pending'
  const key = pipelineSteps.value[idx].key
  if (key === 'verify') {
    const collectOk = pipelineResult.value.steps.collect?.ok
    const hasComparison = pipelineResult.value.data_comparison?.length > 0
    if (collectOk && hasComparison) return 'success'
    return 'pending'
  }
  const step = pipelineResult.value.steps[key]
  if (!step) return 'pending'
  return step.ok ? 'success' : 'error'
}

function getPipelineStepDesc(idx) {
  if (!pipelineResult.value || !pipelineResult.value.steps) return ''
  const key = pipelineSteps.value[idx].key
  if (key === 'verify') {
    const comp = pipelineResult.value.data_comparison
    if (comp && comp.length > 0) {
      const matched = comp.filter(c => c.match).length
      return t('devices.pointMatchCount', { matched, total: comp.length })
    }
    return t('devices.waitingForData')
  }
  const step = pipelineResult.value.steps[key]
  if (!step) return t('devices.notExecuted')
  if (step.ok) {
    if (key === 'auth') return t('devices.authSuccess')
    if (key === 'register') return t('devices.registeredStatus', { status: step.status || 'ok' })
    if (key === 'connect') return t('devices.connectedStatus', { status: step.status || 'ok' })
    if (key === 'collect') return step.has_real_data ? t('devices.dataCollected') : t('devices.noRealData')
    return t('common.success')
  }
  return step.error || t('common.failed')
}

async function batchVerifyPipeline() {
  pipelineLoading.value = true
  let ok = 0, fail = 0, skip = 0
  try {
    // 优化：并发执行替代串行循环，提升速度；去掉逐个失败消息，统一汇总
    const results = await Promise.allSettled(selectedIds.value.map(id => api.verifyEdgelitePipeline(id)))
    results.forEach((r) => {
      if (r.status === 'rejected') { fail++; return }
      const res = r.value
      if (res.skipped) { skip++ }
      else if (res.ok) { ok++ }
      else { fail++ }
    })
  } finally {
    pipelineLoading.value = false
  }
  selectedIds.value = []
  const parts = []
  if (ok) parts.push(t('devices.pipelineOkCount', { count: ok }))
  if (skip) parts.push(t('devices.edgeliteNotConfiguredCount', { count: skip }))
  if (fail) parts.push(t('devices.pipelineFailCount', { count: fail }))
  const msg = parts.join(t('common.separator')) || t('devices.noOperation')
  if (fail > 0 && ok === 0) message.error(msg)
  else if (fail > 0) message.warning(msg)
  else message.success(msg)
}

// 设备详情
async function openDeviceDetail(id) {
  detailDeviceId.value = id
  showDetailModal.value = true
  detailData.value = null
  detailLoading.value = true
  stateEventValue.value = ''
  stateReasonValue.value = ''
  try {
    detailData.value = await api.getDeviceDetail(id)
  } catch (e) {
    message.error(t('devices.loadDetailFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { detailLoading.value = false }
}

async function refreshDetail() {
  if (!detailDeviceId.value) return
  try {
    detailData.value = await api.getDeviceDetail(detailDeviceId.value)
  } catch { /* silent refresh */ }
}

async function doStateTransition() {
  if (!stateEventValue.value) {
    message.warning(t('devices.stateEvent'))
    return
  }
  stateTransitionLoading.value = true
  try {
    const res = await api.triggerStateTransition(detailDeviceId.value, stateEventValue.value, stateReasonValue.value)
    message.success(t('devices.stateTransitionSuccess', { from: res.from_state, to: res.to_state }))
    stateEventValue.value = ''
    stateReasonValue.value = ''
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.stateTransitionFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { stateTransitionLoading.value = false }
}

async function doInjectFault() {
  faultInjectLoading.value = true
  try {
    await api.injectDeviceFault(detailDeviceId.value, { ...faultForm.value })
    message.success(t('devices.faultInjected'))
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.faultInjectFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { faultInjectLoading.value = false }
}

async function doRemoveFault(faultId) {
  try {
    await api.removeDeviceFault(detailDeviceId.value, faultId)
    message.success(t('devices.faultRemoved'))
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.faultRemoveFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function doClearFaults() {
  try {
    const res = await api.clearDeviceFaults(detailDeviceId.value)
    message.success(t('devices.faultCleared', { count: res.cleared || 0 }))
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.faultClearFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function doAddControlLoop() {
  if (!loopForm.value.loop_id) {
    message.warning(t('devices.loopId'))
    return
  }
  loopAddLoading.value = true
  try {
    await api.addControlLoop(detailDeviceId.value, { ...loopForm.value })
    message.success(t('devices.loopAdded'))
    loopForm.value = { loop_id: '', loop_type: 'simple', setpoint_point: '', measurement_point: '', output_point: '' }
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.loopAddFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loopAddLoading.value = false }
}

async function doRemoveControlLoop(loopId) {
  try {
    await api.removeControlLoop(detailDeviceId.value, loopId)
    message.success(t('devices.loopRemoved'))
    await refreshDetail()
  } catch (e) {
    message.error(t('devices.loopRemoveFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadData)
</script>
