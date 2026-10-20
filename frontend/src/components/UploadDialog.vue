<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadDocument } from '@/api/kb'

/**
 * 上传文档对话框
 * - 支持 pdf / ppt / pptx / md / markdown / txt / 图片 / docx
 * - 可配置切块大小、重叠大小、检索方式（dense 稠密 / hybrid 混合）
 * - 提交后由父组件负责轮询解析进度
 */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  kbId: { type: [Number, String], default: '' },
  kbName: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'success'])

// 允许上传的扩展名
const ALLOWED_EXTENSIONS = ['pdf', 'ppt', 'pptx', 'md', 'markdown', 'txt', 'png', 'jpg', 'jpeg', 'bmp', 'webp', 'docx']
const ACCEPT_ATTR = ALLOWED_EXTENSIONS.map((ext) => `.${ext}`).join(',')
const MAX_SIZE = 100 * 1024 * 1024 // 100MB

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const fileList = ref([])
const submitting = ref(false)
const form = ref({ chunk_size: 500, chunk_overlap: 50, retrieval_mode: 'hybrid' })

const selectedFile = computed(() => fileList.value[0]?.raw || null)

/** 重置表单 */
function resetForm() {
  fileList.value = []
  form.value = { chunk_size: 500, chunk_overlap: 50, retrieval_mode: 'hybrid' }
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) resetForm()
  }
)

/** 校验扩展名 */
function getExtension(filename = '') {
  const index = filename.lastIndexOf('.')
  return index === -1 ? '' : filename.slice(index + 1).toLowerCase()
}

/** 选择文件：只保留最新一个文件 */
function handleFileChange(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return
  const ext = getExtension(raw.name)
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    ElMessage.error(`不支持的文件类型：.${ext || '未知'}，仅支持 ${ALLOWED_EXTENSIONS.join(' / ')}`)
    fileList.value = []
    return
  }
  if (raw.size > MAX_SIZE) {
    ElMessage.error('文件过大，请上传 100MB 以内的文档')
    fileList.value = []
    return
  }
  fileList.value = [uploadFile]
}

/** 移除文件 */
function handleFileRemove() {
  fileList.value = []
}

/** 提交上传 */
async function handleSubmit() {
  if (!props.kbId) {
    ElMessage.error('缺少知识库信息，请返回文档列表重试')
    return
  }
  if (!selectedFile.value) {
    ElMessage.warning('请先选择需要上传的文档')
    return
  }
  const chunkSize = Number(form.value.chunk_size)
  const chunkOverlap = Number(form.value.chunk_overlap)
  if (!Number.isFinite(chunkSize) || chunkSize < 100 || chunkSize > 2000) {
    ElMessage.warning('切块大小需在 100 ~ 2000 之间')
    return
  }
  if (!Number.isFinite(chunkOverlap) || chunkOverlap < 0 || chunkOverlap >= chunkSize) {
    ElMessage.warning('重叠大小需满足 0 ≤ 重叠 < 切块大小')
    return
  }

  submitting.value = true
  try {
    const doc = await uploadDocument(props.kbId, {
      file: selectedFile.value,
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
      retrieval_mode: form.value.retrieval_mode
    })
    ElMessage.success('上传成功，正在后台解析')
    emit('success', doc)
    visible.value = false
    resetForm()
  } catch (error) {
    ElMessage.error(error?.message || '上传失败，请重试')
  } finally {
    submitting.value = false
  }
}

/** 格式化文件大小 */
function formatSize(size) {
  if (!Number.isFinite(size)) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="上传文档"
    width="560px"
    :close-on-click-modal="false"
    append-to-body
    class="upload-dialog"
  >
    <div class="upload-head">
      <span class="upload-kb">目标知识库：{{ kbName || '当前知识库' }}</span>
      <span class="upload-tip">支持 PDF / PPT / Markdown / TXT / 图片 / DOCX</span>
    </div>

    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="false"
      :accept="ACCEPT_ATTR"
      :on-change="handleFileChange"
      :on-remove="handleFileRemove"
      class="upload-area"
    >
      <div class="upload-inner">
        <div class="upload-icon">↑</div>
        <p class="upload-main">将文件拖到此处，或<em>点击选择文件</em></p>
        <p class="upload-sub">单个文件不超过 {{ formatSize(MAX_SIZE) }}</p>
      </div>
    </el-upload>

    <div class="upload-params">
      <div class="param-item">
        <label class="param-label">切块大小</label>
        <el-input-number v-model="form.chunk_size" :min="100" :max="2000" :step="50" controls-position="right" />
        <span class="param-hint">100 ~ 2000，默认 500</span>
      </div>
      <div class="param-item">
        <label class="param-label">重叠大小</label>
        <el-input-number
          v-model="form.chunk_overlap"
          :min="0"
          :max="Math.max(0, Number(form.chunk_size) - 1)"
          :step="10"
          controls-position="right"
        />
        <span class="param-hint">需小于切块大小，默认 50</span>
      </div>
      <div class="param-item">
        <label class="param-label">检索方式</label>
        <el-radio-group v-model="form.retrieval_mode">
          <el-radio-button value="dense">稠密检索</el-radio-button>
          <el-radio-button value="hybrid">混合检索</el-radio-button>
        </el-radio-group>
        <span class="param-hint">稠密=纯向量；混合=向量+关键字</span>
      </div>
    </div>

    <template #footer>
      <div class="upload-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" :loading="submitting" @click="handleSubmit">
          上传并解析
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.upload-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.upload-kb {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-1);
}

.upload-tip {
  font-size: 11.5px;
  color: var(--text-muted);
}

.upload-area :deep(.el-upload-dragger) {
  padding: 26px 16px;
  border: 1.5px dashed var(--el-color-primary-light-5);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, #fbfaff 0%, #f7f6ff 100%);
  transition: all var(--transition-base);
}

.upload-area :deep(.el-upload-dragger:hover) {
  border-color: var(--brand-1);
  background: #f6f4ff;
  box-shadow: var(--shadow-sm);
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.upload-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 6px;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  background: var(--brand-gradient);
  border-radius: 14px;
  box-shadow: var(--shadow-brand);
}

.upload-main {
  font-size: 14px;
  color: var(--text-sub);
}

.upload-main em {
  font-style: normal;
  font-weight: 600;
  color: var(--brand-1);
}

.upload-sub {
  font-size: 11.5px;
  color: var(--text-muted);
}

.upload-params {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 18px;
  padding: 16px;
  border-radius: var(--radius-md);
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
}

.param-item {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.param-label {
  width: 72px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
}

.param-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}

.upload-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 768px) {
  .param-label {
    width: 100%;
  }
}
</style>
