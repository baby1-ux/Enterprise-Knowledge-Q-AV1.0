<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createKnowledgeBase, deleteKnowledgeBase, listKnowledgeBases, updateKnowledgeBase } from '@/api/kb'

// 知识库管理：卡片网格展示 + 新建 / 编辑 / 删除 + 进入文档列表
const router = useRouter()

const kbs = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const form = reactive({ name: '', description: '' })

const rules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { max: 50, message: '名称不超过 50 个字符', trigger: 'blur' }
  ],
  description: [{ max: 200, message: '描述不超过 200 个字符', trigger: 'blur' }]
}

// 顶部统计
const totalDocs = computed(() => kbs.value.reduce((sum, kb) => sum + Number(kb.doc_count || 0), 0))
const totalChunks = computed(() => kbs.value.reduce((sum, kb) => sum + Number(kb.chunk_count || 0), 0))

/** 加载知识库列表 */
async function loadKnowledgeBases() {
  loading.value = true
  try {
    const data = await listKnowledgeBases()
    kbs.value = Array.isArray(data) ? data : []
  } catch (error) {
    ElMessage.error(error?.message || '知识库列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 打开新建对话框 */
function openCreate() {
  editingId.value = null
  form.name = ''
  form.description = ''
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

/** 打开编辑对话框 */
function openEdit(kb) {
  editingId.value = kb.id
  form.name = kb.name || ''
  form.description = kb.description || ''
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

/** 提交新建 / 编辑 */
async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  const payload = { name: form.name.trim(), description: form.description.trim() }
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

/** 删除知识库 */
async function handleDelete(kb) {
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

/** 进入文档列表 */
function goDocuments(kb) {
  router.push({ name: 'kb-documents', params: { kbId: kb.id }, query: { name: kb.name } })
}

/** 名称首字符作为封面字 */
function coverText(name) {
  return (name || '知').slice(0, 1)
}

onMounted(loadKnowledgeBases)
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
      <el-button type="primary" class="btn-gradient" @click="openCreate">＋ 新建知识库</el-button>
    </div>

    <!-- 加载骨架 -->
    <div v-if="loading" class="kb-grid">
      <div v-for="index in 3" :key="`kb-sk-${index}`" class="kb-skeleton skeleton-block"></div>
    </div>

    <!-- 空状态 -->
    <el-empty v-else-if="!kbs.length" description="还没有知识库，先创建一个吧">
      <el-button type="primary" class="btn-gradient" @click="openCreate">创建第一个知识库</el-button>
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
            <button type="button" class="ghost-btn" @click="openEdit(kb)">编辑</button>
            <button type="button" class="ghost-btn is-danger" @click="handleDelete(kb)">删除</button>
          </div>
        </div>
      </article>
    </div>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑知识库' : '新建知识库'"
      width="460px"
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
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}

.kb-skeleton {
  height: 188px;
  border-radius: var(--radius-md);
}

.kb-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  cursor: pointer;
  animation: fadeSlideIn 0.4s both;
}

.kb-card-top {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.kb-cover {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  background: var(--brand-gradient);
  background-size: 160% 160%;
  border-radius: 14px;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.28);
  transition: transform var(--transition-base);
}

.kb-card:hover .kb-cover {
  transform: rotate(-6deg) scale(1.05);
}

.kb-title-wrap {
  min-width: 0;
  flex: 1;
}

.kb-card-title {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--text-main);
}

.kb-card-desc {
  margin-top: 5px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}

.kb-stats {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
}

.kb-stat {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.kb-stat b {
  font-size: 17px;
  font-weight: 800;
  color: var(--brand-1);
}

.kb-stat span {
  font-size: 11px;
  color: var(--text-muted);
}

.kb-stat-divider {
  width: 1px;
  height: 26px;
  background: var(--border-strong);
}

.kb-enter {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-2);
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--transition-base);
}

.kb-card:hover .kb-enter {
  opacity: 1;
  transform: translateX(0);
}

.kb-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 4px;
  border-top: 1px dashed var(--border-color);
}

.kb-time {
  font-size: 11px;
  color: var(--text-muted);
}

.kb-actions {
  display: flex;
  gap: 8px;
}

.ghost-btn.is-danger:hover {
  color: var(--el-color-danger);
  background: #fff1f3;
  border-color: #ffd7dd;
}

@media (max-width: 768px) {
  .kb-grid {
    grid-template-columns: 1fr;
  }
}
</style>
