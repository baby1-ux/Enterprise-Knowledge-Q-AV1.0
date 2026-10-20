import { buildApiUrl, getToken, handleUnauthorized } from './request'

/**
 * SSE 流式问答（对应 docs/API.md 6.7）
 *
 * 协议：text/event-stream，事件按 start → retrieval → delta(多次) → done | error 顺序下发。
 * 解析要点：
 * 1. 跨网络分片粘包：使用缓冲区 + '\n\n' 分隔符切分事件块；
 * 2. 一个事件块内可能包含多行 data:，按规范用 '\n' 拼接；
 * 3. 兼容 \r\n 换行、忽略以 ':' 开头的注释行；
 * 4. done / error 为终止标志，收到后主动取消读取；
 * 5. 通过 AbortController 支持“停止生成”。
 */

/**
 * @param {object} payload 请求体 { session_id, question, kb_ids?, model?, temperature?, top_p?, max_tokens?, history_rounds?, retrieval_mode? }
 * @param {object} handlers 事件回调
 * @param {(data: object) => void} [handlers.onStart] 收到 start
 * @param {(data: object) => void} [handlers.onRetrieval] 收到 retrieval（命中分块）
 * @param {(content: string, data: object) => void} [handlers.onDelta] 收到一段增量文本
 * @param {(data: object) => void} [handlers.onDone] 收到 done（正常结束）
 * @param {(message: string, data: object) => void} [handlers.onError] 收到 error 或异常结束
 * @param {AbortSignal} [handlers.signal] 中断信号
 * @returns {Promise<{ aborted: boolean, finished: boolean }>}
 */
export async function streamChat(payload, handlers = {}) {
  const { onStart, onRetrieval, onDelta, onDone, onError, signal } = handlers

  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream'
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(buildApiUrl('/chat/stream'), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new Error('网络异常，无法连接问答服务，请确认后端服务已启动')
  }

  // 鉴权失败：走统一的登录失效处理
  if (response.status === 401) {
    await handleUnauthorized()
    throw new Error('登录已过期，请重新登录')
  }

  // 非流式错误（如 404 会话不存在、500 内部错误）
  if (!response.ok) {
    let message = `问答请求失败（HTTP ${response.status}）`
    try {
      const text = await response.text()
      if (text) {
        const parsed = JSON.parse(text)
        if (parsed?.message) message = parsed.message
      }
    } catch {
      // 响应体不可解析时保留默认提示
    }
    throw new Error(message)
  }

  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应，请更换浏览器')
  }

  /**
   * 解析单个事件块：返回 { event, data }
   * 支持 `event: xxx` 与多行 `data: yyy`
   */
  const parseBlock = (block) => {
    let event = 'message'
    const dataLines = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue // 空行 / 注释行
      const colonIndex = line.indexOf(':')
      const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
      let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
      if (value.startsWith(' ')) value = value.slice(1) // 规范：冒号后只去掉一个空格
      if (field === 'event') event = value.trim()
      else if (field === 'data') dataLines.push(value)
    }
    return { event, data: dataLines.join('\n') }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finished = false

  // 分发一个事件块
  const dispatch = (block) => {
    if (finished) return
    const { event, data } = parseBlock(block)
    if (!event && !data) return

    // 兼容 [DONE] 结束标记
    if (data && data.trim() === '[DONE]') {
      finished = true
      onDone?.({}, {})
      return
    }

    let parsed = null
    if (data) {
      try {
        parsed = JSON.parse(data)
      } catch {
        parsed = { raw: data }
      }
    }

    switch (event) {
      case 'start':
        onStart?.(parsed || {})
        break
      case 'retrieval':
        onRetrieval?.(parsed || {})
        break
      case 'delta': {
        const content = parsed?.content
        if (typeof content === 'string' && content) onDelta?.(content, parsed)
        break
      }
      case 'done':
        finished = true
        onDone?.(parsed || {}, parsed || {})
        break
      case 'error':
        finished = true
        onError?.(parsed?.message || '大模型调用失败，请稍后重试', parsed || {})
        break
      default:
        // 未知事件（如 ping / heartbeat）直接忽略
        break
    }
  }

  try {
    while (!finished) {
      const { value, done } = await reader.read()
      if (done) break
      // 统一换行符后累加到缓冲区，解决跨 chunk 粘包
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1 && !finished) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        dispatch(block)
        boundary = buffer.indexOf('\n\n')
      }
    }

    // 流结束但缓冲区仍有残留（服务端未以空行结尾）
    if (!finished && buffer.trim()) dispatch(buffer)
    buffer = ''
  } catch (error) {
    if (error?.name === 'AbortError' || signal?.aborted) {
      // 用户主动停止生成：静默释放连接
      try {
        await reader.cancel()
      } catch {
        // 连接已关闭，忽略
      }
      throw error?.name === 'AbortError' ? error : Object.assign(new Error('已停止生成'), { name: 'AbortError' })
    }
    throw error
  } finally {
    try {
      decoder.decode()
    } catch {
      // 忽略解码收尾异常
    }
  }

  // 未收到 done / error 就断开连接：提示前端做中断处理
  if (!finished && !signal?.aborted) {
    onError?.('服务端连接意外中断，答案可能不完整，请重试')
  }

  return { aborted: !!signal?.aborted, finished }
}

export default streamChat
