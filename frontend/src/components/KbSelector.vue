<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listKnowledgeBases } from '@/api/kb'

/**
 * 知识库多选组件（对话页顶部）
 * v-model:modelValue 为已选知识库 id 数组
 */
const props = defineProps({
  modelValue: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'change'])

const kbs = ref([])
const loading = ref(false)
const inner = ref([...(props.modelValue || [])])

/** 拉取知识库列表 */
async function loadKnowledgeBases() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await listKnowledgeBases()
    kbs.value = Array.isArray(data) ? data : []
    // 清理已被删除的知识库选项
    const validIds = new Set(kbs.value.map((kb) => kb.id))
    const kept = inner.value.filter((id) => validIds.has(id))
    if (kept.length !== inner.value.length) {
      inner.value = kept
      emit('update:modelValue', kept)
      emit('change', kept)
    }
  } catch (error) {
    ElMessage.error(error?.message || '知识库列表加载失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (value) => {
    const next = value || []
    if (JSON.stringify(next) !== JSON.stringify(inner.value)) inner.value = [...next]
  },
  { deep: true }
)

/** 选择变化：同步给父组件 */
function handleChange(value) {
  const next = Array.isArray(value) ? value : []
  inner.value = next
  emit('update:modelValue', [...next])
  emit('change', [...next])
}

onMounted(loadKnowledgeBases)
defineExpose({ reload: loadKnowledgeBases })
</script>

<template>
  <div class="kb-selector">
    <el-select
      :model-value="inner"
      multiple
      collapse-tags
      collapse-tags-tooltip
      :max-collapse-tags="2"
      clearable
      filterable
      :loading="loading"
      placeholder="选择知识库（可多选）"
      class="kb-select"
      popper-class="kb-select-popper"
      @change="handleChange"
    >
      <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id">
        <div class="kb-option">
          <span class="kb-option-name ellipsis">{{ kb.name }}</span>
          <span class="kb-option-meta">{{ kb.doc_count ?? 0 }} 文档 · {{ kb.chunk_count ?? 0 }} 分块</span>
        </div>
      </el-option>
      <template #empty>
        <div class="kb-empty">暂无知识库，可先在「知识库」页面创建</div>
      </template>
    </el-select>

    <button
      type="button"
      class="kb-refresh"
      :class="{ spinning: loading }"
      title="刷新知识库列表"
      @click="loadKnowledgeBases"
    >
      ⟳
    </button>
  </div>
</template>

<style scoped>
.kb-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.kb-select {
  width: 320px;
  max-width: 52vw;
}

.kb-option {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
}

.kb-option-name {
  font-size: 13px;
  color: var(--text-main);
}

.kb-option-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.kb-empty {
  padding: 14px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

.kb-refresh {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  font-size: 15px;
  color: var(--text-muted);
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 50%;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.kb-refresh:hover {
  color: var(--brand-1);
  border-color: var(--el-color-primary-light-7);
  transform: rotate(90deg);
}

@media (max-width: 768px) {
  .kb-select {
    width: 100%;
    max-width: none;
  }
}
</style>
