<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import StatsCards from '@/components/StatsCards.vue'
import KbPermissionDialog from '@/components/KbPermissionDialog.vue'
import { createKnowledgeBase, deleteKnowledgeBase, listKnowledgeBases, searchChunks, updateKnowledgeBase } from '@/api/kb'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const kbs = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const form = reactive({ name: '', description: '', visibility: 'private' })

const rules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { max: 50, message: '名称不超过 50 个字符', trigger: 'blur' }
  ],
  description: [{ max: 200, message: '描述不超过 200 个字符', trigger: 'blur' }]
}

const visibilityOptions = [
  { value: 'private', label: '私有：仅所有者可访问' },
  { value: 'role', label: '角色共享：被授权角色可读' },
  { value: 'all', label: '全员只读：登录即可检索' }
]

/* ------------------------------ 名称搜索（防抖） ------------------------------ */
const keyword = ref('')
let searchTimer = null

function handleSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadKnowledgeBases(keyword.value.trim())
  }, 300)
}

function handleSearchClear() {
  keyword.value = ''
  loadKnowledgeBases('')
}

/* ------------------------------ 跨库分块搜索 ------------------------------ */
const chunkSearchVisible = ref(false)
const chunkSearching = ref(false)
const chunkKeyword = ref('')
const chunkResult = ref({ total: 0, page: 1, page_size: 10, items: [] })
const chunkSearched = ref(false)

async function doSearchChunks(page = 1) {
  const text = chunkKeyword.value.trim()
  if (!text) {
    ElMessage.warning('请输入分块内容关键字')
    return
  }
  chunkSearching.value = true
  try {
    const data = await searchChunks({ keyword: text, page, page_size: chunkResult.value.page_size })
    chunkResult.value = {
      total: Number(data?.total) || 0,
      page: Number(data?.page) || page,
      page_size: Number(data?.page_size) || 10,
      items: Array.isArray(data?.items) ? data.items : []
    }
    chunkSearched.value = true
  } catch (error) {
    ElMessage.error(error?.message || '搜索失败，请稍后重试')
  } finally {
    chunkSearching.value = false
  }
}

function openChunkSearch() {
  chunkKeyword.value = ''
  chunkResult.value = { total: 0, page: 1, page_size: 10, items: [] }
  chunkSearched.value = false
  chunkSearchVisible.value = true
}

function goChunkDocument(item) {
  if (!item?.document_id) return
  const page = Math.floor((Number(item.chunk_index) || 0) / 10) + 1
  chunkSearchVisible.value = false
  router.push({
    name: 'kb-chunks',
    params: { docId: item.document_id },
    query: { name: item.doc_name || '文档分块', page }
  })
}

function previewText(text, limit = 80) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

const totalDocs = computed(() => kbs.value.reduce((sum, kb) => sum + Number(kb.doc_count || 0), 0))
const totalChunks = computed(() => kbs.value.reduce((sum, kb) => sum + Number(kb.chunk_count || 0), 0))

async function loadKnowledgeBases(searchKeyword = '') {
  loading.value = true
  try {
    const data = await listKnowledgeBases(searchKeyword)
    kbs.value = Array.isArray(data) ? data : []
  } catch (error) {
    ElMessage.error(error?.message || '知识库列表加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.name = ''
  form.description = ''
  form.visibility = 'private'
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

function openEdit(kb) {
  if (!kb.can_write) {
    ElMessage.warning('您对当前知识库仅有只读权限')
    return
  }
  editingId.value = kb.id
  form.name = kb.name || ''
  form.description = kb.description || ''
  form.visibility = kb.visibility || 'private'
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  const payload = {
    name: form.name.trim(),
    description: form.description.trim(),
    visibility: form.visibility || 'private'
  }
  try {
    if (editingId.value) {
      await updateKnowledgeBase(editingId.value, payload)
      ElMessage.success('知识库已更新')
    } else {
      await createKnowledgeBase(payload)
      ElMessage.success('知识库创建成功')
    }
    dialogVisible.value = false
    await loadKnowledgeBases()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败，请重试')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(kb) {
  if (!kb.can_write) {
    ElMessage.warning('您对当前知识库仅有只读权限')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除「${kb.name}」将同时删除其 ${kb.doc_count ?? 0} 个文档、${kb.chunk_count ?? 0} 个分块与全部向量，确定继续吗？`,
      '删除知识库',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  try {
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('知识库已删除')
    await loadKnowledgeBases()
  } catch (error) {
    ElMessage.error(error?.message || '删除失败，请重试')
  }
}

function goDocuments(kb) {
  router.push({ name: 'kb-documents', params: { kbId: kb.id }, query: { name: kb.name } })
}

function coverText(name) {
  return (name || '知').slice(0, 1)
}

const visibilityLabel = (v) => visibilityOptions.find((item) => item.value === v)?.label || '私有'
const visibilityShort = (v) => {
  if (v === 'all') return '全员只读'
  if (v === 'role') return '角色共享'
  return '私有'
}
const accessTypeLabel = (type) => {
  if (type === 'admin') return '管理员'
  if (type === 'owner') return '所有者'
  if (type === 'role') return '角色授权'
  if (type === 'member') return '人员直授'
  if (type === 'all') return '全员可见'
  return ''
}

/* ------------------------------ 知识库授权弹窗 ------------------------------ */
const permissionTarget = ref(null)

function openPermission(kb) {
  // 仅所有者或管理员可配置
  const isOwner = kb.access_type === 'owner'
  if (!isOwner && !auth.isAdmin) {
    ElMessage.warning('仅知识库所有者可配置授权')
    return
  }
  permissionTarget.value = kb
}

async function onPermissionSaved() {
  permissionTarget.value = null
  await loadKnowledgeBases(keyword.value.trim())
}

onMounted(loadKnowledgeBases)
onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div class="page-container page-enter">
    <div class="page-head">
      <div>
        <h1 class="page-title">知识库</h1>
        <p class="page-subtitle">
          共 <b class="gradient-text">{{ kbs.length }}</b> 个知识库 · {{ totalDocs }} 个文档 ·
          {{ totalChunks }} 个分块
        </p>
      </div>
      <div class="page-head-actions">
        <el-input
          v-model="keyword"
          class="kb-search-input"
          placeholder="搜索知识库名称"
          clearable
          @input="handleSearchInput"
          @clear="handleSearchClear"
        >
          <template #prefix><span class="search-prefix">🔍</span></template>
        </el-input>
        <el-button @click="openChunkSearch">🔍 搜索分块</el-button>
        <el-button v-if="auth.isAdmin" @click="router.push('/admin')">⚙ 角色与权限</el-button>
        <el-button type="primary" class="btn-gradient" @click="openCreate">＋ 新建知识库</el-button>
      </div>
    </div>

    <StatsCards class="page-stats" compact />

    <!-- 加载骨架 -->
    <div v-if="loading" class="kb-grid">
      <div v-for="index in 3" :key="`kb-sk-${index}`" class="kb-skeleton skeleton-block"></div>
    </div>

    <!-- 空状态 -->
    <el-empty v-else-if="!kbs.length" :description="keyword ? `未找到名称包含「${keyword}」的知识库` : '还没有知识库，先创建一个吧'">
      <el-button v-if="!keyword" type="primary" class="btn-gradient" @click="openCreate">创建第一个知识库</el-button>
      <el-button v-else @click="handleSearchClear">清空搜索条件</el-button>
    </el-empty>

    <!-- 卡片网格 -->
    <div v-else class="kb-grid">
      <article
        v-for="kb in kbs"
        :key="kb.id"
        class="kb-card surface-card surface-card--hover"
        @click="goDocuments(kb)"
      >
        <div class="kb-card-top">
          <div class="kb-cover">{{ coverText(kb.name) }}</div>
          <div class="kb-title-wrap">
            <h3 class="kb-card-title ellipsis" :title="kb.name">{{ kb.name }}</h3>
            <p class="kb-card-desc">{{ kb.description || '暂无描述' }}</p>
            <div class="kb-card-tags">
              <el-tag size="small" :type="kb.visibility === 'all' ? 'success' : kb.visibility === 'role' ? 'warning' : 'info'" effect="light" round>
                {{ visibilityShort(kb.visibility) }}
              </el-tag>
              <el-tag v-if="kb.access_type && kb.access_type !== 'owner'" size="small" effect="plain" round>
                {{ accessTypeLabel(kb.access_type) }}
              </el-tag>
            </div>
          </div>
        </div>

        <div class="kb-stats">
          <div class="kb-stat">
            <b>{{ kb.doc_count ?? 0 }}</b>
            <span>文档</span>
          </div>
          <div class="kb-stat-divider"></div>
          <div class="kb-stat">
            <b>{{ kb.chunk_count ?? 0 }}</b>
            <span>分块</span>
          </div>
          <div class="kb-enter">进入 →</div>
        </div>

        <div class="kb-card-foot">
          <span class="kb-time">{{ kb.created_at || '' }}</span>
          <div class="kb-actions" @click.stop>
            <el-tooltip v-if="!kb.can_write" content="您对此知识库仅有只读权限">
              <el-tag size="small" type="info" effect="plain">只读</el-tag>
            </el-tooltip>
            <template v-else>
              <button v-if="kb.access_type === 'owner' || auth.isAdmin" type="button" class="ghost-btn" @click="openPermission(kb)">权限</button>
              <button type="button" class="ghost-btn" @click="openEdit(kb)">编辑</button>
              <button type="button" class="ghost-btn is-danger" @click="handleDelete(kb)">删除</button>
            </template>
          </div>
        </div>
      </article>
    </div>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑知识库' : '新建知识库'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="知识库名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：产品手册" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="描述（选填）" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="简单描述这个知识库的用途"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="可见范围">
          <el-select v-model="form.visibility" style="width: 100%">
            <el-option v-for="item in visibilityOptions" :key="item.value" :value="item.value" :label="item.label" />
          </el-select>
          <p class="form-hint">创建后可在「权限」中给指定角色 / 人员授权</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 跨库分块搜索对话框 -->
    <el-dialog
      v-model="chunkSearchVisible"
      title="搜索分块"
      width="640px"
      :close-on-click-modal="false"
      append-to-body
    >
      <div class="chunk-search-bar">
        <el-input
          v-model="chunkKeyword"
          placeholder="输入分块内容关键字，跨全部知识库搜索"
          clearable
          @keyup.enter="doSearchChunks(1)"
        />
        <el-button type="primary" class="btn-gradient" :loading="chunkSearching" @click="doSearchChunks(1)">
          搜索
        </el-button>
      </div>

      <p v-if="chunkSearched" class="chunk-search-total">
        共找到 <b>{{ chunkResult.total }}</b> 个分块
      </p>

      <div v-if="chunkSearching" class="chunk-search-loading">
        <span v-for="index in 3" :key="`cs-sk-${index}`" class="skeleton-block chunk-search-skeleton"></span>
      </div>

      <ul v-else-if="chunkResult.items.length" class="chunk-search-list">
        <li
          v-for="item in chunkResult.items"
          :key="item.id"
          class="chunk-search-item"
          @click="goChunkDocument(item)"
        >
          <div class="chunk-search-line">
            <span class="chunk-search-doc ellipsis">{{ item.doc_name || '未知文档' }}</span>
            <span class="chunk-search-kb">{{ item.kb_name || '' }}</span>
            <span v-if="item.page_no" class="chunk-search-page">第 {{ item.page_no }} 页</span>
            <span v-if="!item.enabled" class="chunk-search-disabled">已停用</span>
          </div>
          <p class="chunk-search-preview">{{ previewText(item.content) }}</p>
        </li>
      </ul>

      <el-empty v-else-if="chunkSearched" description="未找到匹配的分块，换个关键字试试" :image-size="60" />

      <template #footer>
        <div class="chunk-search-footer">
          <el-pagination
            v-if="chunkResult.total > chunkResult.page_size"
            :current-page="chunkResult.page"
            :page-size="chunkResult.page_size"
            :total="chunkResult.total"
            layout="prev, pager, next"
            @current-change="doSearchChunks"
          />
          <el-button @click="chunkSearchVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 知识库授权弹窗 -->
    <KbPermissionDialog
      v-if="permissionTarget"
      :kb="permissionTarget"
      @close="permissionTarget = null"
      @saved="onPermissionSaved"
    />
  </div>
</template>

<style scoped>
.page-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.kb-search-input {
  width: 220px;
}

.search-prefix {
  font-size: 12px;
}

.page-stats {
  margin-bottom: 20px;
}

.kb-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.form-hint {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

/* ---------------- 跨库分块搜索 ---------------- */
.chunk-search-bar {
  display: flex;
  gap: 10px;
}

.chunk-search-total {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.chunk-search-total b {
  color: var(--brand-1);
}

.chunk-search-loading {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.chunk-search-skeleton {
  height: 58px;
  border-radius: var(--radius-sm);
}

.chunk-search-list {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
}

.chunk-search-item {
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.chunk-search-item:hover {
  border-color: var(--el-color-primary-light-7);
  background: #faf8ff;
}

.chunk-search-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}

.chunk-search-doc {
  max-width: 240px;
  font-weight: 600;
  color: var(--text-main);
}

.chunk-search-kb {
  padding: 1px 8px;
  font-size: 11px;
  color: var(--brand-2);
  background: #faf8ff;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 999px;
}

.chunk-search-page,
.chunk-search-disabled {
  padding: 1px 8px;
  font-size: 11px;
  color: var(--text-sub);
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 999px;
}

.chunk-search-disabled {
  color: var(--el-color-danger);
  border-color: #ffd7dd;
}

.chunk-search-preview {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
}

.chunk-search-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}

.kb-skeleton {
  height: 180px;
  border-radius: var(--radius-md);
}

.kb-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 18px;
  cursor: pointer;
  transition: transform var(--transition-base), box-shadow var(--transition-base);
}

.kb-card-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.kb-cover {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--brand-1), var(--brand-2));
  flex-shrink: 0;
}

.kb-title-wrap {
  flex: 1;
  min-width: 0;
}

.kb-card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-main);
}

.kb-card-desc {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.kb-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 16px 0 12px;
  padding: 10px 0;
  border-top: 1px dashed var(--border-color);
  border-bottom: 1px dashed var(--border-color);
}

.kb-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.kb-stat b {
  font-size: 18px;
  color: var(--text-main);
}

.kb-stat span {
  font-size: 11.5px;
  color: var(--text-muted);
}

.kb-stat-divider {
  width: 1px;
  height: 24px;
  background: var(--border-color);
}

.kb-enter {
  margin-left: auto;
  font-size: 13px;
  color: var(--brand-1);
  font-weight: 500;
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-enter {
  opacity: 1;
}

.kb-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.kb-time {
  font-size: 11.5px;
  color: var(--text-muted);
}

.kb-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.ghost-btn {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 6px;
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-main);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ghost-btn:hover {
  border-color: var(--brand-1);
  color: var(--brand-1);
}

.ghost-btn.is-danger:hover {
  border-color: var(--el-color-danger);
  color: var(--el-color-danger);
}
</style>
