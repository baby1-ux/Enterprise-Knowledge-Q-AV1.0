import { ElMessage } from 'element-plus'

/**
 * 统一请求封装（基于原生 fetch，减少第三方依赖）
 * - 自动注入 Bearer token
 * - 自动解包 { code, message, data } 结构，code !== 0 视为失败并抛出 ApiError
 * - 401 时清除本地登录态、提示并跳转登录页
 */

// 接口前缀（开发环境由 Vite 代理到后端）
const RAW_BASE = import.meta.env.VITE_API_BASE || '/api'
export const API_BASE = RAW_BASE.replace(/\/+$/, '')

// 本地存储键名
const TOKEN_KEY = 'rag_access_token'
const USER_KEY = 'rag_user_info'

/** 业务请求错误：message 为可直接展示给用户的中文提示 */
export class ApiError extends Error {
  constructor(message, code = -1, data = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
  }
}

/* ------------------------------ 登录态存取 ------------------------------ */

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

/** 保存登录信息（登录成功 / 拉取当前用户后调用） */
export function setAuth(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

/** 清除登录信息 */
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

/* ------------------------------ 工具方法 ------------------------------ */

/** 拼接完整接口地址 */
export function buildApiUrl(path) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalized}`
}

/** 拼接查询参数（自动忽略空值；数组展开为多个同名参数，如 kb_ids=1&kb_ids=2） */
function appendQuery(url, params) {
  if (!params) return url
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') search.append(key, String(item))
      })
      return
    }
    search.append(key, String(value))
  })
  const qs = search.toString()
  return qs ? `${url}?${qs}` : url
}

/** 从错误响应中提取可展示的中文提示（兼容 422 字段校验错误） */
function extractMessage(payload, status) {
  if (payload && typeof payload.message === 'string' && payload.message) return payload.message
  const detail = payload?.data?.detail
  if (Array.isArray(detail) && detail.length) {
    const messages = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
        const text = item?.msg || '字段校验失败'
        return field ? `${field}：${text}` : text
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  return `请求失败（HTTP ${status}）`
}

/**
 * 登录失效统一处理：清除登录态 + 中文提示 + 跳转登录页
 * 这里使用动态引入 router，避免与路由守卫形成循环依赖
 */
export async function handleUnauthorized(message) {
  clearAuth()
  ElMessage.error(message || '登录已过期，请重新登录')
  try {
    const { default: router } = await import('../router')
    const current = router.currentRoute.value
    if (current && current.path !== '/login' && current.path !== '/register') {
      const redirect = current.fullPath && current.fullPath !== '/' ? current.fullPath : undefined
      await router.replace({ path: '/login', query: redirect ? { redirect } : {} })
    }
  } catch {
    // 极端情况下（路由尚未就绪）退化为整页跳转
    window.location.href = '/login'
  }
}

/* ------------------------------ 核心请求 ------------------------------ */

/**
 * 发起请求
 * @param {string} path 接口路径，例如 '/kb/'
 * @param {object} options
 * @param {string} [options.method] 请求方法，默认 GET
 * @param {object|FormData} [options.body] 请求体（FormData 时自动使用 multipart）
 * @param {object} [options.params] 查询参数
 * @param {object} [options.headers] 额外请求头
 * @returns {Promise<any>} 解包后的 data
 */
export async function request(path, options = {}) {
  const { method = 'GET', body, params, headers = {} } = options
  const url = appendQuery(buildApiUrl(path), params)

  const finalHeaders = { Accept: 'application/json', ...headers }
  const token = getToken()
  if (token) finalHeaders.Authorization = `Bearer ${token}`

  const init = { method, headers: finalHeaders }

  if (body !== undefined && body !== null) {
    if (body instanceof FormData) {
      // 交给浏览器自动补充 multipart boundary，不能手工设置 Content-Type
      init.body = body
    } else {
      finalHeaders['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
  }

  let response
  try {
    response = await fetch(url, init)
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('网络异常，无法连接服务器，请确认后端服务已启动', -1)
  }

  // 解析响应体（可能是空体或非 JSON）
  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  // 鉴权失败
  if (response.status === 401) {
    const message = extractMessage(payload, 401)
    await handleUnauthorized(message)
    throw new ApiError(message, 401)
  }

  // 统一响应结构
  if (payload && typeof payload.code === 'number') {
    if (payload.code !== 0) {
      throw new ApiError(extractMessage(payload, response.status), payload.code, payload.data)
    }
    return payload.data
  }

  if (!response.ok) {
    throw new ApiError(extractMessage(payload, response.status), response.status)
  }

  return payload
}

/* ------------------------------ 语法糖 ------------------------------ */

export const http = {
  get: (path, params, options = {}) => request(path, { ...options, method: 'GET', params }),
  post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body }),
  put: (path, body, options = {}) => request(path, { ...options, method: 'PUT', body }),
  del: (path, body, options = {}) => request(path, { ...options, method: 'DELETE', body })
}

export default request
