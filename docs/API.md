# 接口契约（前后端唯一约定）

> 后端地址：`http://127.0.0.1:8000`，所有接口前缀 `/api`。
> 前端开发环境通过 Vite 代理 `/api` 到后端。
> 所有页面文案、提示词均为中文。

## 1. 统一响应结构

除流式接口外，所有接口返回：

```json
{ "code": 0, "message": "ok", "data": {} }
```

- `code = 0` 表示成功；非 0 表示业务/HTTP 错误（与 HTTP 状态码一致，如 400、401、404、500）。
- 校验错误（422）同样返回该结构，`data.detail` 为字段错误列表。
- 鉴权失败返回 HTTP 401，`message` 形如 `登录已过期，请重新登录`。

## 2. 鉴权

除 `/api/auth/captcha`、`/api/auth/register`、`/api/auth/login` 外，所有接口都需要请求头：

```
Authorization: Bearer <access_token>
```

### 2.1 获取图形验证码

`GET /api/auth/captcha`

```json
{ "code": 0, "message": "ok",
  "data": { "captcha_id": "8f2c...", "image": "data:image/png;base64,iVBORw0..." } }
```

- 验证码为 4 位字符（数字+大写字母），5 分钟内有效，**使用一次即失效**。
- 前端点击图片可刷新。

### 2.2 注册

`POST /api/auth/register`

```json
{ "username": "zhangsan", "password": "abc12345",
  "confirm_password": "abc12345", "captcha_id": "8f2c...", "captcha_code": "3F9K" }
```

成功：

```json
{ "code": 0, "message": "注册成功", "data": { "id": 1, "username": "zhangsan" } }
```

错误场景（HTTP 400，`message` 中文说明）：`两次输入的密码不一致`、`验证码错误或已过期`、`该用户名已被注册`。

### 2.3 登录

`POST /api/auth/login`

```json
{ "username": "zhangsan", "password": "abc12345", "captcha_id": "8f2c...", "captcha_code": "3F9K" }
```

成功：

```json
{ "code": 0, "message": "登录成功",
  "data": { "access_token": "eyJhbGci...", "token_type": "bearer",
            "user": { "id": 1, "username": "zhangsan" } } }
```

### 2.4 当前用户

`GET /api/auth/me` → `data: { "id": 1, "username": "zhangsan" }`

## 3. 知识库

### 3.1 知识库列表

`GET /api/kb/`

```json
{ "code": 0, "message": "ok", "data": [
  { "id": 1, "name": "产品手册", "description": "产品说明书合集",
    "doc_count": 3, "chunk_count": 128, "created_at": "2026-07-10 10:00:00" }
] }
```

### 3.2 创建知识库

`POST /api/kb/`  body `{ "name": "产品手册", "description": "可选" }` → `data` 为单个知识库对象。

### 3.3 修改知识库

`PUT /api/kb/{kb_id}`  body `{ "name": "新名称", "description": "新描述" }` → `data` 为知识库对象。

### 3.4 删除知识库

`DELETE /api/kb/{kb_id}` → `data: { "deleted": true }`（同时删除该库文档、分块与向量）

## 4. 文档

### 4.1 文档列表

`GET /api/kb/{kb_id}/documents`

```json
{ "code": 0, "message": "ok", "data": [
  { "id": 12, "kb_id": 1, "filename": "产品手册.md", "file_type": "md", "size": 20480,
    "status": "success", "chunk_count": 42, "chunk_size": 500, "chunk_overlap": 50,
    "retrieval_mode": "hybrid", "error_message": null,
    "created_at": "2026-07-10 10:00:00" }
] }
```

`status` 取值：`pending`（排队中）、`parsing`（解析中）、`success`（已完成）、`failed`（失败，见 `error_message`）。

### 4.2 上传并解析文档

`POST /api/kb/{kb_id}/documents`（`multipart/form-data`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file` | File | 支持 pdf、ppt/pptx、md、markdown、txt、png/jpg/jpeg/bmp/webp、docx |
| `chunk_size` | int | 文本切块大小，100~2000，默认 500 |
| `chunk_overlap` | int | 重叠大小，0 ≤ overlap < chunk_size，默认 50 |
| `retrieval_mode` | string | `dense` 稠密检索 / `hybrid` 混合检索，默认 `hybrid` |

返回 `data` 为文档对象（`status=pending`），后端在后台异步解析、切块、向量化；前端用 4.3 轮询进度。

### 4.3 解析进度

`GET /api/kb/documents/{doc_id}/status`

```json
{ "code": 0, "message": "ok",
  "data": { "id": 12, "status": "parsing", "chunk_count": 0, "error_message": null } }
```

### 4.4 重新解析

`POST /api/kb/documents/{doc_id}/reparse`（沿用原切块参数，先清空旧分块与向量）→ `data` 为文档对象。

### 4.5 删除文档

`DELETE /api/kb/documents/{doc_id}` → `data: { "deleted": true }`

## 5. 分块预览 / 编辑 / 删除

### 5.1 分块分页列表

`GET /api/kb/documents/{doc_id}/chunks?page=1&page_size=10&keyword=可选关键字`

```json
{ "code": 0, "message": "ok",
  "data": { "total": 42, "page": 1, "page_size": 10, "items": [
    { "id": 301, "chunk_index": 0, "content": "……", "page_no": 1,
      "enabled": true, "created_at": "2026-07-10 10:00:00" }
  ] } }
```

### 5.2 编辑分块

`PUT /api/kb/chunks/{chunk_id}`  body `{ "content": "修改后的文本" }` → `data` 为分块对象。
编辑后会**重新向量化**并更新 Milvus 中的对应向量。

### 5.3 删除分块

`DELETE /api/kb/chunks/{chunk_id}` → `data: { "deleted": true }`

### 5.4 启停分块

`PUT /api/kb/chunks/{chunk_id}/enabled` body `{ "enabled": false }` → `data` 为分块对象；
`enabled=false` 的分块不参与检索。

## 6. 对话

### 6.1 可选模型与默认参数

`GET /api/chat/models`

```json
{ "code": 0, "message": "ok",
  "data": { "models": [
      { "value": "deepseek-chat", "label": "DeepSeek-Chat", "description": "通用对话模型（V3），响应快，适合绝大多数问答" },
      { "value": "deepseek-reasoner", "label": "DeepSeek-Reasoner", "description": "推理模型（R1），会先思考再作答，适合复杂推理问题" }
    ],
    "defaults": { "model": "deepseek-chat", "temperature": 0.3, "top_p": 0.8,
                  "max_tokens": 2048, "history_rounds": 5, "retrieval_mode": "hybrid" } } }
```

- 模型列表来自 `config.yaml -> llm.models`，默认 `deepseek-chat`。
- 传入了不在列表中的 `model` → HTTP 400，`message` 形如 `不支持的大模型「xxx」，可选：deepseek-chat、deepseek-reasoner`。
- 选择 `deepseek-reasoner` 时后端会自动省略 `temperature` / `top_p`（该模型不支持采样参数），并且只把最终答案流式下发给前端。

### 6.2 会话列表

`GET /api/chat/sessions`

```json
{ "code": 0, "message": "ok", "data": [
  { "id": 7, "name": "新产品咨询", "kb_ids": [1, 2], "kb_names": ["产品手册"],
    "model": "deepseek-chat", "temperature": 0.3, "top_p": 0.8, "max_tokens": 2048,
    "history_rounds": 5, "retrieval_mode": "hybrid",
    "created_at": "2026-07-10 10:00:00", "updated_at": "2026-07-10 10:05:00" }
] }
```

### 6.3 新建会话

`POST /api/chat/sessions`

```json
{ "name": "新产品咨询", "kb_ids": [1, 2], "model": "deepseek-chat",
  "temperature": 0.3, "top_p": 0.8, "max_tokens": 2048,
  "history_rounds": 5, "retrieval_mode": "hybrid" }
```

`name` 可省略（默认 `新对话`）。`data` 为会话对象。

### 6.4 更新会话

`PUT /api/chat/sessions/{session_id}`，body 同上（字段均可选）→ `data` 为会话对象。

### 6.5 删除会话

`DELETE /api/chat/sessions/{session_id}` → `data: { "deleted": true }`

### 6.6 会话消息

`GET /api/chat/sessions/{session_id}/messages`

```json
{ "code": 0, "message": "ok", "data": [
  { "id": 21, "role": "user", "content": "产品的保修期是多久？", "citations": [],
    "created_at": "2026-07-10 10:05:00" },
  { "id": 22, "role": "assistant", "content": "根据【产品手册】……",
    "citations": [ { "index": 1, "chunk_id": 301, "doc_id": 12, "doc_name": "产品手册.md",
                     "kb_id": 1, "kb_name": "产品手册", "page_no": 1, "score": 0.82 } ],
    "created_at": "2026-07-10 10:05:02" }
] }
```

### 6.7 流式问答（SSE）

`POST /api/chat/stream`，请求体：

```json
{ "session_id": 7, "question": "产品的保修期是多久？", "kb_ids": [1, 2],
  "model": "deepseek-chat", "temperature": 0.3, "top_p": 0.8, "max_tokens": 2048,
  "history_rounds": 5, "retrieval_mode": "hybrid" }
```

- `session_id` 必填；`kb_ids`/`model` 及其他参数可选，缺省使用会话已保存的值。
- 响应为 `text/event-stream`（前端用 `fetch` + `ReadableStream` 解析，`Accept: text/event-stream`）。
- 事件顺序：

```
event: start
data: {"session_id":7,"user_message_id":21,"assistant_message_id":22}

event: retrieval
data: {"chunks":[{"chunk_id":301,"doc_name":"产品手册.md","kb_name":"产品手册","page_no":1,"score":0.82,"preview":"……"}]}

event: delta
data: {"content":"根据"}

event: delta
data: {"content":"【产品手册】……"}

event: done
data: {"assistant_message_id":22,"answer":"完整答案","finish_reason":"stop"}

event: error
data: {"message":"大模型调用失败：……"}
```

- 前端必须以 `done` 或 `error` 作为结束标志；`delta` 累积为最终答案。
- 若会话不存在/不属于当前用户 → HTTP 404；无可用知识库分块时仍会正常回答，并提示未检索到相关内容。

## 7. 健康检查

`GET /api/health` → `data: { "status": "ok", "mysql": "ok|error", "milvus": "ok|error|memory",
"llm_provider": "deepseek", "llm_model": "deepseek-chat", "llm_configured": true,
"embedding": "dashscope", "embedding_configured": true }`
