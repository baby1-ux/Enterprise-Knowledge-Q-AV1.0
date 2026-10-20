import { http } from './request'

/**
 * 知识库 / 文档 / 分块 相关接口
 * 对应 docs/API.md 第 3、4、5 节
 */

/* ------------------------------ 知识库 ------------------------------ */

/** 知识库列表 */
export function listKnowledgeBases() {
  return http.get('/kb/')
}

/** 创建知识库 { name, description } */
export function createKnowledgeBase(payload) {
  return http.post('/kb/', payload)
}

/** 修改知识库 { name, description } */
export function updateKnowledgeBase(kbId, payload) {
  return http.put(`/kb/${kbId}`, payload)
}

/** 删除知识库（同时删除文档、分块与向量） */
export function deleteKnowledgeBase(kbId) {
  return http.del(`/kb/${kbId}`)
}

/* ------------------------------ 文档 ------------------------------ */

/** 某知识库下的文档列表 */
export function listDocuments(kbId) {
  return http.get(`/kb/${kbId}/documents`)
}

/**
 * 上传并解析文档（multipart/form-data）
 * @param {number|string} kbId 知识库 id
 * @param {{ file: File, chunk_size: number, chunk_overlap: number, retrieval_mode: string }} params
 */
export function uploadDocument(kbId, { file, chunk_size, chunk_overlap, retrieval_mode }) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('chunk_size', String(chunk_size))
  formData.append('chunk_overlap', String(chunk_overlap))
  formData.append('retrieval_mode', retrieval_mode)
  return http.post(`/kb/${kbId}/documents`, formData)
}

/** 文档解析进度 { id, status, chunk_count, error_message } */
export function getDocumentStatus(docId) {
  return http.get(`/kb/documents/${docId}/status`)
}

/** 重新解析（沿用原切块参数） */
export function reparseDocument(docId) {
  return http.post(`/kb/documents/${docId}/reparse`)
}

/** 删除文档 */
export function deleteDocument(docId) {
  return http.del(`/kb/documents/${docId}`)
}

/* ------------------------------ 分块 ------------------------------ */

/**
 * 分块分页列表
 * @param {number|string} docId 文档 id
 * @param {{ page?: number, page_size?: number, keyword?: string }} query
 * @returns {Promise<{ total: number, page: number, page_size: number, items: Array }>}
 */
export function listChunks(docId, query = {}) {
  return http.get(`/kb/documents/${docId}/chunks`, {
    page: query.page ?? 1,
    page_size: query.page_size ?? 10,
    keyword: query.keyword ?? ''
  })
}

/** 编辑分块内容（后端会重新向量化） */
export function updateChunk(chunkId, content) {
  return http.put(`/kb/chunks/${chunkId}`, { content })
}

/** 启停分块（enabled=false 不参与检索） */
export function setChunkEnabled(chunkId, enabled) {
  return http.put(`/kb/chunks/${chunkId}/enabled`, { enabled })
}

/** 删除分块 */
export function deleteChunk(chunkId) {
  return http.del(`/kb/chunks/${chunkId}`)
}
