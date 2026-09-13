<template>
  <div>
    <n-h2 style="margin-bottom: 4px">{{ t('testPlans.title') }}</n-h2>
    <n-text depth="3" style="font-size: 13px">{{ t('testPlans.subtitle') }}</n-text>

    <n-space style="margin: 16px 0" justify="space-between" align="center">
      <n-space>
        <n-select v-model:value="statusFilter" :options="statusOptions" style="width: 160px" clearable
          :placeholder="t('testPlans.filterByStatus')" @update:value="loadPlans" />
      </n-space>
      <n-button type="primary" @click="openCreate">{{ t('testPlans.create') }}</n-button>
    </n-space>

    <n-spin :show="loading">
      <n-empty v-if="!loading && plans.length === 0" :description="t('testPlans.noPlans')" style="padding: 40px">
        <template #extra>
          <n-button type="primary" @click="openCreate">{{ t('testPlans.create') }}</n-button>
        </template>
      </n-empty>

      <n-grid v-else :cols="3" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item v-for="plan in plans" :key="plan.id">
          <n-card hoverable :title="plan.name" size="small">
            <template #header-extra>
              <n-tag :type="planStatusType(plan.status)" size="small">{{ planStatusText(plan.status) }}</n-tag>
            </template>
            <n-space vertical size="small">
              <n-text depth="3" style="font-size: 13px">{{ plan.description || t('testPlans.noDescription') }}</n-text>
              <n-space size="small">
                <n-tag size="tiny" round>v{{ plan.version }}</n-tag>
                <n-tag size="tiny" round type="info">{{ plan.test_suite_ids?.length || 0 }} {{ t('testPlans.suites') }}</n-tag>
              </n-space>
              <n-text depth="3" style="font-size: 12px">{{ t('testPlans.updated') }}: {{ formatTime(plan.updated_at) }}</n-text>
            </n-space>
            <template #action>
              <n-space size="small">
                <n-button size="small" type="primary" :loading="runningPlan === plan.id" @click="runPlan(plan)">
                  {{ t('testPlans.run') }}
                </n-button>
                <n-button size="small" @click="viewRuns(plan)">{{ t('testPlans.history') }}</n-button>
                <n-button size="small" @click="editPlan(plan)">{{ t('common.edit') }}</n-button>
                <n-button size="small" @click="clonePlan(plan)">{{ t('testPlans.clone') }}</n-button>
                <n-popconfirm @positive-click="deletePlan(plan)">
                  <template #trigger>
                    <n-button size="small" type="error" tertiary>{{ t('common.delete') }}</n-button>
                  </template>
                  {{ t('testPlans.confirmDelete', { name: plan.name }) }}
                </n-popconfirm>
              </n-space>
            </template>
          </n-card>
        </n-grid-item>
      </n-grid>
    </n-spin>

    <!-- Create/Edit Modal -->
    <n-modal v-model:show="showModal" :title="editingPlan ? t('testPlans.editTitle') : t('testPlans.createTitle')"
      preset="card" style="width: min(700px, 95vw)" :mask-closable="false">
      <n-form ref="formRef" :model="formData" label-placement="top">
        <n-form-item :label="t('testPlans.planName')" path="name">
          <n-input v-model:value="formData.name" :placeholder="t('testPlans.planNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('testPlans.planVersion')" path="version">
          <n-input v-model:value="formData.version" placeholder="1.0.0" style="width: 150px" />
        </n-form-item>
        <n-form-item :label="t('testPlans.planDescription')" path="description">
          <n-input v-model:value="formData.description" type="textarea" :rows="2"
            :placeholder="t('testPlans.planDescPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('testPlans.selectSuites')" path="test_suite_ids">
          <n-select v-model:value="formData.test_suite_ids" multiple filterable
            :options="suiteOptions" :placeholder="t('testPlans.selectSuitesPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('testPlans.planStatus')" path="status">
          <n-select v-model:value="formData.status" :options="statusEditOptions" style="width: 180px" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="savePlan">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Runs History Modal -->
    <n-modal v-model:show="showRunsModal" :title="t('testPlans.runHistory') + ' - ' + (selectedPlan?.name || '')"
      preset="card" style="width: min(900px, 95vw)">
      <n-spin :show="runsLoading">
        <n-empty v-if="!runsLoading && runs.length === 0" :description="t('testPlans.noRuns')" style="padding: 20px" />
        <n-data-table v-else :columns="runColumns" :data="runs" :bordered="false" size="small" />
      </n-spin>
    </n-modal>

    <!-- Run Result Modal -->
    <n-modal v-model:show="showRunResult" :title="t('testPlans.runResult')" preset="card" style="width: min(800px, 95vw)">
      <div v-if="runResult">
        <n-result :status="runResult.status === 'passed' ? 'success' : runResult.status === 'failed' ? 'error' : 'warning'"
          :title="runResult.plan_name" :description="t('testPlans.runStatus.' + runResult.status)">
          <template #footer>
            <n-space justify="center">
              <n-stat label="Total" :value="runResult.results_summary?.total || 0" />
              <n-stat label="Passed" :value="runResult.results_summary?.passed || 0" />
              <n-stat label="Failed" :value="runResult.results_summary?.failed || 0" />
              <n-stat label="Errors" :value="runResult.results_summary?.errors || 0" />
              <n-stat label="Duration" :value="(runResult.results_summary?.duration_seconds || 0) + 's'" />
            </n-space>
          </template>
        </n-result>
        <n-divider />
        <n-space justify="center">
          <n-button @click="downloadReport(runResult.id, 'junit')">JUnit XML</n-button>
          <n-button @click="downloadReport(runResult.id, 'html')">HTML Report</n-button>
          <n-button @click="downloadReport(runResult.id, 'json')">JSON Report</n-button>
        </n-space>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NButton, NSpace, NTag, NPopconfirm, useMessage, useDialog } from 'naive-ui'
import api from '../api.js'
import { useI18n } from '../i18n.js'

const message = useMessage()
const { t } = useI18n()
const dialog = useDialog()

const loading = ref(false)
const saving = ref(false)
const runningPlan = ref(null)
const plans = ref([])
const suites = ref([])
const statusFilter = ref(null)
const showModal = ref(false)
const showRunsModal = ref(false)
const showRunResult = ref(false)
const editingPlan = ref(null)
const selectedPlan = ref(null)
const runs = ref([])
const runsLoading = ref(false)
const runResult = ref(null)
const formData = ref({
  name: '', version: '1.0.0', description: '', test_suite_ids: [], status: 'draft'
})

const statusOptions = [
  { label: t('testPlans.statusDraft'), value: 'draft' },
  { label: t('testPlans.statusActive'), value: 'active' },
  { label: t('testPlans.statusArchived'), value: 'archived' },
]
const statusEditOptions = statusOptions

const suiteOptions = computed(() =>
  suites.value.map(s => ({ label: s.name, value: s.id }))
)

const runColumns = computed(() => [
  { title: 'Run ID', key: 'id', width: 120, ellipsis: { tooltip: true } },
  { title: t('testPlans.runStatusCol'), key: 'status', width: 100,
    render: (row) => h(NTag, { size: 'small', type: runStatusType(row.status), bordered: false }, () => runStatusText(row.status)) },
  { title: t('testPlans.total'), key: 'results_summary.total', width: 60,
    render: (row) => row.results_summary?.total || 0 },
  { title: t('testPlans.passed'), key: 'results_summary.passed', width: 60,
    render: (row) => row.results_summary?.passed || 0 },
  { title: t('testPlans.failed'), key: 'results_summary.failed', width: 60,
    render: (row) => row.results_summary?.failed || 0 },
  { title: t('testPlans.duration'), key: 'results_summary.duration_seconds', width: 80,
    render: (row) => (row.results_summary?.duration_seconds || 0) + 's' },
  { title: t('common.action'), key: 'actions', width: 120,
    render: (row) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => viewRunDetail(row.id) }, () => t('testPlans.detail')),
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => downloadReport(row.id, 'junit') }, () => 'JUnit'),
    ]) },
])

function planStatusType(status) {
  return { draft: 'default', active: 'success', archived: 'warning' }[status] || 'default'
}
function planStatusText(status) {
  return t('testPlans.status' + status.charAt(0).toUpperCase() + status.slice(1))
}
function runStatusType(status) {
  return { passed: 'success', failed: 'error', error: 'warning', running: 'info', aborted: 'default' }[status] || 'default'
}
function runStatusText(status) {
  return t('testPlans.runStatus.' + status) || status
}
function formatTime(ts) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

async function loadPlans() {
  loading.value = true
  try {
    plans.value = await api.listTestPlans({ status: statusFilter.value || undefined })
  } catch (e) {
    message.error(t('testPlans.loadFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function loadSuites() {
  try {
    suites.value = await api.listTestSuites()
  } catch (e) {
    // Silent fail - suites are optional
  }
}

function openCreate() {
  editingPlan.value = null
  formData.value = { name: '', version: '1.0.0', description: '', test_suite_ids: [], status: 'draft' }
  showModal.value = true
}

function editPlan(plan) {
  editingPlan.value = plan
  formData.value = { ...plan }
  showModal.value = true
}

async function savePlan() {
  if (!formData.value.name) {
    message.warning(t('testPlans.nameRequired'))
    return
  }
  saving.value = true
  try {
    if (editingPlan.value) {
      await api.updateTestPlan(editingPlan.value.id, formData.value)
      message.success(t('testPlans.updateSuccess'))
    } else {
      await api.createTestPlan(formData.value)
      message.success(t('testPlans.createSuccess'))
    }
    showModal.value = false
    await loadPlans()
  } catch (e) {
    message.error(t('common.saveFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function deletePlan(plan) {
  try {
    await api.deleteTestPlan(plan.id)
    message.success(t('testPlans.deleteSuccess'))
    await loadPlans()
  } catch (e) {
    message.error(t('common.deleteFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function clonePlan(plan) {
  try {
    await api.cloneTestPlan(plan.id, { name: plan.name + ' (Copy)' })
    message.success(t('testPlans.cloneSuccess'))
    await loadPlans()
  } catch (e) {
    message.error(t('testPlans.cloneFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function runPlan(plan) {
  runningPlan.value = plan.id
  try {
    const result = await api.runTestPlan(plan.id, { trigger_source: 'manual' })
    runResult.value = result
    showRunResult.value = true
    message.info(t('testPlans.runCompleted'))
  } catch (e) {
    message.error(t('testPlans.runFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    runningPlan.value = null
  }
}

async function viewRuns(plan) {
  selectedPlan.value = plan
  showRunsModal.value = true
  runsLoading.value = true
  try {
    runs.value = await api.listPlanRuns(plan.id, 20)
  } catch (e) {
    message.error(t('testPlans.loadRunsFailed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    runsLoading.value = false
  }
}

async function viewRunDetail(runId) {
  try {
    runResult.value = await api.getTestRun(runId)
    showRunResult.value = true
  } catch (e) {
    message.error(t('testPlans.loadRunFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

async function downloadReport(runId, format) {
  try {
    const report = await api.getTestRunReport(runId, format)
    let content, filename, mime
    if (format === 'junit') {
      content = report
      filename = `test-results-${runId}.xml`
      mime = 'application/xml'
    } else if (format === 'html') {
      content = report
      filename = `test-report-${runId}.html`
      mime = 'text/html'
    } else {
      content = JSON.stringify(report, null, 2)
      filename = `test-report-${runId}.json`
      mime = 'application/json'
    }
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(t('testPlans.downloadFailed') + ': ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(async () => {
  await Promise.all([loadPlans(), loadSuites()])
})
</script>
