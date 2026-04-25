<template>
  <n-space vertical>
    <div class="pf-section-title">联调集成</div>
    <div class="pf-section-desc">导入外部配置，对接第三方系统</div>

    <n-tabs type="card">
      <n-tab-pane name="edgelite" tab="EdgeLite 导入">
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

      <n-tab-pane name="sdk" tab="Python SDK">
        <n-card size="small" title="ProtoForge Python SDK">
          <n-code language="python" :code="sdkExample" />
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <div class="pf-section-title" style="font-size:16px;margin-top:16px">导入结果</div>
    <n-data-table :columns="resultColumns" :data="importResults" :bordered="false" size="small"
      :pagination="{ pageSize: 10 }" />
  </n-space>
</template>

<script setup>
import { ref } from 'vue'
import { NSpace, NH4, NTabs, NTabPane, NCard, NInput, NButton, NAlert, NDataTable, NCode, useMessage } from 'naive-ui'
import api from '../api.js'

const message = useMessage()
const edgeLiteJson = ref('')
const pygbsentryJson = ref('')
const importing = ref(false)
const importResults = ref([])

const resultColumns = [
  { title: '设备ID', key: 'id', width: 180 },
  { title: '名称', key: 'name', width: 180 },
  { title: '协议', key: 'protocol', width: 100 },
  { title: '状态', key: 'status', width: 80 },
]

const sdkExample = `# ProtoForge Python SDK
from protoforge.sdk import ProtoForgeClient

with ProtoForgeClient("http://localhost:8000") as c:
    c.start_protocol("modbus_tcp")
    c.quick_create("modbus_temperature_sensor", "sensor-001")
    points = c.read_points("sensor-001")
    print(points)
    c.create_scenario("factory-001", "factory")
    c.start_scenario("factory-001")
    c.stop_scenario("factory-001")
    c.stop_protocol("modbus_tcp")`

async function importEdgeLite() {
  importing.value = true
  try {
    const config = JSON.parse(edgeLiteJson.value)
    const res = await api._post('/integration/edgelite', config)
    importResults.value = res.devices || []
    message.success(`成功导入 ${res.imported || 0} 个设备`)
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error('JSON 格式错误: ' + e.message)
    } else {
      message.error('导入失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    importing.value = false
  }
}

async function importPyGBSentry() {
  importing.value = true
  try {
    const config = JSON.parse(pygbsentryJson.value)
    const res = await api._post('/integration/pygbsentry', config)
    importResults.value = res.devices || []
    message.success(`成功导入 ${res.imported || 0} 个设备`)
  } catch (e) {
    if (e instanceof SyntaxError) {
      message.error('JSON 格式错误: ' + e.message)
    } else {
      message.error('导入失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    importing.value = false
  }
}
</script>
