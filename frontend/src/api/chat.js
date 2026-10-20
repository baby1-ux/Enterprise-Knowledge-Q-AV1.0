import { http } from './request'

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
