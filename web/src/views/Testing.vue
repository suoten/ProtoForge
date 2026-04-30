<template>
  <div>
    <n-space vertical size="large">

      <n-card size="small">
        <template #header>
          <n-space align="center" size="small">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            <span class="pf-section-title" style="font-size:16px">快速测试</span>
          </n-space>
        </template>
        <template #header-extra>
          <n-button type="success" size="large" :loading="quickTesting" @click="runQuickTest('all')">
            <template #icon><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg></template>
            一键测试全部
          </n-button>
        </template>
        <n-space vertical>
          <n-text depth="3">系统根据当前设备、场景自动生成测试，一键执行</n-text>
          <n-spin :show="loadingSuggestions">
            <n-space v-if="suggestions.length" vertical>
              <n-card v-for="s in suggestions" :key="s.title" size="small" hoverable
                :style="{ borderLeft: s.priority === 'high' ? '3px solid #d03050' : s.priority === 'medium' ? '3px solid #f0a020' : '3px solid #909399' }">
                <n-space justify="space-between" align="center">
                  <n-space align="center" size="small">
                    <n-tag :type="s.priority === 'high' ? 'error' : s.priority === 'medium' ? 'warning' : 'default'" size="small">
                      {{ s.priority === 'high' ? '重要' : s.priority === 'medium' ? '建议' : '可选' }}
                    </n-tag>
                    <n-text strong>{{ s.title }}</n-text>
                    <n-text depth="3" style="font-size:12px">{{ s.description }}</n-text>
                  </n-space>
                  <n-button type="primary" size="small" :loading="quickTesting" @click="runQuickTest(s.scope, s.target_id)">
                    立即测试
                  </n-button>
                </n-space>
              </n-card>
            </n-space>
            <n-empty v-else description="暂无测试建议，请先创建设备或场景" />
          </n-spin>
        </n-space>
      </n-card>

      <n-card v-if="lastReport" size="small">
        <template #header>
          <n-space align="center" size="small">
            <span :style="{ fontSize: '24px', color: lastReport.failed > 0 || lastReport.errors > 0 ? '#ef4444' : '#10b981' }">●</span>
            <span>测试结果</span>
            <n-tag :type="lastReport.success_rate >= 100 ? 'success' : lastReport.success_rate >= 50 ? 'warning' : 'error'" size="small">
              通过率 {{ lastReport.success_rate }}%
            </n-tag>
          </n-space>
        </template>
        <template #header-extra>
          <n-space size="small">
            <n-text depth="3" style="font-size:12px">{{ (lastReport.duration || 0).toFixed(2) }}s</n-text>
            <n-button size="small" @click="viewHtmlReport(lastReport.id)">HTML报告</n-button>
          </n-space>
        </template>
        <n-space vertical size="small">
          <n-space size="large">
            <n-statistic label="总数" :value="lastReport.total" />
            <n-statistic label="通过" :value="lastReport.passed">
              <template #default><span style="color:#18a058">{{ lastReport.passed }}</span></template>
            </n-statistic>
            <n-statistic label="失败" :value="lastReport.failed">
              <template #default><span style="color:#d03050">{{ lastReport.failed }}</span></template>
            </n-statistic>
            <n-statistic label="错误" :value="lastReport.errors">
              <template #default><span style="color:#f0a020">{{ lastReport.errors }}</span></template>
            </n-statistic>
          </n-space>
          <n-progress
            :percentage="lastReport.success_rate"
            :color="lastReport.success_rate >= 100 ? '#18a058' : lastReport.success_rate >= 50 ? '#f0a020' : '#d03050'"
            :height="8" :show-indicator="false" />

          <n-collapse>
            <n-collapse-item v-for="tc in lastReport.test_cases" :key="tc.id"
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
        <n-tab-pane name="builder" tab="可视化编辑">
          <n-card size="small">
            <n-space vertical>
              <n-space align="center" size="small">
                <n-text strong>测试名称:</n-text>
                <n-input v-model:value="builderCase.name" placeholder="输入测试名称" style="width:250px" />
                <n-text depth="3" style="font-size:12px">ID: {{ builderCase.id }}</n-text>
              </n-space>

              <n-divider style="margin:8px 0" />

              <n-space vertical size="small">
                <n-space justify="space-between" align="center">
                  <n-text strong>测试步骤</n-text>
                  <n-button size="small" type="primary" @click="addStep">+ 添加步骤</n-button>
                </n-space>

                <n-card v-for="(step, idx) in builderCase.steps" :key="idx" size="small"
                  :style="{ borderLeft: step.status === 'passed' ? '3px solid #18a058' : step.status === 'failed' ? '3px solid #d03050' : '3px solid #d9d9d9' }">
                  <n-space vertical size="small">
                    <n-space justify="space-between" align="center">
                      <n-text strong>步骤 {{ idx + 1 }}</n-text>
                      <n-space size="small">
                        <n-button size="tiny" quaternary :disabled="idx === 0" @click="moveStep(idx, -1)">↑</n-button>
                        <n-button size="tiny" quaternary :disabled="idx === builderCase.steps.length - 1" @click="moveStep(idx, 1)">↓</n-button>
                        <n-button size="tiny" quaternary type="error" @click="removeStep(idx)">删除</n-button>
                      </n-space>
                    </n-space>
                    <n-space align="center" size="small">
                      <n-text>操作:</n-text>
                      <n-select v-model:value="step.action" :options="actionTypeOptions" placeholder="选择操作"
                        style="width:180px" @update:value="onActionChange(step)" />
                      <n-input v-model:value="step.name" placeholder="步骤名称" style="width:200px" />
                    </n-space>
                    <n-grid :cols="2" :x-gap="8" v-if="step.action">
                      <n-gi v-for="paramKey in getActionParams(step.action)" :key="paramKey">
                        <n-space align="center" size="small" style="margin-bottom:4px">
                          <n-text style="font-size:12px;min-width:70px">{{ paramLabel(paramKey) }}:</n-text>
                          <n-select v-if="paramKey === 'device_id'" v-model:value="step.params[paramKey]"
                            :options="deviceOptions" placeholder="选择设备" style="flex:1" />
                          <n-select v-else-if="paramKey === 'scenario_id'" v-model:value="step.params[paramKey]"
                            :options="scenarioOptions" placeholder="选择场景" style="flex:1" />
                          <n-select v-else-if="paramKey === 'protocol'" v-model:value="step.params[paramKey]"
                            :options="protocolOptions" placeholder="选择协议" style="flex:1" />
                          <n-select v-else-if="paramKey === 'point_name'" v-model:value="step.params[paramKey]"
                            :options="getPointOptions(step.params.device_id)" placeholder="选择测点" style="flex:1" />
                          <n-input-number v-else-if="paramKey === 'seconds' || paramKey === 'value'"
                            v-model:value="step.params[paramKey]" :placeholder="paramKey" style="flex:1" />
                          <n-input v-else v-model:value="step.params[paramKey]" :placeholder="paramKey" style="flex:1" />
                        </n-space>
                      </n-gi>
                    </n-grid>

                    <n-space align="center" size="small">
                      <n-text style="font-size:12px">断言:</n-text>
                      <n-button size="tiny" @click="addAssertion(step)">+ 添加检查</n-button>
                    </n-space>
                    <n-space v-for="(asrt, ai) in step.assertions" :key="ai" align="center" size="small"
                      style="padding-left:12px">
                      <n-select v-model:value="asrt.type" :options="simpleAssertionOptions" placeholder="检查类型"
                        style="width:150px" />
                      <n-input-number v-if="needsExpected(asrt.type)" v-model:value="asrt.expected"
                        placeholder="期望值" style="width:120px" />
                      <n-input v-model:value="asrt.message" placeholder="说明（可选）" style="width:200px" />
                      <n-button size="tiny" quaternary type="error" @click="step.assertions.splice(ai, 1)">×</n-button>
                    </n-space>
                  </n-space>
                </n-card>

                <n-empty v-if="!builderCase.steps.length" description="点击上方 添加步骤 开始构建测试" size="small" />
              </n-space>

              <n-divider style="margin:8px 0" />
              <n-space>
                <n-button type="primary" :loading="runningBuilder" @click="runBuilderTest">执行测试</n-button>
                <n-button @click="saveBuilderCase">保存为用例</n-button>
                <n-button @click="exportBuilderJson">导出JSON</n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-tab-pane>

        <n-tab-pane name="json" tab="JSON编辑">
          <n-space vertical>
            <n-space>
              <n-text depth="3">预设模板：</n-text>
              <n-button size="small" v-for="tpl in presetTemplates" :key="tpl.name"
                @click="testJson = tpl.json">{{ tpl.name }}</n-button>
            </n-space>
            <n-input v-model:value="testJson" type="textarea" :rows="12" placeholder='输入测试用例 JSON...' />
            <n-space>
              <n-button type="primary" @click="runJsonTest" :loading="runningJson">执行测试</n-button>
              <n-button @click="formatJson">格式化</n-button>
              <n-button @click="saveJsonAsCase">保存为用例</n-button>
            </n-space>
          </n-space>
        </n-tab-pane>

        <n-tab-pane name="cases" tab="用例管理">
          <n-space justify="space-between" style="margin-bottom:12px">
            <n-h4 style="margin:0">用例列表</n-h4>
            <n-input v-model:value="caseTagFilter" placeholder="按标签筛选" size="small" style="width:150px" clearable />
          </n-space>
          <n-data-table :columns="caseColumns" :data="filteredCases" :bordered="false" size="small"
            :pagination="{ pageSize: 10 }" />
        </n-tab-pane>

        <n-tab-pane name="suites" tab="测试套件">
          <n-space justify="space-between" style="margin-bottom:12px">
            <n-h4 style="margin:0">套件列表</n-h4>
            <n-button type="primary" size="small" @click="showSuiteModal = true">创建套件</n-button>
          </n-space>
          <n-data-table :columns="suiteColumns" :data="suites" :bordered="false" size="small"
            :pagination="{ pageSize: 10 }" />
        </n-tab-pane>

        <n-tab-pane name="history" tab="历史报告">
          <n-data-table :columns="reportColumns" :data="reports" :bordered="false" size="small"
            :pagination="{ pageSize: 10 }" />
        </n-tab-pane>
      </n-tabs>

      <n-modal v-model:show="showSuiteModal" preset="card" title="创建测试套件" style="width: 500px">
        <n-space vertical>
          <n-input v-model:value="suiteForm.name" placeholder="套件名称" />
          <n-input v-model:value="suiteForm.description" placeholder="描述" type="textarea" :rows="2" />
          <n-select v-model:value="suiteForm.test_case_ids" :options="caseOptions" multiple placeholder="选择测试用例" />
          <n-dynamic-tags v-model:value="suiteForm.tags" />
          <n-button type="primary" @click="createSuite" :loading="creatingSuite">创建</n-button>
        </n-space>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()

const suggestions = ref([])
const loadingSuggestions = ref(false)
const quickTesting = ref(false)
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

const builderCase = ref({
  id: 'tc-' + Date.now().toString(36),
  name: '',
  steps: [],
})

const presetTemplates = [
  {
    name: '设备连通性测试',
    json: JSON.stringify([{
      id: "tc-connectivity", name: "设备连通性测试", tags: ["smoke"],
      steps: [
        { name: "创建设备", action: "create_device", params: { id: "test-conn", name: "连通性测试设备", protocol: "http", points: [{ name: "value", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] }, assertions: [{ type: "status_code", expected: 200, message: "创建设备应返回200" }] },
        { name: "读取测点", action: "read_points", params: { device_id: "test-conn" }, assertions: [{ type: "length_greater", expected: 0, message: "测点列表不应为空" }] },
        { name: "写入测点", action: "write_point", params: { device_id: "test-conn", point_name: "value", value: 42.5 }, assertions: [{ type: "status_code", expected: 200, message: "写入应返回200" }] },
        { name: "清理", action: "delete_device", params: { device_id: "test-conn" } }
      ]
    }], null, 2),
  },
  {
    name: '批量设备测试',
    json: JSON.stringify([{
      id: "tc-batch", name: "批量设备创建删除", tags: ["batch"],
      steps: [
        { name: "批量创建", action: "batch_create_devices", params: { devices: [
          { id: "batch-1", name: "批量1", protocol: "http", points: [{ name: "v", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] },
          { id: "batch-2", name: "批量2", protocol: "http", points: [{ name: "v", address: "0", data_type: "float32", generator_type: "random", min_value: 0, max_value: 100 }] },
        ]}, assertions: [{ type: "status_code", expected: 200, message: "批量创建应返回200" }] },
        { name: "查询设备列表", action: "list_devices", assertions: [{ type: "length_greater", expected: 1, message: "设备列表应不为空" }] },
        { name: "批量删除", action: "batch_delete_devices", params: { device_ids: ["batch-1", "batch-2"] } }
      ]
    }], null, 2),
  },
  {
    name: '场景仿真测试',
    json: JSON.stringify([{
      id: "tc-scenario", name: "场景仿真测试", tags: ["scenario"],
      steps: [
        { name: "创建场景", action: "create_scenario", params: { id: "test-scene", name: "测试场景", devices: [], rules: [] }, assertions: [{ type: "status_code", expected: 200, message: "创建场景应返回200" }] },
        { name: "启动场景", action: "start_scenario", params: { scenario_id: "test-scene" } },
        { name: "等待2秒", action: "wait", params: { seconds: 2 } },
        { name: "停止场景", action: "stop_scenario", params: { scenario_id: "test-scene" } },
        { name: "删除场景", action: "delete_scenario", params: { scenario_id: "test-scene" } }
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
    device_id: '设备', scenario_id: '场景', protocol: '协议', template_id: '模板',
    point_name: '测点', seconds: '秒数', value: '值', method: '方法', url: 'URL',
    id: 'ID', name: '名称', device_ids: '设备IDs',
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
    step.assertions.push({ type: 'status_code', expected: 200, message: '操作应成功' })
  }
  if (step.action === 'read_points') {
    step.assertions.push({ type: 'length_greater', expected: 0, message: '测点列表不应为空' })
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
    name: builderCase.value.name || '未命名测试',
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
    message.warning('请先添加测试步骤')
    return
  }
  runningBuilder.value = true
  try {
    const cases = builderCaseToJson()
    const res = await api.runTests(cases)
    lastReport.value = res
    await loadReports()
    message.success('测试执行完成')
  } catch (e) {
    message.error('测试执行失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    runningBuilder.value = false
  }
}

async function saveBuilderCase() {
  try {
    const cases = builderCaseToJson()
    await api.createTestCase(cases[0])
    await loadCases()
    message.success('用例已保存')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

function exportBuilderJson() {
  const json = JSON.stringify(builderCaseToJson(), null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `test_${builderCase.value.id}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function runQuickTest(scope, targetId) {
  quickTesting.value = true
  try {
    const res = await api.quickTest(scope, targetId)
    lastReport.value = res
    await loadReports()
    if (res.success_rate >= 100) {
      message.success(`一键测试完成：全部 ${res.total} 项通过！`)
    } else {
      message.warning(`一键测试完成：${res.passed}/${res.total} 通过，${res.failed} 项失败`)
    }
  } catch (e) {
    message.error('一键测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    quickTesting.value = false
  }
}

async function runJsonTest() {
  runningJson.value = true
  try {
    const cases = JSON.parse(testJson.value)
    const res = await api.runTests(cases)
    lastReport.value = res
    await loadReports()
    message.success('测试执行完成')
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error('JSON 格式错误: ' + e.message)
    } else {
      message.error('测试执行失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    runningJson.value = false
  }
}

function formatJson() {
  try {
    const parsed = JSON.parse(testJson.value)
    testJson.value = JSON.stringify(parsed, null, 2)
    message.success('格式化完成')
  } catch (e) {
    message.error('JSON 格式错误，无法格式化')
  }
}

async function saveJsonAsCase() {
  try {
    const cases = JSON.parse(testJson.value)
    for (const c of cases) {
      await api.createTestCase(c)
    }
    await loadCases()
    message.success('用例已保存')
  } catch (e) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function runCaseById(caseId) {
  try {
    const res = await api.runTestCase(caseId)
    lastReport.value = res
    await loadReports()
    message.success('测试执行完成')
  } catch (e) {
    message.error('执行失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function runSuiteById(suiteId) {
  try {
    const res = await api.runTestSuite(suiteId)
    lastReport.value = res
    await loadReports()
    message.success('测试执行完成')
  } catch (e) {
    message.error('执行失败: ' + (e.response?.data?.detail || e.message))
  }
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
    message.success('用例已加载到编辑器')
  } catch (e) {
    message.error('加载失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteCase(caseId) {
  try {
    await api.deleteTestCase(caseId)
    await loadCases()
    message.success('用例已删除')
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteSuite(suiteId) {
  try {
    await api.deleteTestSuite(suiteId)
    await loadSuites()
    message.success('套件已删除')
  } catch (e) {
    message.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

function viewHtmlReport(id) {
  const token = localStorage.getItem('token')
  window.open(`/api/v1/tests/reports/${id}/html${token ? '?token=' + token : ''}`, '_blank')
}

async function createSuite() {
  creatingSuite.value = true
  try {
    await api.createTestSuite(suiteForm.value)
    showSuiteModal.value = false
    suiteForm.value = { name: '', description: '', test_case_ids: [], tags: [] }
    await loadSuites()
    message.success('套件已创建')
  } catch (e) {
    message.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    creatingSuite.value = false
  }
}

async function loadSuggestions() {
  loadingSuggestions.value = true
  try {
    suggestions.value = await api.getTestSuggestions()
  } catch (e) { message.error('加载测试建议失败') } finally {
    loadingSuggestions.value = false
  }
}

async function loadMetadata() {
  try {
    const [at, ast, dev, sc, proto] = await Promise.all([
      api.getTestActionTypes(),
      api.getTestAssertionTypes(),
      api.getDevices(),
      api.getScenarios(),
      api.getProtocols(),
    ])
    actionTypes.value = at
    assertionTypes.value = ast
    devices.value = dev || []
    scenarios.value = sc || []
    protocols.value = proto || []
  } catch (e) { message.error('加载测试元数据失败') }
}

async function loadReports() {
  try { reports.value = await api.listTestReports() } catch (e) { message.error('加载测试报告失败') }
}

async function loadCases() {
  try { testCases.value = await api.listTestCases() } catch (e) { message.error('加载测试用例失败') }
}

async function loadSuites() {
  try { suites.value = await api.listTestSuites() } catch (e) { message.error('加载测试套件失败') }
}

const caseColumns = [
  { title: '名称', key: 'name', width: 150 },
  { title: '标签', key: 'tags', width: 150, render: (row) => (row.tags || []).map(t => h('span', { style: 'background:#f0f0f0;padding:1px 6px;border-radius:3px;margin-right:2px;font-size:11px' }, t)) },
  { title: '步骤数', key: 'steps', width: 70, render: (row) => (row.steps || []).length },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => [
      h('button', { onClick: () => runCaseById(row.id), style: 'color:#18a058;border:none;background:none;cursor:pointer;font-size:12px;margin-right:8px' }, '执行'),
      h('button', { onClick: () => loadCaseToEditor(row.id), style: 'color:#2080f0;border:none;background:none;cursor:pointer;font-size:12px;margin-right:8px' }, '编辑'),
      h('button', { onClick: () => deleteCase(row.id), style: 'color:#d03050;border:none;background:none;cursor:pointer;font-size:12px' }, '删除'),
    ]
  },
]

const suiteColumns = [
  { title: '名称', key: 'name', width: 150 },
  { title: '用例数', key: 'test_case_ids', width: 80, render: (row) => (row.test_case_ids || []).length },
  {
    title: '操作', key: 'actions', width: 140,
    render: (row) => [
      h('button', { onClick: () => runSuiteById(row.id), style: 'color:#18a058;border:none;background:none;cursor:pointer;font-size:12px;margin-right:8px' }, '执行'),
      h('button', { onClick: () => deleteSuite(row.id), style: 'color:#d03050;border:none;background:none;cursor:pointer;font-size:12px' }, '删除'),
    ]
  },
]

const reportColumns = [
  { title: '名称', key: 'name', width: 150 },
  { title: '总数', key: 'total', width: 60 },
  { title: '通过', key: 'passed', width: 60 },
  { title: '失败', key: 'failed', width: 60 },
  { title: '通过率', key: 'success_rate', width: 80, render: (row) => `${row.success_rate}%` },
  { title: '耗时', key: 'duration', width: 80, render: (row) => `${(row.duration || 0).toFixed(2)}s` },
  {
    title: '操作', key: 'actions', width: 120,
    render: (row) => [
      h('button', { onClick: () => { lastReport.value = row }, style: 'color:#2080f0;border:none;background:none;cursor:pointer;font-size:12px;margin-right:8px' }, '查看'),
      h('button', { onClick: () => viewHtmlReport(row.id), style: 'color:#18a058;border:none;background:none;cursor:pointer;font-size:12px' }, 'HTML'),
    ]
  },
]

onMounted(() => {
  loadSuggestions()
  loadMetadata()
  loadReports()
  loadCases()
  loadSuites()
})
</script>
