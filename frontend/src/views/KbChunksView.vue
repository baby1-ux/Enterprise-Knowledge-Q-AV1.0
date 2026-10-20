<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteChunk, listChunks, setChunkEnabled, updateChunk } from '@/api/kb'

// 分块预览页：分页浏览 + 关键字搜索 + 编辑 / 删除 / 启停
const route = useRoute()
const router = useRouter()

const docId = computed(() => route.params.docId)
const kbId = computed(() => (typeof route.query.kbId === 'string' ? route.query.kbId : ''))
const docName = computed(() =>
  typeof route.query.name === 'string' && route.query.name ? route.query.name : `文档 #${docId.value}`
)

const chunks = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const loading = ref(false)
const togglingId = ref(null)

// 编辑弹窗
const editVisible = ref(false)
const editSubmitting = ref(false)
const editingChunk = ref(null)
const editContent = ref('')

/** 加载分块列表 */
async function loadChunks() {
  loading.value = true
  try {
    const data = await listChunks(docId.value, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim()
    })
    chunks.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total || 0)

    // 当前页被清空时回退到上一页
    if (!chunks.value.length && total.value > 0 && page.value > 1) {
      page.value -= 1
      await loadChunks()
    }
  } catch (error) {
    chunks.value = []
    total.value = 0
    ElMessage.error(error?.message || '分块列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 搜索：回到第一页 */
function handleSearch() {
  page.value = 1
  loadChunks()
}

/** 重置搜索条件 */
function handleReset() {
  keyword.value = ''
  page.value = 1
  loadChunks()
}

/** 翻页 */
function handlePageChange(nextPage) {
  page.value = nextPage
  loadChunks()
}

/** 打开编辑弹窗 */
function openEdit(chunk) {
  editingChunk.value = chunk
  editContent.value = chunk.content || ''
  editVisible.value = true
}

/** 保存分块内容（后端会重新向量化） */
async function handleEditSubmit() {
  const content = editContent.value.trim()
  if (!content) {
    ElMessage.warning('分块内容不能为空')
    return
  }
  editSubmitting.value = true
  try {
    const updated = await updateChunk(editingChunk.value.id, content)
    const target = chunks.value.find((item) => item.id === editingChunk.value.id)
    if (target) target.content = updated?.content ?? content
    editVisible.value = false
    ElMessage.success('分块已更新，向量已重新生成')
  } catch (error) {
    ElMessage.error(error?.message || '保存失败')
  } finally {
    editSubmitting.value = false
  }
}

/** 删除分块 */
async function handleDelete(chunk) {
  try {
    await ElMessageBox.confirm(
      `确定删除第 ${chunk.chunk_index} 个分块吗？删除后不可恢复。`,
      '删除分块',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  try {
    await deleteChunk(chunk.id)
    ElMessage.success('分块已删除')
    await loadChunks()
  } catch (error) {
    ElMessage.error(error?.message || '删除失败')
  }
}

/** 启停分块：enabled=false 不参与检索 */
async function handleToggle(chunk, nextEnabled) {
  togglingId.value = chunk.id
  const previous = !nextEnabled
  try {
    const updated = await setChunkEnabled(chunk.id, nextEnabled)
    chunk.enabled = updated?.enabled ?? nextEnabled
    ElMessage.success(nextEnabled ? '分块已启用' : '分块已停用，将不参与检索')
  } catch (error) {
    chunk.enabled = previous
    ElMessage.error(error?.message || '状态切换失败')
  } finally {
    togglingId.value = null
  }
}

/** 返回文档列表 */
function goBack() {
  if (kbId.value) {
    router.push({ name: 'kb-documents', params: { kbId: kbId.value }, query: { name: docName.value } })
  } else {
    router.push({ name: 'kb' })
  }
}

onMounted(loadChunks)

watch(docId, () => {
  page.value = 1
  keyword.value = ''
  loadChunks()
})
</script>

<template>
  <div class="page-container page-enter">
    <div class="page-head">
      <div>
        <button type="button" class="back-link" @click="goBack">← 返回文档列表</button>
        <h1 class="page-title">{{ docName }}</h1>
        <p class="page-subtitle">
          共 <b class="gradient-text">{{ total }}</b> 个分块 · 每页 {{ pageSize }} 条 · 停用的分块不参与检索
        </p>
      </div>

      <div class="search-bar">
        <el-input
          v-model="keyword"
          placeholder="输入关键字搜索分块内容"
          clearable
          class="search-input"
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" class="btn-gradient" @click="handleSearch">搜索</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
    </div>

    <!-- 加载骨架 -->
    <div v-if="loading" class="chunk-list">
      <div v-for="index in 4" :key="`chunk-sk-${index}`" class="chunk-skeleton skeleton-block"></div>
    </div>

    <!-- 空状态 -->
    <el-empty v-else-if="!chunks.length" :description="keyword ? '没有匹配的分块，换个关键字试试' : '该文档还没有分块'" />

    <!-- 分块列表 -->
    <div v-else class="chunk-list">
      <article
        v-for="chunk in chunks"
        :key="chunk.id"
        class="chunk-card surface-card"
        :class="{ 'is-disabled': chunk.enabled === false }"
      >
        <div class="chunk-head">
          <div class="chunk-badges">
            <span class="chunk-no"># {{ chunk.chunk_index }}</span>
            <span v-if="chunk.page_no !== null && chunk.page_no !== undefined" class="chunk-page">
              第 {{ chunk.page_no }} 页
            </span>
            <span v-if="chunk.created_at" class="chunk-time">{{ chunk.created_at }}</span>
            <span v-if="chunk.enabled === false" class="chunk-off">已停用</span>
          </div>

          <div class="chunk-tools">
            <el-switch
              :model-value="chunk.enabled !== false"
              :loading="togglingId === chunk.id"
              size="small"
              title="启用 / 停用该分块"
              @change="(value) => handleToggle(chunk, value)"
            />
            <el-button link type="primary" @click="openEdit(chunk)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(chunk)">删除</el-button>
          </div>
        </div>

        <p class="chunk-content">{{ chunk.content }}</p>
      </article>
    </div>

    <div v-if="total > pageSize" class="pagination-bar">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, jumper"
        background
        @current-change="handlePageChange"
      />
    </div>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑分块" width="640px" :close-on-click-modal="false">
      <div class="edit-meta">
        <span>分块 #{{ editingChunk?.chunk_index }}</span>
        <span v-if="editingChunk?.page_no">第 {{ editingChunk.page_no }} 页</span>
        <span class="edit-count">{{ editContent.length }} 字</span>
      </div>
      <el-input
        v-model="editContent"
        type="textarea"
        :rows="12"
        resize="none"
        maxlength="8000"
        show-word-limit
        placeholder="请输入分块内容"
      />
      <p class="edit-tip">保存后会自动重新向量化，并同步更新向量库中的对应向量。</p>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" :loading="editSubmitting" @click="handleEditSubmit">保存</el-button>
      </template>
    </el-dialog>
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

.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  width: 280px;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chunk-skeleton {
  height: 118px;
  border-radius: var(--radius-md);
}

.chunk-card {
  padding: 16px 18px;
  transition: box-shadow var(--transition-base), transform var(--transition-base), border-color var(--transition-base);
  animation: fadeSlideIn 0.35s both;
}

.chunk-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.chunk-card.is-disabled {
  opacity: 0.62;
  background: #fbfbfe;
}

.chunk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  margin-bottom: 10px;
  border-bottom: 1px dashed var(--border-color);
}

.chunk-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.chunk-no {
  padding: 2px 9px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.1);
  border-radius: 999px;
}

.chunk-page,
.chunk-time {
  font-size: 11px;
  color: var(--text-muted);
}

.chunk-off {
  padding: 1px 8px;
  font-size: 11px;
  color: var(--el-color-warning);
  background: #fff8eb;
  border: 1px solid #ffe2b8;
  border-radius: 999px;
}

.chunk-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.chunk-content {
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--text-sub);
  white-space: pre-wrap;
  word-break: break-word;
}

.pagination-bar {
  display: flex;
  justify-content: center;
  margin-top: 22px;
}

.edit-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-muted);
}

.edit-count {
  margin-left: auto;
  color: var(--brand-2);
  font-weight: 600;
}

.edit-tip {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .search-bar {
    width: 100%;
  }

  .search-input {
    flex: 1;
    width: auto;
  }

  .chunk-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
