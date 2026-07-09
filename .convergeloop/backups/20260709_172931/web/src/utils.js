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
