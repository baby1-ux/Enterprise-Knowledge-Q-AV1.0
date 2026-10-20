<script setup>
import { computed, onBeforeUnmount, reactive, watch } from 'vue'

/**
 * 推理参数抽屉（对话页右侧）
 * 实现说明：使用自定义固定定位面板而非 el-drawer，避免遮罩层拦截聊天区点击，
 * 打开面板时聊天区整体左移，保持「不遮挡聊天区」的交互体验。
 */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 当前会话已保存的参数 */
  params: { type: Object, default: () => ({}) },
  /** 可选模型列表 [{ value, label, description }] */
  models: { type: Array, default: () => [] },
  /** 后端返回的默认参数 */
  defaults: { type: Object, default: () => ({}) },
  saving: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'save'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// 表单副本：打开面板时用当前会话参数覆盖
const form = reactive({
  model: '',
  temperature: 0.3,
  top_p: 0.8,
  max_tokens: 2048,
  history_rounds: 5,
  retrieval_mode: 'hybrid'
})

/** 用当前参数填充表单 */
function syncForm() {
  const source = props.params || {}
  const fallback = props.defaults || {}
  form.model = source.model || fallback.model || props.models[0]?.value || ''
  form.temperature = Number(source.temperature ?? fallback.temperature ?? 0.3)
  form.top_p = Number(source.top_p ?? fallback.top_p ?? 0.8)
  form.max_tokens = Number(source.max_tokens ?? fallback.max_tokens ?? 2048)
  form.history_rounds = Number(source.history_rounds ?? fallback.history_rounds ?? 5)
  form.retrieval_mode = source.retrieval_mode || fallback.retrieval_mode || 'hybrid'
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) syncForm()
  },
  { immediate: true }
)

/** 当前选中模型的说明文字 */
const currentModelDesc = computed(() => props.models.find((item) => item.value === form.model)?.description || '')

/** 是否为推理模型（DeepSeek-Reasoner 不支持温度与 Top P 采样参数） */
const isReasonerModel = computed(() => {
  const name = String(form.model || '').toLowerCase()
  return name.includes('reasoner') || name.includes('r1')
})

/** 保存参数 */
function handleSave() {
  emit('save', {
    model: form.model,
    temperature: Number(Number(form.temperature).toFixed(2)),
    top_p: Number(Number(form.top_p).toFixed(2)),
    max_tokens: Math.round(Number(form.max_tokens) || 2048),
    history_rounds: Math.round(Number(form.history_rounds) || 0),
    retrieval_mode: form.retrieval_mode
  })
}

/** 恢复后端默认参数 */
function handleRestore() {
  const fallback = props.defaults || {}
  form.model = fallback.model || props.models[0]?.value || form.model
  form.temperature = Number(fallback.temperature ?? 0.3)
  form.top_p = Number(fallback.top_p ?? 0.8)
  form.max_tokens = Number(fallback.max_tokens ?? 2048)
  form.history_rounds = Number(fallback.history_rounds ?? 5)
  form.retrieval_mode = fallback.retrieval_mode || 'hybrid'
}

/** ESC 关闭面板 */
function handleKeydown(event) {
  if (event.key === 'Escape' && visible.value) visible.value = false
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) window.addEventListener('keydown', handleKeydown)
    else window.removeEventListener('keydown', handleKeydown)
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <teleport to="body">
    <transition name="param-slide">
      <aside v-if="visible" class="param-panel" role="dialog" aria-label="参数设置">
        <header class="param-panel-head">
          <div class="param-panel-title">
            <h3>参数设置</h3>
            <p>调整模型与推理参数，保存后作用于当前会话</p>
          </div>
          <button type="button" class="panel-close" title="关闭（Esc）" @click="visible = false">✕</button>
        </header>

        <div class="param-panel-body">
          <!-- 模型 -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">模型</span>
              <span class="param-tip">选择回答使用的大模型</span>
            </div>
            <el-select v-model="form.model" placeholder="请选择模型" class="param-control">
              <el-option v-for="item in models" :key="item.value" :label="item.label" :value="item.value">
                <div class="model-option">
                  <span class="model-label">{{ item.label }}</span>
                  <span class="model-desc">{{ item.description }}</span>
                </div>
              </el-option>
            </el-select>
            <p v-if="currentModelDesc" class="param-extra">{{ currentModelDesc }}</p>
          </section>

          <!-- 推理模型提示：R1 系列不支持采样参数 -->
          <el-alert
            v-if="isReasonerModel"
            class="reasoner-tip"
            type="info"
            :closable="false"
            show-icon
            title="当前为推理模型，温度与 Top P 将被忽略"
            description="DeepSeek-Reasoner 会先思考再作答，不支持采样参数；系统会自动省略这两项，并只向页面输出最终答案。"
          />

          <!-- 温度 -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">温度</span>
              <span class="param-value">{{ Number(form.temperature).toFixed(1) }}</span>
            </div>
            <el-slider
              v-model="form.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :show-tooltip="false"
              :disabled="isReasonerModel"
            />
            <p class="param-extra">
              {{ isReasonerModel ? '当前模型不支持该参数，已自动忽略。' : '取值越高回答越发散，越低越稳定严谨（推荐 0.2 ~ 0.5）。' }}
            </p>
          </section>

          <!-- Top P -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">Top P</span>
              <span class="param-value">{{ Number(form.top_p).toFixed(2) }}</span>
            </div>
            <el-slider
              v-model="form.top_p"
              :min="0.1"
              :max="1"
              :step="0.05"
              :show-tooltip="false"
              :disabled="isReasonerModel"
            />
            <p class="param-extra">
              {{ isReasonerModel ? '当前模型不支持该参数，已自动忽略。' : '核采样阈值，控制候选词范围（推荐 0.7 ~ 0.9）。' }}
            </p>
          </section>

          <!-- 最长输出 token -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">最长输出 Token</span>
              <span class="param-tip">256 ~ 8192</span>
            </div>
            <el-input-number
              v-model="form.max_tokens"
              :min="256"
              :max="8192"
              :step="256"
              step-strictly
              controls-position="right"
              class="param-control"
            />
            <p class="param-extra">单次回答的最大长度，数值越大可输出越长的内容。</p>
          </section>

          <!-- 历史对话轮数 -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">历史对话轮数</span>
              <span class="param-value">{{ form.history_rounds }} 轮</span>
            </div>
            <el-slider v-model="form.history_rounds" :min="0" :max="20" :step="1" :show-tooltip="false" />
            <p class="param-extra">带入上下文的历史问答轮数，0 表示不携带历史（默认 5）。</p>
          </section>

          <!-- 检索模式 -->
          <section class="param-block">
            <div class="param-head">
              <span class="param-label">检索模式</span>
            </div>
            <el-radio-group v-model="form.retrieval_mode" class="param-radio">
              <el-radio-button value="dense">稠密检索</el-radio-button>
              <el-radio-button value="hybrid">混合检索</el-radio-button>
            </el-radio-group>
            <p class="param-extra">稠密检索使用向量相似度；混合检索同时融合关键字与向量，召回更全面。</p>
          </section>
        </div>

        <footer class="param-panel-foot">
          <el-button text @click="handleRestore">恢复默认</el-button>
          <el-button type="primary" class="btn-gradient" :loading="saving" @click="handleSave">保存参数</el-button>
        </footer>
      </aside>
    </transition>
  </teleport>
</template>

<style scoped>
.param-panel {
  position: fixed;
  top: var(--header-height);
  right: 0;
  bottom: 0;
  z-index: 2200;
  display: flex;
  flex-direction: column;
  width: 380px;
  max-width: 92vw;
  background: #fff;
  border-left: 1px solid var(--border-color);
  box-shadow: -14px 0 40px rgba(99, 102, 241, 0.14);
}

.param-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--border-color);
}

.param-panel-title h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
}

.param-panel-title p {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.panel-close {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  font-size: 13px;
  color: var(--text-muted);
  background: var(--bg-muted);
  border: 0;
  border-radius: 50%;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.panel-close:hover {
  color: #fff;
  background: var(--brand-gradient);
  transform: rotate(90deg);
}

.param-panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 18px 20px 24px;
}

.param-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 推理模型提示条 */
.reasoner-tip {
  margin-top: -6px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.18);
}

.param-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.param-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.param-tip {
  font-size: 11px;
  color: var(--text-muted);
}

.param-value {
  min-width: 46px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.1);
  border-radius: 999px;
}

.param-extra {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-muted);
}

.param-control {
  width: 100%;
}

.model-option {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.model-label {
  font-size: 13px;
  color: var(--text-main);
}

.model-desc {
  font-size: 11px;
  color: var(--text-muted);
}

.param-radio {
  width: 100%;
}

.param-radio :deep(.el-radio-button) {
  flex: 1;
}

.param-radio :deep(.el-radio-button__inner) {
  width: 100%;
  border-radius: 999px;
}

.param-panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border-color);
  background: rgba(250, 250, 255, 0.9);
}

/* 滑入滑出 */
.param-slide-enter-active,
.param-slide-leave-active {
  transition: transform var(--transition-base), opacity var(--transition-base);
}

.param-slide-enter-from,
.param-slide-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
</style>
