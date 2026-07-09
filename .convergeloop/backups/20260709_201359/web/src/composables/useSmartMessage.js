import { ref } from 'vue'

/**
 * 智能通知系统
 * 支持消息去重、批量汇总、格式统一
 */
const recentMessages = new Map()
const DEDUP_WINDOW_MS = 5000

export function useSmartMessage() {
  const batchMode = ref(false)
  const batchBuffer = ref([])

  function smartNotify(messageApi, type, content, options = {}) {
    const { dedupKey, duration } = options

    // 去重：相同 key 在窗口期内不重复弹出
    if (dedupKey && recentMessages.has(dedupKey)) return
    if (dedupKey) {
      recentMessages.set(dedupKey, true)
      setTimeout(() => recentMessages.delete(dedupKey), DEDUP_WINDOW_MS)
    }

    // 批量模式：缓冲消息
    if (batchMode.value) {
      batchBuffer.value.push({ type, content })
      return
    }

    // 正常模式：直接弹出
    const msgOptions = {}
    if (duration) msgOptions.duration = duration
    messageApi[type]?.(content, msgOptions)
  }

  function startBatch() {
    batchMode.value = true
    batchBuffer.value = []
  }

  function endBatch(messageApi, options = {}) {
    batchMode.value = false
    const buffer = batchBuffer.value
    batchBuffer.value = []

    if (buffer.length === 0) return

    // 汇总消息
    const successCount = buffer.filter(m => m.type === 'success').length
    const errorCount = buffer.filter(m => m.type === 'error').length
    const warningCount = buffer.filter(m => m.type === 'warning').length

    if (buffer.length === 1) {
      const m = buffer[0]
      messageApi[m.type]?.(m.content, options)
      return
    }

    // 多条消息汇总
    const parts = []
    if (successCount > 0) parts.push(`${successCount} ${options.successLabel || 'succeeded'}`)
    if (warningCount > 0) parts.push(`${warningCount} ${options.warningLabel || 'warnings'}`)
    if (errorCount > 0) parts.push(`${errorCount} ${options.errorLabel || 'failed'}`)

    const summary = parts.join(', ')
    const type = errorCount > 0 ? 'error' : warningCount > 0 ? 'warning' : 'success'
    messageApi[type]?.(summary, options)
  }

  return { smartNotify, startBatch, endBatch }
}
