import { ApiError, buildApiUrl, getToken, http } from './request'

/**
 * 对话相关接口（对应 docs/API.md 第 6 节）
 * 流式问答见 api/stream.js
 */

/** 可选模型与默认参数：data = { models, defaults } */
export function fetchChatModels() {
  return http.get('/chat/models')
}

/** 会话列表 */
export function listSessions() {
  return http.get('/chat/sessions')
}

/**
 * 新建会话（字段均可选，name 省略时后端使用「新对话」）
 * @param {{ name?: string, kb_ids?: number[], model?: string, temperature?: number,
 *           top_p?: number, max_tokens?: number, history_rounds?: number, retrieval_mode?: string }} payload
 */
export function createSession(payload = {}) {
  return http.post('/chat/sessions', payload)
}

/**
 * 更新会话（局部更新，只传需要修改的字段）
 * @param {number|string} sessionId
 * @param {object} payload 同新建会话
 */
export function updateSession(sessionId, payload = {}) {
  return http.put(`/chat/sessions/${sessionId}`, payload)
}

/** 删除会话 */
export function deleteSession(sessionId) {
  return http.del(`/chat/sessions/${sessionId}`)
}

/** 会话历史消息 */
export function listSessionMessages(sessionId) {
  return http.get(`/chat/sessions/${sessionId}/messages`)
}

/**
 * 消息反馈（对助手回答点赞 / 点踩）
 * @param {number|string} messageId 助手消息 id
 * @param {'like'|'dislike'|null} feedback 传 null 取消反馈
 */
export function feedbackMessage(messageId, feedback) {
  return http.put(`/chat/messages/${messageId}/feedback`, { feedback })
}

/**
 * 导出会话为 Markdown 文件（浏览器直接触发下载）
 * @param {number|string} sessionId 会话 id
 * @param {string} filename 下载文件名（不含 .md 后缀）
 */
export async function exportSession(sessionId, filename = '对话记录') {
  let response
  try {
    response = await fetch(buildApiUrl(`/chat/sessions/${sessionId}/export`), {
      headers: { Authorization: `Bearer ${getToken()}` }
    })
  } catch {
    throw new ApiError('网络异常，无法连接服务器，请确认后端服务已启动', -1)
  }
  if (!response.ok) {
    let message = `导出失败（HTTP ${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.message) message = payload.message
    } catch {
      // 非 JSON 响应时使用默认提示
    }
    throw new ApiError(message, response.status)
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename || '对话记录'}.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
