<template>
  <div>
    <n-h2 style="margin-bottom: 4px">{{ t('compliance.title') }}</n-h2>
    <n-text depth="3" style="font-size: 13px">{{ t('compliance.subtitle') }}</n-text>

    <n-tabs type="line" animated style="margin-top: 20px">
      <!-- Check Tab -->
      <n-tab-pane name="check" :tab="t('compliance.runCheck')">
        <n-card style="max-width: 700px">
          <n-form label-placement="left" label-width="120">
            <n-form-item :label="t('compliance.selectProtocol')">
              <n-select v-model:value="checkForm.protocol" :options="protocolOptions"
                :placeholder="t('compliance.selectProtocolPlaceholder')" style="width: 250px"
                @update:value="onProtocolChange" />
            </n-form-item>
            <n-form-item :label="t('compliance.recordingId')">
              <n-input v-model:value="checkForm.recording_id" :placeholder="t('compliance.recordingIdPlaceholder')"
                style="width: 300px" />
              <n-text depth="3" style="margin-left: 8px; font-size: 12px">{{ t('compliance.recordingIdHint') }}</n-text>
            </n-form-item>
            <n-form-item>
              <n-button type="primary" :loading="checking" @click="runCheck" :disabled="!checkForm.protocol">
                {{ t('compliance.runCheckBtn') }}
              </n-button>
            </n-form-item>
          </n-form>
        </n-card>

        <!-- Rules Preview -->
        <n-card v-if="rules.length > 0" :title="t('compliance.rulesTitle') + ' - ' + checkForm.protocol" size="small"
          style="margin-top: 16px; max-width: 700px">
          <n-table :bordered="false" :single-line="false" size="small">
            <thead>
              <tr>
                <th>ID</th>
                <th>{{ t('compliance.ruleName') }}</th>
                <th>{{ t('compliance.ruleDesc') }}</th>
                <th>{{ t('compliance.severity') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in rules" :key="rule.id">
                <td><n-tag size="tiny">{{ rule.id }}</n-tag></td>
                <td>{{ rule.name }}</td>
                <td>{{ rule.description }}</td>
                <td><n-tag :type="rule.severity === 'error' ? 'error' : rule.severity === 'warning' ? 'warning' : 'info'"
                    size="tiny">{{ rule.severity }}</n-tag></td>
              </tr>
            </tbody>
          </n-table>
        </n-card>

        <!-- Check Result -->
        <n-card v-if="checkResult" :title="t('compliance.checkResult')" size="small" style="margin-top: 16px; max-width: 700px">
          <n-space vertical size="large">
            <n-result :status="checkResult.passed ? 'success' : 'error'"
              :title="checkResult.passed ? t('compliance.allPassed') : t('compliance.violationsFound')"
              :description="t('compliance.score') + ': ' + checkResult.compliance_score + '%'">
            </n-result>
            <n-space>
              <n-stat :label="t('compliance.totalMessages')" :value="checkResult.total_messages" />
              <n-stat :label="t('compliance.totalRules')" :value="checkResult.total_rules" />
              <n-stat :label="t('compliance.violationsCount')" :value="checkResult.violations.length" />
            </n-space>
            <div v-if="checkResult.violations.length > 0">
              <n-text strong style="display: block; margin-bottom: 8px">{{ t('compliance.violationsList') }}</n-text>
              <n-table :bordered="false" size="small">
                <thead>
                  <tr>
                    <th>Rule ID</th>
                    <th>{{ t('compliance.ruleName') }}</th>
                    <th>{{ t('compliance.severity') }}</th>
                    <th>{{ t('compliance.violationMsg') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(v, idx) in checkResult.violations" :key="idx">
                    <td><n-tag size="tiny">{{ v.rule_id }}</n-tag></td>
                    <td>{{ v.rule_name }}</td>
                    <td><n-tag :type="v.severity === 'error' ? 'error' : 'warning'" size="tiny">{{ v.severity }}</n-tag></td>
                    <td>{{ v.message }}</td>
                  </tr>
                </tbody>
              </n-table>
            </div>
          </n-space>
        </n-card>
      </n-tab-pane>

      <!-- History Tab -->
      <n-tab-pane name="history" :tab="t('compliance.history')">
        <n-spin :show="reportsLoading">
          <n-empty v-if="!reportsLoading && reports.length === 0" :description="t('compliance.noReports')"
            style="padding: 40px" />
          <n-data-table v-else :columns="reportColumns" :data="reports" :bordered="false" size="small" />
        </n-spin>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NButton, NSpace, NTag, useMessage } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()

const checking = ref(false)
const reportsLoading = ref(false)
const protocols = ref([])
const rules = ref([])
const reports = ref([])
const checkResult = ref(null)
const checkForm = ref({ protocol: '', recording_id: '' })

const protocolOptions = computed(() =>
  protocols.value.map(p => ({ label: p, value: p }))
)

const reportColumns = computed(() => [
  { title: 'Report ID', key: 'id', width: 120, ellipsis: { tooltip: true } },
  { title: t('compliance.protocolCol'), key: 'protocol', width: 100 },
  { title: t('compliance.score'), key: 'compliance_score', width: 80,
    render: (row) => h(NTag, { size: 'small', type: row.passed ? 'success' : 'error', bordered: false },
      () => row.compliance_score + '%') },
  { title: t('compliance.totalMessages'), key: 'total_messages', width: 100 },
  { title: t('compliance.violationsCount'), key: 'violations', width: 100,
    render: (row) => (row.violations?.length || 0) },
  { title: t('compliance.created'), key: 'created_at', width: 160,
    render: (row) => row.created_at ? new Date(row.created_at * 1000).toLocaleString() : '-' },
  { title: t('common.action'), key: 'actions', width: 80,
    render: (row) => h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewReport(row.id) },
      () => t('testPlans.detail')) },
])

async function loadProtocols() {
  try {
    protocols.value = await api.listComplianceProtocols()
  } catch (e) {
    // Silent
  }
}

async function loadReports() {
  reportsLoading.value = true
  try {
    reports.value = await api.listComplianceReports()
  } catch (e) {
    message.error(t('compliance.loadReportsFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    reportsLoading.value = false
  }
}

async function onProtocolChange(protocol) {
  rules.value = []
  checkResult.value = null
  if (!protocol) return
  try {
    const data = await api.getComplianceRules(protocol)
    rules.value = data.rules || []
  } catch (e) {
    // Silent
  }
}

async function runCheck() {
  if (!checkForm.value.protocol) {
    message.warning(t('compliance.selectProtocolFirst'))
    return
  }
  checking.value = true
  checkResult.value = null
  try {
    checkResult.value = await api.runComplianceCheck({
      protocol: checkForm.value.protocol,
      recording_id: checkForm.value.recording_id || undefined,
    })
    if (checkResult.value) {
      message.success(t('compliance.checkComplete'))
    }
    await loadReports()
  } catch (e) {
    message.error(t('compliance.checkFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    checking.value = false
  }
}

async function viewReport(reportId) {
  try {
    checkResult.value = await api.getComplianceReport(reportId)
  } catch (e) {
    message.error(t('compliance.loadReportFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(async () => {
  await Promise.all([loadProtocols(), loadReports()])
})
</script>
