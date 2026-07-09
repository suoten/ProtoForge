import { ref } from 'vue'

/**
 * WebSocket 连接池
 * 全局单例，同一 endpoint 只建一个连接，多组件共享
 */
const connections = new Map()

export function useWebSocketPool() {
  /**
   * 获取或创建 WebSocket 连接
   * @param {string} endpoint - 连接标识（如 'devices' 或 'logs'）
   * @param {Function} createFn - 创建 WebSocket 的工厂函数
   * @returns {{ status, data, subscribe, unsubscribe }}
   */
  function getConnection(endpoint, createFn) {
    if (connections.has(endpoint)) {
      return connections.get(endpoint)
    }

    const status = ref('disconnected')
    const data = ref(null)
    const listeners = new Set()
    let ws = null
    let reconnectTimer = null
    let reconnectDelay = 1000
    let reconnectAttempts = 0
    let manualClose = false
    const MAX_RECONNECT_DELAY = 30000
    const MAX_RECONNECT_ATTEMPTS = 20

    function connect() {
      if (manualClose) return
      try {
        ws = createFn()
        if (!ws) return
      } catch (e) {
        console.error(`WebSocket [${endpoint}] create failed:`, e.message)
        reconnectAttempts++
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          reconnectTimer = setTimeout(connect, 5000)
        }
        return
      }

      ws.onopen = () => {
        status.value = 'connected'
        reconnectDelay = 1000
        reconnectAttempts = 0
        listeners.forEach(cb => cb.onOpen?.())
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          data.value = msg
          listeners.forEach(cb => cb.onMessage?.(msg))
        } catch {
          if (event.data !== 'ping') {
            listeners.forEach(cb => cb.onRawMessage?.(event.data))
          }
        }
      }

      ws.onerror = () => {
        status.value = 'error'
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
        listeners.forEach(cb => cb.onError?.())
      }

      ws.onclose = () => {
        status.value = 'disconnected'
        listeners.forEach(cb => cb.onClose?.())
        if (manualClose) return
        reconnectAttempts++
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          const delay = reconnectDelay
          reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
          reconnectTimer = setTimeout(connect, delay)
        }
      }
    }

    function disconnect() {
      manualClose = true
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
      if (ws) { try { ws.close() } catch {} ws = null }
      status.value = 'disconnected'
    }

    function subscribe(callbacks) {
      listeners.add(callbacks)
      // 如果已连接，立即通知
      if (status.value === 'connected') {
        callbacks.onOpen?.()
      }
      return () => listeners.delete(callbacks)
    }

    function unsubscribe(callbacks) {
      listeners.delete(callbacks)
      // 如果没有监听者了，不关闭连接（保持连接池热）
    }

    const conn = { status, data, connect, disconnect, subscribe, unsubscribe }
    connections.set(endpoint, conn)
    return conn
  }

  /**
   * 完全移除一个连接（组件卸载时调用）
   */
  function removeConnection(endpoint) {
    const conn = connections.get(endpoint)
    if (conn) {
      conn.disconnect()
      connections.delete(endpoint)
    }
  }

  return { getConnection, removeConnection }
}
