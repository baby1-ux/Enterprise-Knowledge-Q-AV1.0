<script setup>
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

/**
 * 消息气泡组件
 * - 助手消息使用 markdown-it 渲染（html:false + linkify），highlight.js 做代码高亮
 * - 引用来源支持折叠展开
 * - 生成过程中展示呼吸光标，滚动跟随由父组件负责
 */
const props = defineProps({
  /** { id, role, content, citations, streaming, error, stopped } */
  message: { type: Object, required: true }
})

const open = ref(true)
const copied = ref(false)

const role = computed(() => props.message?.role || 'assistant')
const citations = computed(() => props.message?.citations || [])

// markdown 渲染器（禁止原始 HTML，避免 XSS；开启自动识别链接）
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        // 高亮失败时回退为纯文本
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  }
})

// 外链在新标签页打开
const defaultLinkOpen = md.renderer.rules.link_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

const renderedHtml = computed(() => {
  const content = props.message?.content || ''
  if (!content) return ''
  // 流式输出时补一个换行使未闭合的代码块不至于吞掉后续内容
  return md.render(props.message?.streaming ? `${content}\n` : content)
})

/** 相似度展示：0~1 转为百分比 */
function formatScore(score) {
  const value = Number(score)
  if (!Number.isFinite(value)) return '—'
  const percent = value > 1 ? value : value * 100
  return `${percent.toFixed(1)}%`
}

/** 复制回答内容 */
async function copyContent() {
  const text = props.message?.content || ''
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 1600)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <div class="bubble" :class="[`is-${role}`, { 'is-streaming': message.streaming }]">
    <div class="bubble-avatar" :class="`avatar-${role}`">{{ role === 'user' ? '我' : 'AI' }}</div>

    <div class="bubble-body">
      <div class="bubble-card">
        <div v-if="role === 'assistant'" class="markdown-body" v-html="renderedHtml"></div>
        <div v-else class="bubble-plain">{{ message.content }}</div>

        <span v-if="message.streaming" class="typing-caret" aria-hidden="true"></span>

        <div v-if="message.error" class="bubble-note is-error">{{ message.error }}</div>
        <div v-else-if="message.stopped" class="bubble-note">已停止生成</div>
      </div>

      <!-- 引用来源 -->
      <div v-if="citations.length" class="citations">
        <button type="button" class="citations-toggle" @click="open = !open">
          <span class="citations-dot"></span>
          引用来源 <b>{{ citations.length }}</b> 条
          <span class="citations-arrow" :class="{ 'is-open': open }">▾</span>
        </button>

        <transition name="fold">
          <ol v-show="open" class="citations-list">
            <li v-for="(item, index) in citations" :key="`${item.chunk_id || 'c'}-${index}`" class="citation-item">
              <span class="citation-index">{{ item.index ?? index + 1 }}</span>
              <div class="citation-main">
                <div class="citation-line">
                  <span class="citation-doc ellipsis" :title="item.doc_name">{{ item.doc_name || '未知文档' }}</span>
                  <span v-if="item.page_no !== null && item.page_no !== undefined" class="citation-tag">
                    第 {{ item.page_no }} 页
                  </span>
                  <span v-if="item.kb_name" class="citation-tag is-kb">{{ item.kb_name }}</span>
                  <span class="citation-score">相似度 {{ formatScore(item.score) }}</span>
                </div>
                <p v-if="item.preview" class="citation-preview ellipsis-2">{{ item.preview }}</p>
              </div>
            </li>
          </ol>
        </transition>
      </div>

      <!-- 操作区 -->
      <div v-if="role === 'assistant' && message.content && !message.streaming" class="bubble-actions">
        <button type="button" class="ghost-btn" @click="copyContent">{{ copied ? '已复制' : '复制回答' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  animation: bubbleIn 0.32s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}

.bubble.is-user {
  flex-direction: row-reverse;
}

.bubble-avatar {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.4px;
}

.avatar-assistant {
  color: #fff;
  background: var(--brand-gradient);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.26);
}

.avatar-user {
  color: var(--brand-1);
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
}

.bubble-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  max-width: min(760px, calc(100% - 46px));
}

.bubble.is-user .bubble-body {
  align-items: flex-end;
}

.bubble-card {
  position: relative;
  padding: 13px 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition-base), border-color var(--transition-base);
}

.bubble-card:hover {
  box-shadow: var(--shadow-md);
}

.bubble.is-user .bubble-card {
  color: #fff;
  border-color: transparent;
  background: var(--brand-gradient);
  background-size: 150% 150%;
  box-shadow: 0 10px 24px rgba(99, 102, 241, 0.26);
  border-bottom-right-radius: 6px;
}

.bubble.is-assistant .bubble-card {
  border-bottom-left-radius: 6px;
}

.is-streaming .bubble-card {
  border-color: var(--el-color-primary-light-7);
}

.bubble-plain {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.75;
}

.bubble-note {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.bubble-note.is-error {
  color: var(--el-color-danger);
}

/* 生成中的呼吸光标 */
.typing-caret {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 3px;
  vertical-align: -2px;
  border-radius: 2px;
  background: var(--brand-gradient);
  animation: cursorBlink 1s steps(1, end) infinite;
}

/* ---------------- markdown 渲染样式 ---------------- */
.markdown-body {
  font-size: 14px;
  line-height: 1.78;
  color: var(--text-main);
  word-break: break-word;
}

.markdown-body :deep(> *:first-child) {
  margin-top: 0;
}

.markdown-body :deep(> *:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(p) {
  margin: 0 0 10px;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 16px 0 8px;
  line-height: 1.4;
  font-weight: 700;
  color: var(--text-main);
}

.markdown-body :deep(h1) {
  font-size: 19px;
}

.markdown-body :deep(h2) {
  font-size: 17px;
}

.markdown-body :deep(h3) {
  font-size: 15px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 10px;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 3px 0;
}

.markdown-body :deep(li::marker) {
  color: var(--brand-2);
}

.markdown-body :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 14px;
  color: var(--text-sub);
  border-left: 3px solid var(--el-color-primary-light-5);
  border-radius: 0 var(--radius-xs) var(--radius-xs) 0;
  background: var(--bg-muted);
}

.markdown-body :deep(strong) {
  font-weight: 700;
  color: var(--brand-1);
}

.markdown-body :deep(code:not(pre code)) {
  padding: 2px 6px;
  font-size: 12.5px;
  font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
  color: var(--brand-2);
  background: rgba(139, 92, 246, 0.1);
  border-radius: 6px;
}

.markdown-body :deep(pre) {
  margin: 10px 0;
  padding: 12px 14px;
  overflow-x: auto;
  border-radius: var(--radius-sm);
  background: #1f2233;
  box-shadow: var(--shadow-sm);
}

.markdown-body :deep(pre code) {
  padding: 0;
  font-size: 12.5px;
  font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
  background: transparent;
}

.markdown-body :deep(table) {
  width: 100%;
  margin: 10px 0;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--bg-muted);
  font-weight: 600;
}

.markdown-body :deep(a) {
  color: var(--brand-1);
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}

.markdown-body :deep(hr) {
  height: 1px;
  margin: 14px 0;
  border: 0;
  background: var(--border-color);
}

/* ---------------- 引用来源 ---------------- */
.citations {
  padding-left: 2px;
}

.citations-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text-sub);
  background: rgba(99, 102, 241, 0.07);
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.citations-toggle:hover {
  color: var(--brand-1);
  border-color: var(--el-color-primary-light-7);
  background: rgba(99, 102, 241, 0.12);
}

.citations-toggle b {
  color: var(--brand-1);
}

.citations-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-gradient);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.16);
}

.citations-arrow {
  font-size: 10px;
  transition: transform var(--transition-base);
}

.citations-arrow.is-open {
  transform: rotate(180deg);
}

.citations-list {
  margin: 8px 0 0;
  padding: 4px;
  list-style: none;
  border-radius: var(--radius-sm);
  background: rgba(245, 246, 251, 0.9);
  border: 1px solid var(--border-color);
}

.citation-item {
  display: flex;
  gap: 9px;
  padding: 8px 10px;
  border-radius: var(--radius-xs);
  transition: background var(--transition-fast);
}

.citation-item:hover {
  background: #fff;
}

.citation-index {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 19px;
  height: 19px;
  margin-top: 1px;
  font-size: 11px;
  font-weight: 700;
  color: var(--brand-1);
  background: #fff;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 6px;
}

.citation-main {
  min-width: 0;
  flex: 1;
}

.citation-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}

.citation-doc {
  max-width: 220px;
  font-weight: 600;
  color: var(--text-main);
}

.citation-tag {
  padding: 1px 8px;
  font-size: 11px;
  color: var(--text-sub);
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 999px;
}

.citation-tag.is-kb {
  color: var(--brand-2);
  border-color: var(--el-color-primary-light-7);
  background: #faf8ff;
}

.citation-score {
  margin-left: auto;
  font-size: 11px;
  color: var(--brand-2);
  font-weight: 600;
}

.citation-preview {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
}

.ellipsis-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.bubble-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 768px) {
  .bubble-body {
    max-width: calc(100% - 40px);
  }

  .bubble-avatar {
    width: 30px;
    height: 30px;
    border-radius: 10px;
  }
}
</style>
