<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadDocument, uploadDocumentsBatch } from '@/api/kb'

/**
 * 上传文档对话框
 * - 支持 pdf / ppt / pptx / md / markdown / txt / 图片 / docx
 * - 支持多选批量上传（单次最多 20 个，单个文件失败不影响其它文件）
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
const MAX_BATCH = 20 // 单次批量上传上限

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const fileList = ref([])
const submitting = ref(false)
const form = ref({ chunk_size: 500, chunk_overlap: 50, retrieval_mode: 'hybrid' })

const selectedFiles = computed(() => fileList.value.map((item) => item.raw).filter(Boolean))

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

/** 选择文件：累积多选，逐个校验（类型 / 体积 / 数量） */
function handleFileChange(uploadFile, uploadFiles) {
  const raw = uploadFile?.raw
  if (!raw) return
  const ext = getExtension(raw.name)
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    ElMessage.error(`不支持的文件类型：.${ext || '未知'}，仅支持 ${ALLOWED_EXTENSIONS.join(' / ')}`)
    fileList.value = fileList.value.filter((item) => item.uid !== uploadFile.uid)
    return
  }
  if (raw.size > MAX_SIZE) {
    ElMessage.error(`「${raw.name}」超过 ${formatSize(MAX_SIZE)}，已跳过`)
    fileList.value = fileList.value.filter((item) => item.uid !== uploadFile.uid)
    return
  }
  if (uploadFiles.length > MAX_BATCH) {
    ElMessage.error(`单次最多上传 ${MAX_BATCH} 个文件，已跳过「${raw.name}」`)
    fileList.value = fileList.value.filter((item) => item.uid !== uploadFile.uid)
    return
  }
  fileList.value = uploadFiles
}

/** 移除文件 */
function handleFileRemove() {
  // el-upload 的 v-model:file-list 会自动同步，这里仅兜底空列表
  if (!fileList.value.length) resetForm()
}

/** 提交上传（单个文件走原接口，多个文件走批量接口） */
async function handleSubmit() {
  if (!props.kbId) {
    ElMessage.error('缺少知识库信息，请返回文档列表重试')
    return
  }
  if (!selectedFiles.value.length) {
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
    let uploaded = []
    if (selectedFiles.value.length === 1) {
      const doc = await uploadDocument(props.kbId, {
        file: selectedFiles.value[0],
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        retrieval_mode: form.value.retrieval_mode
      })
      uploaded = [doc]
      ElMessage.success('上传成功，正在后台解析')
    } else {
      const result = await uploadDocumentsBatch(props.kbId, {
        files: selectedFiles.value,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        retrieval_mode: form.value.retrieval_mode
      })
      uploaded = Array.isArray(result?.uploaded) ? result.uploaded : []
      const failed = Array.isArray(result?.failed) ? result.failed : []
      if (failed.length) {
        const names = failed.map((item) => item.filename).filter(Boolean).join('、')
        ElMessage.warning(`上传完成：成功 ${uploaded.length} 个，失败 ${failed.length} 个${names ? `（${names}）` : ''}`)
      } else {
        ElMessage.success(`上传成功，${uploaded.length} 个文档正在后台解析`)
      }
    }
    emit('success', uploaded)
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
      multiple
      :auto-upload="false"
      :accept="ACCEPT_ATTR"
      :on-change="handleFileChange"
      :on-remove="handleFileRemove"
      class="upload-area"
    >
      <div class="upload-inner">
        <div class="upload-icon">↑</div>
        <p class="upload-main">将文件拖到此处，或<em>点击选择文件</em></p>
        <p class="upload-sub">支持多选，单次最多 {{ MAX_BATCH }} 个，单个文件不超过 {{ formatSize(MAX_SIZE) }}</p>
      </div>
    </el-upload>

    <p v-if="fileList.length" class="upload-selected">已选择 {{ fileList.length }} 个文件</p>

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

.upload-selected {
  margin-top: 10px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand-1);
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
