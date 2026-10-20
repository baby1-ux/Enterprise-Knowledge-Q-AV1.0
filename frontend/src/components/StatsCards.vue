<script setup>
import { onMounted, ref } from 'vue'
import { fetchStats } from '@/api/system'

/**
 * 用量统计卡片：展示当前用户的知识库 / 文档 / 分块 / 会话 / 回答数据
 * 统计失败时静默隐藏，不打扰用户
 */
defineProps({
  /** compact = 紧凑模式（单行小卡片） */
  compact: { type: Boolean, default: false }
})

const emit = defineEmits(['loaded'])

const stats = ref(null)
const failed = ref(false)

const CARDS = [
  { key: 'knowledge_base_count', label: '知识库', icon: '库' },
  { key: 'document_count', label: '文档', icon: '档' },
  { key: 'chunk_count', label: '分块', icon: '块' },
  { key: 'session_count', label: '会话', icon: '话' },
  { key: 'answer_count', label: '累计回答', icon: '答' },
  { key: 'today_answer_count', label: '今日回答', icon: '今' }
]

onMounted(async () => {
  try {
    stats.value = await fetchStats()
    emit('loaded', stats.value)
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div v-if="stats && !failed" class="stats-cards" :class="{ 'is-compact': compact }">
    <div v-for="card in CARDS" :key="card.key" class="stat-card surface-card">
      <span class="stat-icon">{{ card.icon }}</span>
      <div class="stat-main">
        <b class="stat-value gradient-text">{{ stats[card.key] ?? 0 }}</b>
        <span class="stat-label">{{ card.label }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
}

.stats-cards.is-compact {
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 8px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  animation: fadeSlideIn 0.4s both;
}

.is-compact .stat-card {
  padding: 8px 10px;
  gap: 8px;
}

.stat-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.08);
  border-radius: 10px;
}

.is-compact .stat-icon {
  width: 26px;
  height: 26px;
  font-size: 11px;
  border-radius: 8px;
}

.stat-main {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.stat-value {
  font-size: 19px;
  font-weight: 800;
}

.is-compact .stat-value {
  font-size: 15px;
}

.stat-label {
  font-size: 11.5px;
  color: var(--text-muted);
}
</style>
