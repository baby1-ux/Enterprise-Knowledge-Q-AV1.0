import { http } from './request'

/**
 * 知识库 / 文档 / 分块 相关接口
 * 对应 docs/API.md 第 3、4、5 节
 */

/* ------------------------------ 知识库 ------------------------------ */

/**
 * 知识库列表
 * @param {string} [keyword] 按名称模糊搜索（可选）
 */
export function listKnowledgeBases(keyword = '') {
  return http.get('/kb/', { keyword })
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

/**
 * 批量上传并解析文档（单次最多 20 个，单个失败不影响其它文件）
 * @param {number|string} kbId 知识库 id
 * @param {{ files: File[], chunk_size: number, chunk_overlap: number, retrieval_mode: string }} params
 * @returns {Promise<{ uploaded: Array, failed: Array<{ filename: string, message: string }> }>}
 */
export function uploadDocumentsBatch(kbId, { files, chunk_size, chunk_overlap, retrieval_mode }) {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  formData.append('chunk_size', String(chunk_size))
  formData.append('chunk_overlap', String(chunk_overlap))
  formData.append('retrieval_mode', retrieval_mode)
  return http.post(`/kb/${kbId}/documents/batch`, formData)
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

/* ------------------------------ 全局搜索 ------------------------------ */

/**
 * 跨知识库搜索分块（按内容关键字）
 * @param {{ keyword: string, kb_ids?: number[], page?: number, page_size?: number }} query
 * @returns {Promise<{ total: number, page: number, page_size: number, items: Array }>}
 */
export function searchChunks(query = {}) {
  return http.get('/kb/chunks/search', {
    keyword: query.keyword ?? '',
    kb_ids: query.kb_ids ?? [],
    page: query.page ?? 1,
    page_size: query.page_size ?? 10
  })
}
