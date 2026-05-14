<template>
  <div>
    <n-space vertical size="large">

      <n-card size="small">
        <template #header>
          <n-space align="center" size="small">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            <span class="pf-section-title" style="font-size:16px">{{ t('testing.quickTest') }}</span>
          </n-space>
        </template>
        <template #header-extra>
          <n-button type="success" size="large" :loading="quickTesting" @click="runQuickTest('all')">
            <template #icon><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg></template>
            {{ t('testing.testAll') }}
          </n-button>
        </template>
        <n-space vertical>
          <n-text depth="3">{{ t('testing.testAllDesc') }}</n-text>
          <n-spin :show="loadingSuggestions">
            <n-space v-if="suggestions.length" vertical>
              <n-card v-for="s in suggestions" :key="s.title" size="small" hoverable
                :style="{ borderLeft: s.priority === 'high' ? '3px solid #d03050' : s.priority === 'medium' ? '3px solid #f0a020' : '3px solid #909399' }">
                <n-space justify="space-between" align="center">
                  <n-space align="center" size="small">
                    <n-tag :type="s.priority === 'high' ? 'error' : s.priority === 'medium' ? 'warning' : 'default'" size="small">
                      {{ s.priority === 'high' ? t('testing.important') : s.priority === 'medium' ? t('testing.suggested') : t('testing.optional') }}
                    </n-tag>
                    <n-text strong>{{ s.title }}</n-text>
                    <n-text depth="3" style="font-size:12px">{{ s.description }}</n-text>
                  </n-space>
                  <n-button type="primary" size="small" :loading="quickTesting" @click="runQuickTest(s.scope, s.target_id)">
                    {{ t('testing.testNow') }}
                  </n-button>
                </n-space>
              </n-card>
            </n-space>
            <n-empty v-else :description="t('testing.noSuggestions')" />
          </n-spin>
        </n-space>
      </n-card>

      <n-card v-if="lastReport" size="small">
        <template #header>
          <n-space align="center" size="small">
            <span :style="{ fontSize: '24px', color: (lastReport.failed || 0) > 0 || (lastReport.errors || 0) > 0 ? '#ef4444' : '#10b981' }">●</span>
            <span>{{ t('testing.testResults') }}</span>
            <n-tag :type="(lastReport.success_rate || 0) >= 100 ? 'success' : (lastReport.success_rate || 0) >= 50 ? 'warning' : 'error'" size="small">
              {{ t('testing.passRate') }} {{ lastReport.success_rate ?? 0 }}%
            </n-tag>
          </n-space>
        </template>
        <template #header-extra>
          <n-space size="small">
            <n-text depth="3" style="font-size:12px">{{ (lastReport.duration || 0).toFixed(2) }}s</n-text>
            <n-button size="small" @click="viewHtmlReport(lastReport.id)">{{ t('testing.htmlReport') }}</n-button>
          </n-space>
        </template>
        <n-space vertical size="small">
          <n-space size="large">
            <n-statistic :label="t('testing.total')" :value="lastReport.total || 0" />
            <n-statistic :label="t('testing.passed')" :value="lastReport.passed || 0">
              <template #default><span style="color:#18a058">{{ lastReport.passed || 0 }}</span></template>
            </n-statistic>
            <n-statistic :label="t('testing.failed')" :value="lastReport.failed || 0">
              <template #default><span style="color:#d03050">{{ lastReport.failed || 0 }}</span></template>
            </n-statistic>
            <n-statistic :label="t('testing.errors')" :value="lastReport.errors || 0">
              <template #default><span style="color:#f0a020">{{ lastReport.errors || 0 }}</span></template>
            </n-statistic>
          </n-space>
          <n-progress
            :percentage="lastReport.success_rate || 0"
            :color="(lastReport.success_rate || 0) >= 100 ? '#18a058' : (lastReport.success_rate || 0) >= 50 ? '#f0a020' : '#d03050'"
            :height="8" :show-indicator="false" />

          <n-collapse>
            <n-collapse-item v-for="tc in (lastReport.test_cases || [])" :key="tc.id"
              :name="tc.id">
              <template #header>
                <n-space align="center" size="small">
                  <span :style="{ color: tc.status === 'passed' ? '#18a058' : tc.status === 'failed' ? '#d03050' : '#f0a020', fontWeight: 600 }">
                    {{ tc.status === 'passed' ? '✓' : tc.status === 'failed' ? '✗' : '⚠' }}
                  </span>
                  <span>{{ tc.name }}</span>
                </n-space>
              </template>
              <template #header-extra>
                <n-tag :type="statusTagType(tc.status)" size="small">{{ tc.status }}</n-tag>
              </template>
              <div v-for="(s, i) in tc.steps" :key="i"
                :style="{ padding: '8px 12px', background: s.status === 'passed' ? '#f6ffed' : s.status === 'failed' ? '#fff2f0' : '#fffbe6', borderRadius: '4px', marginBottom: '4px' }">
                <n-space justify="space-between" align="center">
                  <n-space align="center" size="small">
                    <span :style="{ color: s.status === 'passed' ? '#18a058' : s.status === 'failed' ? '#d03050' : '#f0a020' }">
                      {{ s.status === 'passed' ? '✓' : s.status === 'failed' ? '✗' : '⚠' }}
                    </span>
                    <n-text>{{ s.name }}</n-text>
                    <n-tag size="tiny">{{ s.action }}</n-tag>
                  </n-space>
                  <n-text depth="3" style="font-size:12px">{{ (s.duration || 0).toFixed(3) }}s</n-text>
                </n-space>
                <div v-if="s.error" style="color:#d03050;font-size:12px;margin-top:4px;padding-left:20px">
                  {{ s.error }}
                </div>
                <div v-for="(ar, j) in (s.assertion_results || [])" :key="j"
                  :style="{ padding: '2px 0 2px 20px', fontSize: '12px', color: ar.passed ? '#18a058' : '#d03050' }">
                  {{ ar.passed ? '✓' : '✗' }} {{ ar.message }}
                </div>
              </div>
            </n-collapse-item>
          </n-collapse>
        </n-space>
      </n-card>

      <n-tabs type="line" animated>
        <n-tab-pane name="builder" :tab="t('testing.visualEdit')">
          <n-card size="small">
            <n-space vertical>
              <n-space align="center" size="small">
                <n-text strong>{{ t('testing.testName') }}:</n-text>
                <n-input v-model:value="builderCase.name" :placeholder="t('testing.inputTestName')" style="width:250px" />
                <n-text depth="3" style="font-size:12px">ID: {{ builderCase.id }}</n-text>
              </n-space>

              <n-divider style="margin:8px 0" />

              <n-space vertical size="small">
                <n-space justify="space-between" align="center">
                  <n-text strong>{{ t('testing.testSteps') }}</n-text>
                  <n-button size="small" type="primary" @click="addStep">{{ t('testing.addStep') }}</n-button>
                </n-space>

                <n-card v-for="(step, idx) in builderCase.steps" :key="idx" size="small"
                  :style="{ borderLeft: step.status === 'passed' ? '3px solid #18a058' : step.status === 'failed' ? '3px solid #d03050' : '3px solid #d9d9d9' }">
                  <n-space vertical size="small">
                    <n-space justify="space-between" align="center">
                      <n-text strong>{{ t('testing.stepIndex', { n: idx + 1 }) }}</n-text>
                      <n-space size="small">
                        <n-button size="tiny" quaternary :disabled="idx === 0" @click="moveStep(idx, -1)">↑</n-button>
                        <n-button size="tiny" quaternary :disabled="idx === builderCase.steps.length - 1" @click="moveStep(idx, 1)">↓</n-button>
                        <n-button size="tiny" quaternary type="error" @click="removeStep(idx)">{{ t('common.delete') }}</n-button>
                      </n-space>
                    </n-space>
                    <n-space align="center" size="small">
                      <n-text>{{ t('testing.operation') }}</n-text>
                      <n-select v-model:value="step.action" :options="actionTypeOptions" :placeholder="t('testing.selectOperation')"
                        style="width:180px" @update:value="onActionChange(step)" />
                      <n-input v-model:value="step.name" :placeholder="t('testing.stepName')" style="width:200px" />
                    </n-space>
                    <n-grid :cols="2" :x-gap="8" v-if="step.action">
                      <n-gi v-for="paramKey in getActionParams(step.action)" :key="paramKey">
                        <n-space align="center" size="small" style="margin-bottom:4px">
                          <n-text style="font-size:12px;min-width:70px">{{ paramLabel(paramKey) }}:</n-text>
                          <n-select v-if="paramKey === 'device_id'" v-model:value="step.params[paramKey]"
                            :options="deviceOptions" :placeholder="t('common.selectPlaceholder')" style="flex:1" />
                          <n-select v-else-if="paramKey === 'scenario_id'" v-model:value="step.params[paramKey]"
                            :options="scenarioOptions" :placeholder="t('common.selectPlaceholder')" style="flex:1" />
                          <n-select v-else-if="paramKey === 'protocol'" v-model:value="step.params[paramKey]"
                            :options="protocolOptions" :placeholder="t('common.selectPlaceholder')" style="flex:1" />
                          <n-select v-else-if="paramKey === 'point_name'" v-model:value="step.params[paramKey]"
                            :options="getPointOptions(step.params.device_id)" :placeholder="t('common.selectPlaceholder')" style="flex:1" />
                          <n-input-number v-else-if="paramKey === 'seconds' || paramKey === 'value'"
                            v-model:value="step.params[paramKey]" :placeholder="paramKey" style="flex:1" />
                          <n-input v-else v-model:value="step.params[paramKey]" :placeholder="paramKey" style="flex:1" />
                        </n-space>
                      </n-gi>
                    </n-grid>

                    <n-space align="center" size="small">
                      <n-text style="font-size:12px">{{ t('testing.assertions') }}:</n-text>
                      <n-button size="tiny" @click="addAssertion(step)">{{ t('testing.addCheck') }}</n-button>
                    </n-space>
                    <n-space v-for="(asrt, ai) in step.assertions" :key="ai" align="center" size="small"
                      style="padding-left:12px">
                      <n-select v-model:value="asrt.type" :options="simpleAssertionOptions" :placeholder="t('testing.checkType')"
                        style="width:150px" />
                      <n-input-number v-if="needsExpected(asrt.type)" v-model:value="asrt.expected"
                        :placeholder="t('testing.expectedValue')" style="width:120px" />
                      <n-input v-model:value="asrt.message" :placeholder="t('testing.optionalNote')" style="width:200px" />
                      <n-button size="tiny" quaternary type="error" @click="step.assertions.splice(ai, 1)">×</n-button>
                    </n-space>
                  </n-space>
                </n-card>

                <n-empty v-if="!builderCase.steps.length" :description="t('testing.noSteps')" size="small" />
              </n-space>

              <n-divider style="margin:8px 0" />
              <n-space>
                <n-button type="primary" :loading="runningBuilder" @click="runBuilderTest">{{ t('testing.executeTest') }}</n-button>
                <n-button @click="saveBuilderCase">{{ t('testing.saveAsCase') }}</n-button>
                <n-button @click="exportBuilderJson">{{ t('testing.exportJson') }}</n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-tab-pane>

        <n-tab-pane name="json" :tab="t('testing.jsonEdit')">
          <n-space vertical>
            <n-space>
              <n-text depth="3">{{ t('testing.presetTemplates') }}</n-text>
              <n-button size="small" v-for="tpl in presetTemplates" :key="tpl.name"
                @click="testJson = tpl.json">{{ tpl.name }}</n-button>
            </n-space>
            <n-input v-model:value="testJson" type="textarea" :rows="12" :placeholder="t('testing.inputJson')" />
            <n-space>
              <n-button type="primary" @click="runJsonTest" :loading="runningJson">{{ t('testing.executeTest') }}</n-button>
              <n-button @click="formatJson">{{ t('testing.formatJson') }}</n-button>
              <n-button @click="saveJsonAsCase">{{ t('testing.saveJsonAsCase') }}</n-button>
            </n-space>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="cases" :tab="t('testing.caseManagement')">
          <n-space justify="space-between" style="margin-bottom:12px">
            <n-h4 style="margin:0">{{ t('testing.caseList') }}</n-h4>
            <n-input v-model:value="caseTagFilter" :placeholder="t('testing.filterByTag')" size="small" style="width:150px" clearable />
          </n-space>
          <n-data-table :columns="caseColumns" :data="filteredCases" :bordered="false" size="small"
            :pagination="{ pageSize: 10 }" />
        </n-tab-pane>

        <n-tab-pane name="suites" :tab="t('testing.testSuite')">
          <n-space justify="space-between" style="margin-bottom:12px">
            <n-h4 style="margin:0">{{ t('testing.suiteList') }}</n-h4>
            <n-button type="primary" size="small" @click="showSuiteModal = true">{{ t('testing.createSuite') }}</n-button>
          </n-space>
          <n-data-table :columns="suiteColumns" :data="suites" :bordered="false" size="small"
            :pagination="{ pageSize: 10 }" />
        </n-tab-pane>

        <n-tab-pane name="history" :tab="t('testing.historyReports')">
          <n-space vertical>
            <n-space justify="space-between" align="center">
              <n-text depth="3">{{ t('testing.historyReportsTitle') }}</n-text>
              <n-button size="small" @click="loadReportTrend" :loading="loadingTrend">{{ t('testing.viewTrend') }}</n-button>
            </n-space>
            <n-data-table :columns="reportColumns" :data="reports" :bordered="false" size="small"
              :pagination="{ pageSize: 10 }" />
            <n-card v-if="trendData.length > 0" size="small" :title="t('testing.testTrend')">
              <n-space vertical>
                <n-grid :cols="3" :x-gap="12">
                  <n-gi v-for="(item, idx) in trendData" :key="idx">
                    <n-card size="small" embedded>
                      <n-statistic :label="item.name || t('testing.reportIndex', { n: idx + 1 })">
                        <template #default>
                          <span :style="{ color: (item.success_rate || 0) >= 100 ? '#18a058' : (item.success_rate || 0) >= 50 ? '#f0a020' : '#d03050' }">
                            {{ item.success_rate ?? 0 }}%
                          </span>
                        </template>
                      </n-statistic>
                      <n-text depth="3" style="font-size:12px">{{ item.passed || 0 }}/{{ item.total || 0 }} {{ t('testing.passed') }}</n-text>
                    </n-card>
                  </n-gi>
                </n-grid>
              </n-space>
            </n-card>
          </n-space>
        </n-tab-pane>
      </n-tabs>

      <n-modal v-model:show="showSuiteModal" preset="card" :title="t('testing.createSuiteTitle')" style="width: 500px">
        <n-space vertical>
          <n-input v-model:value="suiteForm.name" :placeholder="t('testing.suiteName')" />
          <n-input v-model:value="suiteForm.description" :placeholder="t('common.description')" type="textarea" :rows="2" />
          <n-select v-model:value="suiteForm.test_case_ids" :options="caseOptions" multiple :placeholder="t('testing.selectCases')" />
          <n-dynamic-tags v-model:value="suiteForm.tags" />
          <n-button type="primary" @click="createSuite" :loading="creatingSuite">{{ t('common.create') }}</n-button>
        </n-space>
      </n-modal>

      <n-modal v-model:show="showEditCaseModal" preset="card" :title="t('testing.editCaseTitle')" style="width: 600px">
        <n-space vertical>
          <n-form :model="editCaseForm" label-placement="left" label-width="80">
            <n-form-item :label="t('testing.caseName')">
              <n-input v-model:value="editCaseForm.name" :placeholder="t('testing.caseName')" />
            </n-form-item>
            <n-form-item :label="t('testing.caseTags')">
              <n-dynamic-tags v-model:value="editCaseForm.tags" />
            </n-form-item>
          </n-form>
          <n-text depth="3" style="font-size:12px">{{ t('testing.stepEditHint') }}</n-text>
        </n-space>
        <template #action>
          <n-space>
            <n-button @click="showEditCaseModal = false">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" @click="doUpdateTestCase" :loading="updatingCase">{{ t('common.save') }}</n-button>
          </n-space>
        </template>
      </n-modal>

      <n-modal v-model:show="showSuiteDetailModal" preset="card" :title="t('testing.suiteDetailTitle')" style="width: 600px">
        <n-space vertical v-if="suiteDetail">
          <n-descriptions label-placement="left" :column="1" bordered size="small">
            <n-descriptions-item :label="t('common.name')">{{ suiteDetail.name }}</n-descriptions-item>
            <n-descriptions-item :label="t('common.description')">{{ suiteDetail.description || '-' }}</n-descriptions-item>
            <n-descriptions-item :label="t('testing.caseCount')">{{ (suiteDetail.test_case_ids || []).length }}</n-descriptions-item>
          </n-descriptions>
          <n-text strong style="font-size:13px">{{ t('testing.includedCases') }}</n-text>
          <n-data-table :columns="suiteDetailCaseColumns" :data="suiteDetailCases" :bordered="false" size="small" />
        </n-space>
        <template #action>
          <n-button @click="showSuiteDetailModal = false">{{ t('common.close') }}</n-button>
        </template>
      </n-modal>

      <n-modal v-model:show="showReportDetailModal" preset="card" :title="t('testing.reportDetailTitle')" style="width: 700px">
        <n-space vertical v-if="reportDetail">
          <n-grid :cols="4" :x-gap="12">
            <n-gi><n-statistic :label="t('testing.total')" :value="reportDetail.total || 0" /></n-gi>
            <n-gi><n-statistic :label="t('testing.passed')" :value="reportDetail.passed || 0" /></n-gi>
            <n-gi><n-statistic :label="t('testing.failed')" :value="reportDetail.failed || 0" /></n-gi>
            <n-gi><n-statistic :label="t('testing.passRateLabel')" :value="(reportDetail.success_rate ?? 0) + '%'" /></n-gi>
          </n-grid>
          <n-collapse v-if="reportDetail.test_cases">
            <n-collapse-item v-for="tc in reportDetail.test_cases" :key="tc.id" :name="tc.id">
              <template #header>
                <n-space align="center" size="small">
                  <span :style="{ color: tc.status === 'passed' ? '#18a058' : '#d03050', fontWeight: 600 }">
                    {{ tc.status === 'passed' ? '✓' : '✗' }}
                  </span>
                  <span>{{ tc.name }}</span>
                </n-space>
              </template>
              <div v-for="(s, i) in tc.steps" :key="i" style="padding:4px 8px;font-size:12px">
                {{ s.status === 'passed' ? '✓' : '✗' }} {{ s.name }} ({{ s.action }})
                <span v-if="s.error" style="color:#d03050"> - {{ s.error }}</span>
              </div>
            </n-collapse-item>
          </n-collapse>
        </n-space>
        <template #action>
          <n-space>
            <n-button @click="showReportDetailModal = false">{{ t('common.close') }}</n-button>
            <n-button type="primary" @click="viewHtmlReport(reportDetail.id)">{{ t('testing.htmlReport') }}</n-button>
          </n-space>
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, h } from 'vue'
import { useMessage, useDialog, NStatistic, NGrid, NGi, NDescriptions, NDescriptionsItem, NCollapse, NCollapseItem, NDynamicTags, NButton, NSpace } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()

const suggestions = ref([])
const loadingSuggestions = ref(false)
const quickTesting = ref(false)
const runningCaseIds = reactive(new Set())  // FIXED: ref→reactive，Set响应性更可靠
const runningSuiteIds = reactive(new Set())
const lastReport = ref(null)
const testJson = ref('')
const runningJson = ref(false)
const runningBuilder = ref(false)
const reports = ref([])
const testCases = ref([])
const suites = ref([])
const caseTagFilter = ref('')
const showSuiteModal = ref(false)
const creatingSuite = ref(false)
const suiteForm = ref({ name: '', description: '', test_case_ids: [], tags: [] })
const actionTypes = ref([])
const assertionTypes = ref([])
const devices = ref([])
const scenarios = ref([])
const protocols = ref([])

const showEditCaseModal = ref(false)
const updatingCase = ref(false)
const editCaseForm = ref({ id: '', name: '', tags: [] })

const showSuiteDetailModal = ref(false)
const suiteDetail = ref(null)
const suiteDetailCases = ref([])

const showReportDetailModal = ref(false)
const reportDetail = ref(null)

const loadingTrend = ref(false)
const trendData = ref([])

const builderCase = ref({
  id: 'tc-' + Date.now().toString(36),
  name: '',
  steps: [],
})

const presetTemplates = [
  {
    name: t('testing.connectivityTest'),
    json: JSON.stringify([{
      id: "tc-connectivity", name: t('testing.connectivityTest'), tags: ["smoke"],
      steps: [
        { name: t('testing.createDevice'), action: "create_device", params: { id: "test-conn", name: t('testing.connectivityTestDevice'), protocol: "http", points: [{ name: "value", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] }, assertions: [{ type: "status_code", expected: 200, message: t('testing.createDeviceShould200') }] },
        { name: t('testing.readPoints'), action: "read_points", params: { device_id: "test-conn" }, assertions: [{ type: "length_greater", expected: 0, message: t('testing.pointsNotEmptyAssert') }] },
        { name: t('testing.writePoint'), action: "write_point", params: { device_id: "test-conn", point_name: "value", value: 42.5 }, assertions: [{ type: "status_code", expected: 200, message: t('testing.writeShould200') }] },
        { name: t('testing.cleanup'), action: "delete_device", params: { device_id: "test-conn" } }
      ]
    }], null, 2),
  },
  {
    name: t('testing.batchDeviceTest'),
    json: JSON.stringify([{
      id: "tc-batch", name: t('testing.batchDeviceTest'), tags: ["batch"],
      steps: [
        { name: t('testing.batchCreate'), action: "batch_create_devices", params: { devices: [
          { id: "batch-1", name: t('testing.batch1'), protocol: "http", points: [{ name: "v", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] },
          { id: "batch-2", name: t('testing.batch2'), protocol: "http", points: [{ name: "v", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] },
        ]}, assertions: [{ type: "status_code", expected: 200, message: t('testing.batchCreateShould200') }] },
        { name: t('testing.queryDeviceList'), action: "list_devices", assertions: [{ type: "length_greater", expected: 1, message: t('testing.deviceListNotEmpty') }] },
        { name: t('testing.batchDelete'), action: "batch_delete_devices", params: { device_ids: ["batch-1", "batch-2"] } }
      ]
    }], null, 2),
  },
  {
    name: t('testing.scenarioSimTest'),
    json: JSON.stringify([{
      id: "tc-scenario", name: t('testing.scenarioSimTest'), tags: ["scenario"],
      steps: [
        { name: t('testing.createScenario'), action: "create_scenario", params: { id: "test-scene", name: t('testing.testScenarioName'), devices: [], rules: [] }, assertions: [{ type: "status_code", expected: 200, message: t('testing.createScenarioShould200') }] },
        { name: t('testing.startScenario'), action: "start_scenario", params: { scenario_id: "test-scene" } },
        { name: t('testing.waitSeconds'), action: "wait", params: { seconds: 2 } },
        { name: t('testing.stopScenario'), action: "stop_scenario", params: { scenario_id: "test-scene" } },
        { name: t('testing.deleteScenario'), action: "delete_scenario", params: { scenario_id: "test-scene" } }
      ]
    }], null, 2),
  },
]

const statusTagType = (status) => {
  const map = { passed: 'success', failed: 'error', error: 'warning', running: 'info', pending: 'default', skipped: 'default' }
  return map[status] || 'default'
}

const filteredCases = computed(() => {
  if (!caseTagFilter.value) return testCases.value
  return testCases.value.filter(c => c.tags && c.tags.includes(caseTagFilter.value))
})

const caseOptions = computed(() => testCases.value.map(c => ({ label: c.name || c.id, value: c.id })))

const actionTypeOptions = computed(() => {
  const categories = {}
  for (const at of actionTypes.value) {
    if (!categories[at.category]) categories[at.category] = []
    categories[at.category].push(at)
  }
  const result = []
  for (const [cat, items] of Object.entries(categories)) {
    result.push({ type: 'group', label: cat, key: cat })
    for (const item of items) {
      result.push({ label: item.label, value: item.value })
    }
  }
  return result
})

const simpleAssertionOptions = computed(() => {
  return assertionTypes.value.map(a => ({ label: a.label, value: a.value }))
})

const deviceOptions = computed(() => devices.value.map(d => ({ label: d.name || d.id, value: d.id })))
const scenarioOptions = computed(() => scenarios.value.map(s => ({ label: s.name || s.id, value: s.id })))
const protocolOptions = computed(() => protocols.value.map(p => ({ label: p.name || p, value: p.name || p })))

function getActionParams(action) {
  const at = actionTypes.value.find(a => a.value === action)
  return at ? at.params : []
}

function getPointOptions(deviceId) {
  const dev = devices.value.find(d => d.id === deviceId)
  if (!dev || !dev.points) return []
  return dev.points.map(p => ({ label: p.name, value: p.name }))
}

function paramLabel(key) {
  const labels = {
    device_id: t('testing.paramDevice'), scenario_id: t('testing.paramScenario'), protocol: t('common.protocol'), template_id: t('common.type'),
    point_name: t('testing.paramPoint'), seconds: t('common.port'), value: t('common.value'), method: t('testing.paramMethod'), url: t('testing.paramUrl'),
    id: t('testing.paramId'), name: t('common.name'), device_ids: t('testing.paramDeviceIds'),
  }
  return labels[key] || key
}

function needsExpected(type) {
  return ['status_code', 'equals', 'not_equals', 'greater_than', 'less_than', 'length_equals', 'length_greater', 'length_less'].includes(type)
}

function onActionChange(step) {
  step.params = {}
  step.assertions = []
  const params = getActionParams(step.action)
  for (const p of params) {
    step.params[p] = undefined
  }
  if (['create_device', 'start_protocol', 'start_scenario', 'write_point'].includes(step.action)) {
    step.assertions.push({ type: 'status_code', expected: 200, message: t('testing.actionShouldSucceed') })
  }
  if (step.action === 'read_points') {
    step.assertions.push({ type: 'length_greater', expected: 0, message: t('testing.pointsNotEmpty') })
  }
  if (!step.name) {
    const at = actionTypes.value.find(a => a.value === step.action)
    step.name = at ? at.label : step.action
  }
}

function addStep() {
  builderCase.value.steps.push({
    name: '', action: '', params: {}, assertions: [],
  })
}

function removeStep(idx) {
  builderCase.value.steps.splice(idx, 1)
}

function moveStep(idx, dir) {
  const steps = builderCase.value.steps
  const newIdx = idx + dir
  if (newIdx < 0 || newIdx >= steps.length) return
  const temp = steps[idx]
  steps[idx] = steps[newIdx]
  steps[newIdx] = temp
  builderCase.value.steps = [...steps]
}

function addAssertion(step) {
  step.assertions.push({ type: 'status_code', expected: 200, message: '' })
}

function builderCaseToJson() {
  return [{
    id: builderCase.value.id,
    name: builderCase.value.name || t('testing.unnamedTest'),
    tags: ['custom'],
    steps: builderCase.value.steps.map(s => ({
      name: s.name,
      action: s.action,
      params: Object.fromEntries(Object.entries(s.params).filter(([_, v]) => v !== undefined && v !== '')),
      assertions: s.assertions.filter(a => a.type),
    })),
  }]
}

async function runBuilderTest() {
  if (!builderCase.value.steps.length) {
    message.warning(t('testing.addStepsFirst'))
    return
  }
  runningBuilder.value = true
  try {
    const cases = builderCaseToJson()
    const res = await api.runTests(cases)
    lastReport.value = res
    await loadReports()
    message.success(t('testing.testComplete'))
  } catch (e) {
    message.error(t('testing.testExecFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    runningBuilder.value = false
  }
}

async function saveBuilderCase() {
  try {
    const cases = builderCaseToJson()
    await api.createTestCase(cases[0])
    await loadCases()
    message.success(t('testing.caseSaved'))
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error(t('testing.jsonParseError') + ': ' + e.message)
    } else {
      message.error(t('common.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
    }
  }
}

function exportBuilderJson() {
  try {
    const json = JSON.stringify(builderCaseToJson(), null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `test_${builderCase.value.id}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(t('common.exportFailed') + ': ' + (e.message || t('common.unknownError')))
  }
}

async function runQuickTest(scope, targetId) {
  const scopeLabels = { all: t('testing.testAll'), protocol: t('testing.protocolDevices'), device: t('testing.specifiedDevice') }
  const scopeLabel = scopeLabels[scope] || scope
  dialog.info({
    title: t('testing.confirmQuickTest'),
    content: t('testing.confirmQuickTestDesc', { scope: scopeLabel }),
    positiveText: t('testing.executeTest'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      quickTesting.value = true
      try {
        const res = await api.quickTest(scope, targetId)
        lastReport.value = res
        await loadReports()
        if ((res.success_rate || 0) >= 100) {
          message.success(t('testing.quickTestComplete', { total: res.total || 0 }))
        } else {
          message.warning(t('testing.quickTestPartial', { passed: res.passed || 0, total: res.total || 0, failed: res.failed || 0 }))
        }
      } catch (e) {
        message.error(t('testing.quickTestFailed') + ': ' + (e.response?.data?.detail || e.message))
      } finally {
        quickTesting.value = false
      }
    }
  })
}

async function runJsonTest() {
  runningJson.value = true
  try {
    const cases = JSON.parse(testJson.value)
    const res = await api.runTests(cases)
    lastReport.value = res
    await loadReports()
    message.success(t('testing.testComplete'))
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error(t('testing.jsonParseError') + ': ' + e.message)
    } else {
      message.error(t('testing.testExecFailed') + ': ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    runningJson.value = false
  }
}

function formatJson() {
  try {
    const parsed = JSON.parse(testJson.value)
    testJson.value = JSON.stringify(parsed, null, 2)
    message.success(t('testing.formatComplete'))
  } catch (e) {
    message.error(t('testing.jsonFormatError'))
  }
}

async function saveJsonAsCase() {
  try {
    const cases = JSON.parse(testJson.value)
    if (!Array.isArray(cases)) {
      message.error(t('testing.jsonMustBeArray'))
      return
    }
    for (let i = 0; i < cases.length; i++) {
      const c = cases[i]
      if (!c.id || typeof c.id !== 'string') {
        message.error(t('testing.caseMissingId', { index: i + 1 }))
        return
      }
      if (!c.steps || !Array.isArray(c.steps) || c.steps.length === 0) {
        message.error(t('testing.caseMissingSteps', { id: c.id }))
        return
      }
      for (let j = 0; j < c.steps.length; j++) {
        const s = c.steps[j]
        if (!s.action || typeof s.action !== 'string') {
          message.error(t('testing.stepMissingAction', { id: c.id, index: j + 1 }))
          return
        }
      }
    }
    for (const c of cases) {
      await api.createTestCase(c)
    }
    await loadCases()
    message.success(t('testing.caseSaved'))
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error(t('testing.jsonParseError') + ': ' + e.message)
    } else {
      message.error(t('common.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
    }
  }
}

async function runCaseById(caseId) {
  runningCaseIds.add(caseId)
  try {
    const res = await api.runTestCase(caseId)
    lastReport.value = res
    await loadReports()
    message.success(t('testing.testComplete'))
  } catch (e) {
    message.error(t('common.operationFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { runningCaseIds.delete(caseId) }
}

async function runSuiteById(suiteId) {
  runningSuiteIds.add(suiteId)
  try {
    const res = await api.runTestSuite(suiteId)
    lastReport.value = res
    await loadReports()
    message.success(t('testing.testComplete'))
  } catch (e) {
    message.error(t('common.operationFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { runningSuiteIds.delete(suiteId) }
}

async function loadCaseToEditor(caseId) {
  try {
    const c = await api.getTestCase(caseId)
    builderCase.value = {
      id: c.id,
      name: c.name,
      steps: (c.steps || []).map(s => ({
        name: s.name || '',
        action: s.action || '',
        params: s.params || {},
        assertions: (s.assertions || []).map(a => ({
          type: a.type || 'status_code',
          expected: a.expected,
          message: a.message || '',
        })),
      })),
    }
    message.success(t('testing.caseLoaded'))
  } catch (e) {
    message.error(t('testing.caseLoadFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteCase(caseId) {
  dialog.warning({
    title: t('testing.confirmDeleteCase'),
    content: t('testing.confirmDeleteCaseDesc'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.deleteTestCase(caseId)
        await loadCases()
        message.success(t('testing.caseDeleted'))
      } catch (e) {
        message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function deleteSuite(suiteId) {
  dialog.warning({
    title: t('testing.confirmDeleteSuite'),
    content: t('testing.confirmDeleteSuiteDesc'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.deleteTestSuite(suiteId)
        await loadSuites()
        message.success(t('testing.suiteDeleted'))
      } catch (e) {
        message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
      }
    }
  })
}

async function viewHtmlReport(id) {
  try {
    const res = await api.getTestReportHtml(id)
    const html = typeof res === 'string' ? res : JSON.stringify(res)
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (e) {
    message.error(t('testing.reportLoadFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function createSuite() {
  if (!suiteForm.value.name?.trim()) { message.warning(t('testing.suiteNameRequired')); return }
  creatingSuite.value = true
  try {
    await api.createTestSuite(suiteForm.value)
    showSuiteModal.value = false
    suiteForm.value = { name: '', description: '', test_case_ids: [], tags: [] }
    await loadSuites()
    message.success(t('testing.suiteCreated'))
  } catch (e) {
    message.error(t('common.createFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    creatingSuite.value = false
  }
}

async function loadSuggestions() {
  loadingSuggestions.value = true
  try {
    suggestions.value = (await api.getTestSuggestions()) || []  // FIXED: API返回null时后续操作崩溃
  } catch (e) { message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message)) } finally {
    loadingSuggestions.value = false
  }
}

async function loadMetadata() {
  try {
    const results = await Promise.allSettled([
      api.getTestActionTypes(),
      api.getTestAssertionTypes(),
      api.getDevices(),
      api.getScenarios(),
      api.getProtocols(),
    ])
    actionTypes.value = results[0].status === 'fulfilled' ? (results[0].value || []) : []
    assertionTypes.value = results[1].status === 'fulfilled' ? (results[1].value || []) : []
    devices.value = results[2].status === 'fulfilled' ? (results[2].value || []) : []
    scenarios.value = results[3].status === 'fulfilled' ? (results[3].value || []) : []
    protocols.value = results[4].status === 'fulfilled' ? (results[4].value || []) : []
    const failedIdx = results.map((r, i) => r.status === 'rejected' ? i : -1).filter(i => i >= 0)
    if (failedIdx.length > 0) {
      const names = t('testing.metadataNames').split(',')
      message.warning(t('testing.partialMetadataFailed', { items: failedIdx.map(i => names[i]).join(t('common.listSeparator') || '、') }))
    }
  } catch (e) { message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function loadReports() {
  try { reports.value = (await api.listTestReports()) || [] } catch (e) { message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function loadCases() {
  try { testCases.value = (await api.listTestCases()) || [] } catch (e) { message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

async function loadSuites() {
  try { suites.value = (await api.listTestSuites()) || [] } catch (e) { message.error(t('common.loadFailed') + ': ' + (e.response?.data?.detail || e.message)) }
}

const caseColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 150 },
  { title: t('common.filter'), key: 'tags', width: 150, render: (row) => (row.tags || []).map(tag => h('span', { style: 'background:#f0f0f0;padding:1px 6px;border-radius:3px;margin-right:2px;font-size:11px' }, tag)) },
  { title: t('testing.stepCount'), key: 'steps', width: 70, render: (row) => (row.steps || []).length },
  {
    title: t('common.action'), key: 'actions', width: 260,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'success', loading: runningCaseIds.has(row.id), onClick: () => runCaseById(row.id) }, () => t('common.test')),
      h(NButton, { size: 'tiny', type: 'info', onClick: () => openEditCase(row) }, () => t('common.edit')),
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => loadCaseToEditor(row.id) }, () => t('testing.loadToEditor')),
      h(NButton, { size: 'tiny', type: 'error', onClick: () => deleteCase(row.id) }, () => t('common.delete')),
    ])
  },
])

const suiteColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 150 },
  { title: t('testing.caseCount'), key: 'test_case_ids', width: 80, render: (row) => (row.test_case_ids || []).length },
  {
    title: t('common.action'), key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'success', loading: runningSuiteIds.has(row.id), onClick: () => runSuiteById(row.id) }, () => t('common.test')),
      h(NButton, { size: 'tiny', type: 'info', onClick: () => viewSuiteDetail(row.id) }, () => t('common.detail')),
      h(NButton, { size: 'tiny', type: 'error', onClick: () => deleteSuite(row.id) }, () => t('common.delete')),
    ])
  },
])

const reportColumns = computed(() => [
  { title: t('common.name'), key: 'name', width: 150 },
  { title: t('testing.total'), key: 'total', width: 60 },
  { title: t('testing.passed'), key: 'passed', width: 60 },
  { title: t('testing.failed'), key: 'failed', width: 60 },
  { title: t('testing.passRate'), key: 'success_rate', width: 80, render: (row) => `${row.success_rate ?? 0}%` },
  { title: t('testing.duration'), key: 'duration', width: 80, render: (row) => `${(row.duration || 0).toFixed(2)}s` },
  {
    title: t('common.action'), key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', type: 'info', onClick: () => viewReportDetail(row.id) }, () => t('common.detail')),
      h(NButton, { size: 'tiny', type: 'success', onClick: () => { lastReport.value = row } }, () => t('testing.viewReport')),
      h(NButton, { size: 'tiny', type: 'primary', onClick: () => viewHtmlReport(row.id) }, () => 'HTML'),
    ])
  },
])

const suiteDetailCaseColumns = computed(() => [
  { title: t('testing.caseId'), key: 'id', width: 180 },
  { title: t('common.name'), key: 'name', width: 150 },
  { title: t('testing.stepCount'), key: 'steps', width: 80, render: (row) => (row.steps || []).length },
])

async function openEditCase(row) {
  editCaseForm.value = { id: row.id, name: row.name || '', tags: [...(row.tags || [])] }
  showEditCaseModal.value = true
}

async function doUpdateTestCase() {
  if (!editCaseForm.value.name) { message.warning(t('testing.caseNameRequired')); return }
  updatingCase.value = true
  try {
    await api.updateTestCase(editCaseForm.value.id, {
      name: editCaseForm.value.name,
      tags: editCaseForm.value.tags,
    })
    showEditCaseModal.value = false
    message.success(t('testing.caseUpdated'))
    await loadCases()
  } catch (e) {
    message.error(t('common.updateFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { updatingCase.value = false }
}

async function viewSuiteDetail(suiteId) {
  try {
    const res = await api.getTestSuite(suiteId)
    suiteDetail.value = res
    suiteDetailCases.value = (res.test_case_ids || []).map(id => {
      const c = testCases.value.find(tc => tc.id === id)
      return c || { id, name: t('testing.unknownCase'), steps: [] }
    })
    showSuiteDetailModal.value = true
  } catch (e) {
    message.error(t('testing.suiteDetailFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function viewReportDetail(reportId) {
  try {
    const res = await api.getTestReport(reportId)
    reportDetail.value = res
    showReportDetailModal.value = true
  } catch (e) {
    message.error(t('testing.reportDetailFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function loadReportTrend() {
  loadingTrend.value = true
  try {
    const res = await api.getReportTrend({ count: 10 })
    trendData.value = Array.isArray(res) ? res : (res.trends || [])
  } catch (e) {
    message.error(t('testing.trendLoadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally { loadingTrend.value = false }
}

onMounted(() => {
  loadSuggestions()
  loadMetadata()
  loadReports()
  loadCases()
  loadSuites()
})
</script>
