<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import KbSelector from '@/components/KbSelector.vue'
import ParamDrawer from '@/components/ParamDrawer.vue'
import StatsCards from '@/components/StatsCards.vue'
import { createSession, deleteSession, exportSession, fetchChatModels, feedbackMessage, listSessionMessages, listSessions, updateSession } from '@/api/chat'
import { streamChat } from '@/api/stream'

/* ------------------------------ 基础状态 ------------------------------ */

// 后端未返回默认参数时的兜底值
const FALLBACK_PARAMS = {
  model: '',
  temperature: 0.3,
  top_p: 0.8,
  max_tokens: 2048,
  history_rounds: 5,
  retrieval_mode: 'hybrid'
}

const sessions = ref([])
const sessionsLoading = ref(true)
const models = ref([])
const defaults = reactive({ ...FALLBACK_PARAMS })

const currentSessionId = ref(null)
const messages = ref([])
const messagesLoading = ref(false)
const kbIds = ref([])

const question = ref('')
const sending = ref(false)
const streaming = ref(false)
const savingParams = ref(false)

const drawerVisible = ref(false)
const sessionPanelOpen = ref(false)
const listRef = ref(null)

// 用于中断流式生成的控制器
let abortController = null

// 空状态示例问题
const sampleQuestions = [
  '请概述知识库中的主要内容',
  '文档里提到的保修政策是怎样的？',
  '帮我总结一下产品的核心卖点'
]

/* ------------------------------ 派生状态 ------------------------------ */

const currentSession = computed(() => sessions.value.find((item) => item.id === currentSessionId.value) || null)

/** 当前会话的推理参数（未创建会话时用后端默认值） */
const currentParams = computed(() => {
  const session = currentSession.value
  if (!session) return { ...defaults }
  return {
    model: session.model || defaults.model,
    temperature: Number(session.temperature ?? defaults.temperature),
    top_p: Number(session.top_p ?? defaults.top_p),
    max_tokens: Number(session.max_tokens ?? defaults.max_tokens),
    history_rounds: Number(session.history_rounds ?? defaults.history_rounds),
    retrieval_mode: session.retrieval_mode || defaults.retrieval_mode
  }
})

/* ------------------------------ 数据加载 ------------------------------ */

/** 拉取可选模型与默认参数 */
async function loadModels() {
  try {
    const data = await fetchChatModels()
    models.value = Array.isArray(data?.models) ? data.models : []
    Object.assign(defaults, FALLBACK_PARAMS, data?.defaults || {})
    if (!defaults.model && models.value.length) defaults.model = models.value[0].value
  } catch (error) {
    ElMessage.error(error?.message || '模型列表加载失败')
  }
}

/** 拉取会话列表，并按需选中会话 */
async function loadSessions(preferredId = null) {
  sessionsLoading.value = true
  try {
    const data = await listSessions()
    sessions.value = Array.isArray(data) ? data : []

    const targetId = preferredId ?? currentSessionId.value
    const exists = sessions.value.some((item) => item.id === targetId)
    const nextId = exists ? targetId : sessions.value[0]?.id ?? null

    if (nextId !== currentSessionId.value) {
      currentSessionId.value = nextId
      syncKbFromSession()
      await loadMessages(nextId)
    } else if (!nextId) {
      messages.value = []
      kbIds.value = []
    }
  } catch (error) {
    ElMessage.error(error?.message || '会话列表加载失败')
  } finally {
    sessionsLoading.value = false
  }
}

/** 拉取指定会话的历史消息 */
async function loadMessages(sessionId) {
  if (!sessionId) {
    messages.value = []
    return
  }
  messagesLoading.value = true
  try {
    const data = await listSessionMessages(sessionId)
    messages.value = (Array.isArray(data) ? data : []).map((item) => ({
      ...item,
      citations: Array.isArray(item.citations) ? item.citations : [],
      streaming: false
    }))
    scrollToBottom(true)
  } catch (error) {
    messages.value = []
    ElMessage.error(error?.message || '会话消息加载失败')
  } finally {
    messagesLoading.value = false
  }
}

/** 用当前会话已保存的知识库回填顶部多选框 */
function syncKbFromSession() {
  const session = currentSession.value
  kbIds.value = Array.isArray(session?.kb_ids) ? [...session.kb_ids] : []
}

/** 消息反馈（赞 / 踩 / 取消） */
async function handleFeedback({ id, feedback }) {
  const target = messages.value.find((item) => (item.message_id || item.id) === id)
  if (!target) return
  try {
    const updated = await feedbackMessage(id, feedback)
    target.feedback = updated?.feedback ?? null
  } catch (error) {
    ElMessage.error(error?.message || '反馈提交失败')
  }
}

/** 导出当前会话为 Markdown 文件 */
async function handleExport() {
  if (!currentSessionId.value || !messages.value.length) return
  try {
    await exportSession(currentSessionId.value, currentSession.value?.name || '对话记录')
    ElMessage.success('对话已导出为 Markdown 文件')
  } catch (error) {
    ElMessage.error(error?.message || '导出失败，请稍后重试')
  }
}

/** 局部更新列表中的会话对象 */
function patchSession(sessionId, patch) {
  const index = sessions.value.findIndex((item) => item.id === sessionId)
  if (index !== -1) sessions.value[index] = { ...sessions.value[index], ...patch }
}

/** 组装推理参数请求体 */
function buildParamsPayload() {
  const params = currentParams.value
  return {
    model: params.model,
    temperature: params.temperature,
    top_p: params.top_p,
    max_tokens: params.max_tokens,
    history_rounds: params.history_rounds,
    retrieval_mode: params.retrieval_mode
  }
}

/* ------------------------------ 会话操作 ------------------------------ */

/** 新建会话（支持自定义名称） */
async function handleCreateSession() {
  let name = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入新会话的名称', '新建会话', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputValue: '新对话',
      inputPlaceholder: '例如：产品保修政策咨询',
      inputValidator: (val) => (val && val.trim() ? true : '会话名称不能为空')
    })
    name = value.trim()
  } catch {
    return // 用户取消
  }
  await doCreateSession(name)
}

/** 真正创建会话（新建按钮与首次发送共用） */
async function doCreateSession(name) {
  try {
    const created = await createSession({ name, kb_ids: kbIds.value, ...buildParamsPayload() })
    if (!created?.id) {
      ElMessage.error('新建会话失败，请稍后重试')
      return null
    }
    sessions.value = [created, ...sessions.value]
    currentSessionId.value = created.id
    kbIds.value = Array.isArray(created.kb_ids) ? [...created.kb_ids] : kbIds.value
    messages.value = []
    sessionPanelOpen.value = false
    return created
  } catch (error) {
    ElMessage.error(error?.message || '新建会话失败')
    return null
  }
}

/** 切换会话 */
async function selectSession(sessionId) {
  sessionPanelOpen.value = false
  if (sessionId === currentSessionId.value) return
  if (streaming.value) stopGenerating(true)
  currentSessionId.value = sessionId
  syncKbFromSession()
  await loadMessages(sessionId)
}

/** 重命名会话（双击会话项或菜单触发） */
async function handleRenameSession(session) {
  let name = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: session.name,
      inputValidator: (val) => (val && val.trim() ? true : '会话名称不能为空')
    })
    name = value.trim()
  } catch {
    return
  }
  if (name === session.name) return

  try {
    const updated = await updateSession(session.id, { name })
    patchSession(session.id, { name: updated?.name || name })
    ElMessage.success('会话名称已更新')
  } catch (error) {
    ElMessage.error(error?.message || '重命名失败')
  }
}

/** 删除会话 */
async function handleDeleteSession(session) {
  try {
    await ElMessageBox.confirm(`确定删除会话「${session.name}」吗？删除后不可恢复。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  try {
    await deleteSession(session.id)
    ElMessage.success('会话已删除')
    if (streaming.value && currentSessionId.value === session.id) stopGenerating(true)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (currentSessionId.value === session.id) {
      const next = sessions.value[0] || null
      currentSessionId.value = next?.id ?? null
      syncKbFromSession()
      if (next) await loadMessages(next.id)
      else messages.value = []
    }
  } catch (error) {
    ElMessage.error(error?.message || '删除会话失败')
  }
}

/** 会话项下拉菜单 */
function handleSessionCommand(command, session) {
  if (command === 'rename') handleRenameSession(session)
  else if (command === 'delete') handleDeleteSession(session)
}

/* ------------------------------ 参数与知识库 ------------------------------ */

/** 顶部知识库多选变化：写入会话 */
async function handleKbChange(ids) {
  if (!currentSessionId.value) return
  try {
    const updated = await updateSession(currentSessionId.value, { kb_ids: ids })
    patchSession(currentSessionId.value, {
      kb_ids: Array.isArray(updated?.kb_ids) ? updated.kb_ids : ids,
      kb_names: Array.isArray(updated?.kb_names) ? updated.kb_names : []
    })
  } catch (error) {
    ElMessage.error(error?.message || '知识库选择保存失败')
  }
}

/** 参数抽屉保存 */
async function handleSaveParams(nextParams) {
  if (!currentSessionId.value) {
    // 无会话时：仅更新本地默认参数，新建会话时自动带上
    Object.assign(defaults, nextParams)
    drawerVisible.value = false
    ElMessage.success('参数已应用，将在新建会话时生效')
    return
  }

  savingParams.value = true
  try {
    const updated = await updateSession(currentSessionId.value, nextParams)
    patchSession(currentSessionId.value, { ...nextParams, ...(updated || {}) })
    drawerVisible.value = false
    ElMessage.success('参数已保存到当前会话')
  } catch (error) {
    ElMessage.error(error?.message || '参数保存失败')
  } finally {
    savingParams.value = false
  }
}

/* ------------------------------ 发送与流式回答 ------------------------------ */

/** 将检索分块转换为引用来源结构 */
function mapCitations(chunks) {
  if (!Array.isArray(chunks)) return []
  return chunks.map((chunk, index) => ({
    index: chunk.index ?? index + 1,
    chunk_id: chunk.chunk_id,
    doc_id: chunk.doc_id,
    doc_name: chunk.doc_name,
    kb_id: chunk.kb_id,
    kb_name: chunk.kb_name,
    page_no: chunk.page_no,
    score: chunk.score,
    preview: chunk.preview
  }))
}

/** 发送问题并接收流式回答 */
async function handleSend() {
  const text = question.value.trim()
  if (!text) {
    ElMessage.warning('请输入你的问题')
    return
  }
  if (streaming.value) return

  // 没有会话时自动创建一个，保证对话链路连续
  let sessionId = currentSessionId.value
  if (!sessionId) {
    const created = await doCreateSession('新对话')
    if (!created) return
    sessionId = created.id
  }

  const payload = {
    session_id: sessionId,
    question: text,
    kb_ids: kbIds.value,
    ...buildParamsPayload()
  }

  question.value = ''
  sending.value = true
  streaming.value = true

  // 先落地用户消息与助手占位气泡，视觉上立即响应
  messages.value.push({
    id: `local-user-${Date.now()}`,
    role: 'user',
    content: text,
    citations: [],
    created_at: ''
  })
  const assistant = reactive({
    id: `local-assistant-${Date.now()}`,
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
    error: '',
    stopped: false,
    finish_reason: ''
  })
  messages.value.push(assistant)
  scrollToBottom(true)

  abortController = new AbortController()

  try {
    await streamChat(payload, {
      signal: abortController.signal,
      onStart: (data) => {
        // 保留稳定的本地 key，服务端消息 id 单独存放，避免气泡重挂载
        if (data?.assistant_message_id) assistant.message_id = data.assistant_message_id
      },
      onRetrieval: (data) => {
        assistant.citations = mapCitations(data?.chunks)
      },
      onDelta: (delta) => {
        assistant.content += delta
        scrollToBottom()
      },
      onDone: (data) => {
        if (typeof data?.answer === 'string' && data.answer) assistant.content = data.answer
        assistant.finish_reason = data?.finish_reason || ''
      },
      onError: (message) => {
        assistant.error = message || '大模型调用失败，请稍后重试'
      }
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      assistant.stopped = true
    } else {
      assistant.error = error?.message || '生成失败，请稍后重试'
      ElMessage.error(assistant.error)
    }
  } finally {
    assistant.streaming = false
    streaming.value = false
    sending.value = false
    abortController = null
    scrollToBottom()
    await refreshSessionsSilently()
  }
}

/** 停止生成：中断 fetch 流 */
function stopGenerating(silent = false) {
  if (!abortController) return
  abortController.abort()
  if (!silent) ElMessage.info('已停止生成')
}

/** 后台刷新会话列表（更新名称与时间，不打断当前视图） */
async function refreshSessionsSilently() {
  try {
    const data = await listSessions()
    if (!Array.isArray(data)) return
    sessions.value = data
    if (currentSessionId.value && !data.some((item) => item.id === currentSessionId.value)) {
      currentSessionId.value = data[0]?.id ?? null
    }
  } catch {
    // 静默失败：不影响对话
  }
}

/* ------------------------------ 交互细节 ------------------------------ */

/** 滚动到底部（生成过程中自动跟随） */
function scrollToBottom(force = false) {
  nextTick(() => {
    const el = listRef.value
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    if (force || distance < 140) el.scrollTop = el.scrollHeight
  })
}

/** Enter 发送 / Shift + Enter 换行（兼容中文输入法合成） */
function handleKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing) return
  event.preventDefault()
  if (!streaming.value) handleSend()
}

/** 点击示例问题填入输入框 */
function fillSample(text) {
  question.value = text
}

/** 会话时间简写：2026-07-10 10:05:00 → 07-10 10:05 */
function formatShortTime(value) {
  if (!value) return ''
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
  return match ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : String(value)
}

/* ------------------------------ 生命周期 ------------------------------ */

onMounted(async () => {
  await loadModels()
  await loadSessions()
})

onBeforeUnmount(() => {
  stopGenerating(true)
})
</script>

<template>
  <div class="chat-page" :class="{ 'is-param-open': drawerVisible }">
    <!-- 左侧会话列表（窄屏时收纳为抽屉） -->
    <aside class="session-panel" :class="{ 'is-open': sessionPanelOpen }">
      <div class="session-head">
        <span class="session-title">我的会话</span>
        <button type="button" class="session-new" title="新建会话" @click="handleCreateSession">＋</button>
      </div>

      <div class="session-list">
        <template v-if="sessionsLoading">
          <div v-for="index in 4" :key="`sk-${index}`" class="session-skeleton skeleton-block"></div>
        </template>
        <p v-else-if="!sessions.length" class="session-empty">
          还没有会话，<br />点击右上角「＋」新建一个吧
        </p>
        <template v-else>
          <div
            v-for="item in sessions"
            :key="item.id"
            class="session-item"
            :class="{ 'is-active': item.id === currentSessionId }"
            @click="selectSession(item.id)"
            @dblclick="handleRenameSession(item)"
          >
            <div class="session-item-main">
              <span class="session-item-name ellipsis" :title="item.name">{{ item.name }}</span>
              <span class="session-item-meta">{{ formatShortTime(item.updated_at) }}</span>
            </div>
            <el-dropdown
              trigger="click"
              placement="bottom-end"
              @click.stop
              @command="(command) => handleSessionCommand(command, item)"
            >
              <span class="session-item-more" title="更多操作" @click.stop>⋯</span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除会话</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
      </div>

      <div class="session-foot">
        <span class="session-foot-text">双击会话名可重命名</span>
      </div>
    </aside>

    <div v-if="sessionPanelOpen" class="session-mask" @click="sessionPanelOpen = false"></div>

    <!-- 右侧聊天区 -->
    <section class="chat-main">
      <header class="chat-toolbar">
        <button type="button" class="panel-toggle" title="会话列表" @click="sessionPanelOpen = !sessionPanelOpen">☰</button>

        <KbSelector v-model="kbIds" @change="handleKbChange" />

        <div class="toolbar-right">
          <el-tag v-if="!kbIds.length" type="warning" effect="light" round class="toolbar-warning">
            未选知识库
          </el-tag>
          <el-button class="param-btn" :disabled="!messages.length" title="导出当前对话为 Markdown 文件" @click="handleExport">
            导出对话
          </el-button>
          <el-button class="param-btn" @click="drawerVisible = true">
            <span class="param-icon">⚙</span> 参数设置
          </el-button>
        </div>
      </header>

      <div ref="listRef" class="chat-scroll">
        <!-- 消息加载骨架 -->
        <div v-if="messagesLoading" class="message-skeleton">
          <div v-for="index in 3" :key="`msg-sk-${index}`" class="skeleton-row">
            <span class="skeleton-avatar skeleton-block"></span>
            <span class="skeleton-content skeleton-block"></span>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!messages.length" class="chat-welcome">
          <div class="welcome-icon">✦</div>
          <h2 class="welcome-title">今天想了解点什么？</h2>
          <p class="welcome-sub">
            选择知识库后提问，回答会自动附带引用来源；未选择时仅依赖通用知识。
          </p>
          <div class="welcome-samples">
            <button v-for="sample in sampleQuestions" :key="sample" type="button" class="sample-chip" @click="fillSample(sample)">
              {{ sample }}
            </button>
          </div>
          <StatsCards class="welcome-stats" />
        </div>

        <!-- 消息列表 -->
        <div v-else class="message-list">
          <ChatBubble v-for="item in messages" :key="item.id" :message="item" @feedback="handleFeedback" />
        </div>
      </div>

      <!-- 输入区 -->
      <footer class="chat-composer">
        <div v-if="!kbIds.length" class="composer-hint">
          <span class="hint-dot"></span>
          未选择知识库，将仅依赖通用知识回答
        </div>

        <div class="composer-box">
          <el-input
            v-model="question"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            resize="none"
            maxlength="2000"
            placeholder="输入问题开始对话，Enter 发送，Shift + Enter 换行"
            class="composer-input"
            @keydown="handleKeydown"
          />
          <div class="composer-actions">
            <span class="composer-count">{{ question.length }} / 2000</span>
            <el-button v-if="streaming" class="stop-btn" @click="stopGenerating()">
              <span class="stop-dot"></span>停止生成
            </el-button>
            <el-button v-else type="primary" class="btn-gradient send-btn" :loading="sending" @click="handleSend">
              发送
            </el-button>
          </div>
        </div>
      </footer>
    </section>

    <!-- 参数设置抽屉 -->
    <ParamDrawer
      v-model="drawerVisible"
      :params="currentParams"
      :models="models"
      :defaults="defaults"
      :saving="savingParams"
      @save="handleSaveParams"
    />
  </div>
</template>

<style scoped>
.chat-page {
  position: relative;
  display: flex;
  flex: 1;
  height: calc(100dvh - var(--header-height));
  min-height: 0;
  overflow: hidden;
}

/* ---------------- 会话侧栏 ---------------- */
.session-panel {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 252px;
  min-height: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-color);
  backdrop-filter: blur(12px);
}

.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 10px;
}

.session-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--text-sub);
}

.session-new {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  cursor: pointer;
  background: var(--brand-gradient);
  border: 0;
  border-radius: 9px;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.28);
  transition: all var(--transition-fast);
}

.session-new:hover {
  transform: translateY(-1px) scale(1.06);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.36);
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-skeleton {
  height: 46px;
  border-radius: var(--radius-sm);
}

.session-empty {
  padding: 26px 12px;
  font-size: 12.5px;
  line-height: 1.9;
  text-align: center;
  color: var(--text-muted);
}

.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
  transition: all var(--transition-base);
}

.session-item:hover {
  background: #fff;
  border-color: var(--border-color);
  box-shadow: var(--shadow-xs);
  transform: translateX(2px);
}

.session-item.is-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12) 0%, rgba(139, 92, 246, 0.1) 100%);
  border-color: var(--el-color-primary-light-7);
}

.session-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.session-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-main);
}

.session-item.is-active .session-item-name {
  color: var(--brand-1);
  font-weight: 600;
}

.session-item-meta {
  font-size: 10.5px;
  color: var(--text-muted);
}

.session-item-more {
  flex-shrink: 0;
  padding: 0 4px;
  font-size: 14px;
  line-height: 1;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  outline: none;
  opacity: 0;
  transition: all var(--transition-fast);
}

.session-item:hover .session-item-more {
  opacity: 1;
}

.session-item-more:hover {
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.1);
}

.session-foot {
  padding: 10px 16px 12px;
  border-top: 1px solid var(--border-color);
}

.session-foot-text {
  font-size: 11px;
  color: var(--text-muted);
}

.session-mask {
  display: none;
}

/* ---------------- 聊天主区 ---------------- */
.chat-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  transition: margin-right var(--transition-base);
}

/* 参数面板打开时，聊天区左移，避免被面板遮挡 */
@media (min-width: 1024px) {
  .chat-page.is-param-open .chat-main {
    margin-right: 380px;
  }
}

.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: rgba(255, 255, 255, 0.72);
  border-bottom: 1px solid var(--border-color);
  backdrop-filter: blur(12px);
}

.panel-toggle {
  display: none;
  width: 32px;
  height: 32px;
  font-size: 15px;
  color: var(--text-sub);
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  cursor: pointer;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.toolbar-warning {
  animation: breathingGlow 2.4s ease-in-out infinite;
}

.param-btn {
  border-color: var(--el-color-primary-light-7);
  color: var(--brand-1);
  background: #fff;
}

.param-btn:hover {
  border-color: var(--brand-1);
  color: var(--brand-1);
  background: var(--el-color-primary-light-9);
}

.param-icon {
  margin-right: 4px;
  font-size: 13px;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 20px 8px;
  scroll-behavior: smooth;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
}

/* 加载骨架 */
.message-skeleton {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-width: 900px;
  margin: 0 auto;
}

.skeleton-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.skeleton-avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  flex-shrink: 0;
}

.skeleton-content {
  flex: 1;
  height: 74px;
  border-radius: var(--radius-md);
}

/* 空状态 */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  max-width: 620px;
  margin: 8vh auto 0;
  padding: 0 12px;
  text-align: center;
  animation: fadeSlideIn 0.5s both;
}

.welcome-icon {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin-bottom: 4px;
  font-size: 22px;
  color: #fff;
  background: var(--brand-gradient);
  background-size: 160% 160%;
  border-radius: 18px;
  box-shadow: var(--shadow-brand);
  animation: gradientFlow 6s ease infinite;
}

.welcome-title {
  font-size: 21px;
  font-weight: 700;
  color: var(--text-main);
}

.welcome-sub {
  max-width: 460px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-muted);
}

.welcome-samples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 12px;
}

.welcome-stats {
  width: min(680px, 100%);
  margin-top: 26px;
  text-align: left;
}

.sample-chip {
  padding: 8px 16px;
  font-size: 12.5px;
  color: var(--text-sub);
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: var(--shadow-xs);
  transition: all var(--transition-base);
}

.sample-chip:hover {
  color: var(--brand-1);
  border-color: var(--el-color-primary-light-5);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

/* 输入区 */
.chat-composer {
  padding: 10px 20px 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.85) 45%);
}

.composer-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  max-width: 900px;
  margin: 0 auto 8px;
  padding: 6px 12px;
  font-size: 12px;
  color: #a05a00;
  background: #fff8eb;
  border: 1px solid #ffe2b8;
  border-radius: 999px;
  animation: fadeIn 0.3s both;
}

.hint-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
}

.composer-box {
  position: relative;
  max-width: 900px;
  margin: 0 auto;
  padding: 10px 12px 8px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.composer-box:focus-within {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 14px 34px rgba(99, 102, 241, 0.18);
}

.composer-input :deep(.el-textarea__inner) {
  padding: 4px 2px;
  font-size: 14px;
  line-height: 1.7;
  border: 0;
  box-shadow: none;
  background: transparent;
}

.composer-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.composer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid var(--bg-muted);
}

.composer-count {
  font-size: 11px;
  color: var(--text-muted);
}

.send-btn {
  margin-left: auto;
  min-width: 88px;
  border-radius: 999px;
}

.stop-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  background: #fff5f6;
  border: 1px solid #ffd7dd;
  border-radius: 999px;
}

.stop-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--el-color-danger);
  animation: breathingGlow 1.4s ease-in-out infinite;
}

/* ---------------- 响应式：侧栏收纳为抽屉 ---------------- */
@media (max-width: 1023px) {
  .panel-toggle {
    display: grid;
    place-items: center;
  }

  .session-panel {
    position: fixed;
    top: var(--header-height);
    bottom: 0;
    left: 0;
    z-index: 2100;
    width: 280px;
    background: #fff;
    box-shadow: var(--shadow-lg);
    transform: translateX(-104%);
    transition: transform var(--transition-base);
  }

  .session-panel.is-open {
    transform: translateX(0);
  }

  .session-mask {
    display: block;
    position: fixed;
    inset: var(--header-height) 0 0 0;
    z-index: 2050;
    background: rgba(31, 34, 51, 0.28);
    backdrop-filter: blur(2px);
    animation: fadeIn 0.2s both;
  }

  .chat-scroll {
    padding: 18px 14px 6px;
  }

  .chat-toolbar {
    padding: 10px 14px;
  }

  .chat-composer {
    padding: 8px 12px 12px;
  }
}
</style>
