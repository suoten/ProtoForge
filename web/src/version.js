// 全局版本号缓存：登录页、左侧菜单、设置页"关于"共用，避免重复请求
// 数据来源：GET /api/v1/health（公开端点，登录前也可访问）
// FIXED: 必须用 api.getHealth()（api.js 默认导出是方法封装对象，
// 直接调 api.get 会报 "X.get is not a function"）
import api from './api.js'

let _version = ''
let _pending = null

export function getAppVersion() {
  return _version
}

export function setAppVersion(v) {
  _version = v || ''
}

export async function fetchAppVersion() {
  if (_version) return _version
  if (!_pending) {
    _pending = Promise.resolve(api.getHealth())
      .then(d => {
        _version = d?.version || ''
        return _version
      })
      .finally(() => { _pending = null })
  }
  return _pending
}
