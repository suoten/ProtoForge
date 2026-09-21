export function validatePassword(password) {
  if (!password || password.length < 8) {
    return { valid: false, reason: 'tooShort' }
  }
  const types = [
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^a-zA-Z0-9]/.test(password),
  ].filter(Boolean).length
  if (types < 3) {
    return { valid: false, reason: 'tooWeak' }
  }
  return { valid: true, reason: null }
}

const MS_THRESHOLD_MICRO = 1e15  // FIXED: 魔术数字→命名常量
const MS_THRESHOLD_MILLI = 1e12  // FIXED: 魔术数字→命名常量

export function formatTime(ts) {
  if (!ts) return '-'
  let ms = ts
  if (typeof ms === 'string') ms = Number(ms)
  if (ms > MS_THRESHOLD_MICRO) ms = ms / 1e6
  else if (ms > MS_THRESHOLD_MILLI && ms < MS_THRESHOLD_MICRO) ms = ms
  else if (ms < MS_THRESHOLD_MILLI) ms = ms * 1000
  const d = new Date(ms)
  if (isNaN(d.getTime())) return String(ts)
  const locale = (typeof localStorage !== 'undefined' && localStorage.getItem('locale')) || 'zh'  // FIXED: 使用locale格式化时间
  const localeMap = { zh: 'zh-CN', en: 'en-US' }
  return d.toLocaleString(localeMap[locale] || 'zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

export function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '-'
  const locale = (typeof localStorage !== 'undefined' && localStorage.getItem('locale')) || 'zh'  // FIXED: 使用locale格式化时长
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  // FIXED: P3 - Q4: 时间格式化中文未走i18n，改为国际化通用格式
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function safeGet(obj, path, defaultValue = undefined) {
  if (!obj || typeof obj !== 'object') return defaultValue
  const keys = path.split('.')
  let current = obj
  for (const key of keys) {
    if (current == null || typeof current !== 'object') return defaultValue
    current = current[key]
  }
  return current ?? defaultValue
}

export function defensiveResult(res, field, fallback = null) {
  if (!res) return fallback
  if (field && res[field] !== undefined) return res[field]
  return res
}

// ---------------------------------------------------------------------------
//  Modbus 点位默认地址分配
//  背景：多字节类型（float32/int32/uint32 占 2 个寄存器，float64 占 4，
//  string 占 32）按起始地址向后占用多个寄存器。"添加测点"若默认地址取
//  points.length，极易与相邻多字节点位重叠，保存时被后端地址重叠校验
//  拦截（400 "检测到同设备点位地址重叠"），用户表现为"更新失败"。
//  这里自动计算下一个不重叠的空闲地址，避免用户手工排查。
// ---------------------------------------------------------------------------

// 与后端 _common.point_reg_count 保持一致
const MODBUS_REG_COUNT = {
  bool: 1, int16: 1, uint16: 1,
  int32: 2, uint32: 2, float32: 2,
  float64: 4, string: 32,
}

export function modbusPointRegCount(dataType) {
  return MODBUS_REG_COUNT[String(dataType || '').toLowerCase()] || 1
}

// 解析 Modbus 点位地址 → { area, addr }；无法解析返回 null。
// 兼容: "3"、"C5"、"COIL5"、"HR10"、"IR8"、"DI3"、"4X100"、"0X10"、
// 6 位 PLC 记法 "400100"；无前缀时按 data_type 判区（bool→coil，其余→holding）
export function parseModbusPointArea(address, dataType) {
  const s = String(address ?? '').trim()
  if (!s) return null
  let area = null
  let num = null
  let m = s.match(/^([0-9]{1,2})[xX](\d+)$/)
  if (m) {
    const p = m[1]
    area = p === '0' ? 'coil' : p === '1' ? 'discrete' : p === '3' ? 'input' : 'holding'
    num = parseInt(m[2], 10)
  } else if (/^[0-9]{6}$/.test(s) && '0134'.includes(s[0])) {
    area = s[0] === '0' ? 'coil' : s[0] === '1' ? 'discrete' : s[0] === '3' ? 'input' : 'holding'
    // 6 位 PLC 记法从 40001 起算（40001 → 地址 0），与后端 parse_modbus_address 一致
    num = parseInt(s.slice(1), 10) - 1
  } else {
    const n = s.match(/^([A-Za-z]*)[-_]?(\d+)$/)
    if (!n) return null
    const prefix = n[1].toUpperCase()
    if (prefix.startsWith('COIL') || prefix.startsWith('C')) area = 'coil'
    else if (prefix.startsWith('DISCRETE') || prefix.startsWith('DI')) area = 'discrete'
    else if (prefix.startsWith('IR')) area = 'input'
    else if (prefix.startsWith('HR')) area = 'holding'
    else area = String(dataType || '').toLowerCase() === 'bool' ? 'coil' : 'holding'
    num = parseInt(n[2], 10)
  }
  if (Number.isNaN(num) || num < 0) return null
  return { area, addr: num }
}

// 计算指定 data_type 的新点位在既有点位中的下一个空闲起始地址（字符串）
export function nextFreeModbusAddress(points, dataType = 'float32') {
  const span = modbusPointRegCount(dataType)
  const area = String(dataType).toLowerCase() === 'bool' ? 'coil' : 'holding'
  const intervals = []
  for (const pt of points || []) {
    if (!pt || !pt.address) continue
    const parsed = parseModbusPointArea(pt.address, pt.data_type)
    if (!parsed) continue
    intervals.push({ area: parsed.area, start: parsed.addr, end: parsed.addr + modbusPointRegCount(pt.data_type) })
  }
  let start = 0
  for (;;) {
    const hit = intervals.find(iv => iv.area === area && start < iv.end && iv.start < start + span)
    if (!hit) return String(start)
    start = hit.end
  }
}

// 生成不与既有点位重名的默认点位名（point_N）
export function nextPointName(points) {
  const names = new Set((points || []).map(p => p && p.name).filter(Boolean))
  let i = (points || []).length + 1
  while (names.has('point_' + i)) i++
  return 'point_' + i
}
