<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import UploadDialog from '@/components/UploadDialog.vue'
import { deleteDocument, getDocumentStatus, listDocuments, reparseDocument } from '@/api/kb'

// 某知识库下的文档列表：上传解析 + 解析进度轮询
const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.kbId)
const kbName = computed(() => (typeof route.query.name === 'string' && route.query.name ? route.query.name : '知识库'))

const docs = ref([])
const loading = ref(false)
const uploadVisible = ref(false)

// 状态轮询定时器（组件卸载时清除）
let pollTimer = null
const POLL_INTERVAL = 1500

const STATUS_META = {
  pending: { text: '排队中', type: 'info' },
  parsing: { text: '解析中', type: 'warning' },
  success: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' }
}

const RETRIEVAL_LABEL = { dense: '稠密检索', hybrid: '混合检索' }

const pendingCount = computed(
  () => docs.value.filter((item) => item.status === 'pending' || item.status === 'parsing').length
)

function statusMeta(status) {
  return STATUS_META[status] || { text: status || '未知', type: 'info' }
}

/** 加载文档列表 */
async function loadDocuments(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await listDocuments(kbId.value)
    docs.value = Array.isArray(data) ? data : []
  } catch (error) {
    if (!silent) ElMessage.error(error?.message || '文档列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 启动轮询 */
function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(pollOnce, POLL_INTERVAL)
}

/** 停止轮询 */
function stopPolling() {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = null
}

/** 轮询一次解析进度 */
async function pollOnce() {
  const pendingDocs = docs.value.filter((item) => item.status === 'pending' || item.status === 'parsing')
  if (!pendingDocs.length) {
    stopPolling()
    return
  }

  let settled = false
  await Promise.all(
    pendingDocs.map(async (docItem) => {
      try {
        const status = await getDocumentStatus(docItem.id)
        const target = docs.value.find((item) => item.id === docItem.id)
        if (target) {
          target.status = status?.status || target.status
          if (status?.chunk_count !== undefined && status.chunk_count !== null) target.chunk_count = status.chunk_count
          target.error_message = status?.error_message ?? null
        }
        if (status?.status === 'success' || status?.status === 'failed') settled = true
      } catch {
        // 单次轮询失败不打断整体流程
      }
    })
  )

  // 有文档解析落地后刷新整表，补齐分块数等信息
  if (settled) await loadDocuments(true)

  if (!docs.value.some((item) => item.status === 'pending' || item.status === 'parsing')) stopPolling()
}

/** 上传成功后：刷新列表并开始轮询 */
async function handleUploadSuccess() {
  await loadDocuments(true)
  if (pendingCount.value) startPolling()
}

/** 重新解析 */
async function handleReparse(docItem) {
  try {
    await ElMessageBox.confirm(
      `将清空「${docItem.filename}」的旧分块与向量并重新解析，确定继续吗？`,
      '重新解析',
      { confirmButtonText: '重新解析', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  try {
    const updated = await reparseDocument(docItem.id)
    const target = docs.value.find((item) => item.id === docItem.id)
    if (target) {
      target.status = updated?.status || 'pending'
      target.chunk_count = updated?.chunk_count ?? 0
      target.error_message = updated?.error_message ?? null
    }
    ElMessage.success('已提交重新解析任务')
    startPolling()
  } catch (error) {
    ElMessage.error(error?.message || '重新解析失败')
  }
}

/** 删除文档 */
async function handleDelete(docItem) {
  try {
    await ElMessageBox.confirm(`确定删除文档「${docItem.filename}」及其全部分块吗？`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  try {
    await deleteDocument(docItem.id)
    ElMessage.success('文档已删除')
    await loadDocuments(true)
  } catch (error) {
    ElMessage.error(error?.message || '删除失败')
  }
}

/** 预览分块 */
function goChunks(docItem) {
  router.push({
    name: 'kb-chunks',
    params: { docId: docItem.id },
    query: { kbId: kbId.value, name: docItem.filename }
  })
}

/** 返回知识库列表 */
function goBack() {
  router.push({ name: 'kb' })
}

/** 文件大小格式化 */
function formatSize(size) {
  const value = Number(size)
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

/** 切块参数展示 */
function formatChunkParams(row) {
  const size = row.chunk_size ?? '-'
  const overlap = row.chunk_overlap ?? '-'
  return `${size} / ${overlap}`
}

onMounted(async () => {
  await loadDocuments()
  if (pendingCount.value) startPolling()
})

// 切换知识库时重新加载
watch(kbId, async () => {
  stopPolling()
  await loadDocuments()
  if (pendingCount.value) startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="page-container page-enter">
    <div class="page-head">
      <div>
        <button type="button" class="back-link" @click="goBack">← 返回知识库</button>
        <h1 class="page-title">{{ kbName }}</h1>
        <p class="page-subtitle">
          共 {{ docs.length }} 个文档<span v-if="pendingCount"> · {{ pendingCount }} 个正在解析</span>
        </p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="loadDocuments()">刷新</el-button>
        <el-button type="primary" class="btn-gradient" @click="uploadVisible = true">↑ 上传文档</el-button>
      </div>
    </div>

    <div class="table-card surface-card">
      <el-table v-loading="loading" :data="docs" style="width: 100%" empty-text="还没有文档，点击右上角「上传文档」开始">
        <el-table-column prop="filename" label="文档名称" min-width="220">
          <template #default="{ row }">
            <div class="doc-name">
              <span class="doc-ext">{{ (row.file_type || '').toUpperCase() || 'DOC' }}</span>
              <span class="doc-title ellipsis" :title="row.filename">{{ row.filename }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="file_type" label="类型" width="88">
          <template #default="{ row }">
            <span class="muted-text">{{ (row.file_type || '—').toUpperCase() }}</span>
          </template>
        </el-table-column>

        <el-table-column label="大小" width="100">
          <template #default="{ row }">
            <span class="muted-text">{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip
              :disabled="row.status !== 'failed' || !row.error_message"
              :content="row.error_message || ''"
              placement="top"
            >
              <el-tag :type="statusMeta(row.status).type" effect="light" round size="small">
                {{ statusMeta(row.status).text }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="分块数" width="92">
          <template #default="{ row }">
            <b class="chunk-count">{{ row.chunk_count ?? 0 }}</b>
          </template>
        </el-table-column>

        <el-table-column label="切块参数" width="168">
          <template #default="{ row }">
            <div class="chunk-params">
              <span>{{ formatChunkParams(row) }}</span>
              <span class="chunk-mode">{{ RETRIEVAL_LABEL[row.retrieval_mode] || row.retrieval_mode || '—' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="上传时间" width="168">
          <template #default="{ row }">
            <span class="muted-text">{{ row.created_at || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="goChunks(row)">预览分块</el-button>
              <el-button link type="warning" @click="handleReparse(row)">重新解析</el-button>
              <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <UploadDialog
      v-model="uploadVisible"
      :kb-id="kbId"
      :kb-name="kbName"
      @success="handleUploadSuccess"
    />
  </div>
</template>

<style scoped>
.back-link {
  padding: 0;
  margin-bottom: 8px;
  font-size: 12.5px;
  color: var(--text-muted);
  background: transparent;
  border: 0;
  cursor: pointer;
  transition: color var(--transition-fast);
}

.back-link:hover {
  color: var(--brand-1);
}

.head-actions {
  display: flex;
  gap: 10px;
}

.table-card {
  padding: 8px 8px 4px;
  overflow: hidden;
}

.doc-name {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.doc-ext {
  flex-shrink: 0;
  padding: 2px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--brand-2);
  background: rgba(99, 102, 241, 0.1);
  border-radius: 6px;
}

.doc-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-main);
}

.muted-text {
  font-size: 12.5px;
  color: var(--text-muted);
}

.chunk-count {
  font-size: 14px;
  font-weight: 700;
  color: var(--brand-1);
}

.chunk-params {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.chunk-mode {
  font-size: 11px;
  color: var(--text-muted);
}

.row-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .head-actions {
    width: 100%;
  }
}
</style>
