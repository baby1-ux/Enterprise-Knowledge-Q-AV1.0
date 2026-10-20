import { http } from './request'

/**
 * 系统相关接口
 */

/**
 * 用量统计（按当前登录用户隔离）
 * @returns {Promise<{
 *   knowledge_base_count: number, document_count: number, chunk_count: number,
 *   session_count: number, message_count: number, answer_count: number,
 *   today_answer_count: number
 * }>}
 */
export function fetchStats() {
  return http.get('/system/stats')
}
