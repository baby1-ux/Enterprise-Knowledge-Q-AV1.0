# 企业内部知识问答系统（RAG）

基于 **企业自有内容知识库** 的检索增强问答系统：上传离线文档 → 自动解析切块 → 向量化入库 → 多知识库检索 → **DeepSeek 流式作答**，答案带引用来源。

- 场景价值：客服售后、产品手册、规章制度、培训资料等「企业内部知识多、查起来慢、答起来不一致」的问题，用一套可溯源的知识问答替代人工翻文档。
- 全栈实现：FastAPI + MySQL + Milvus + DeepSeek（后端）、Vue 3 + Vite + Element Plus（前端）、pytest（测试）。

> **模型分工**：对话生成使用 **DeepSeek**（`deepseek-chat` 默认，可选 `deepseek-reasoner`）；
> 文本向量化、重排与图片 OCR 使用 **DashScope**（DeepSeek 暂未提供向量化 / 多模态 OCR 接口）。
> 因此需要两个 Key：`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`（也可把 `embedding.provider` 改为 `local_bge_m3` 或 `hash` 免掉后者）。

---

## 一、核心能力

| 模块 | 能力 |
| --- | --- |
| 账号体系 | 注册（4 字段：账号/密码/确认密码/图形验证码）、登录（3 字段）、图形验证码（一次性、5 分钟有效）、JWT 登录态、**登录防爆破**（同一账号连续失败 5 次锁定 10 分钟，验证码错误不连坐） |
| 知识库 | 多知识库；**名称关键字搜索**；文档列表；删除级联清理分块与向量；每库默认检索方式 |
| 文档解析 | PDF、PPTX、Markdown、TXT、DOCX、图片（OCR）；按页/按标题保留来源位置；**批量上传**（单次最多 20 个，单文件失败不影响其它） |
| 切块 | 中文友好的句子级切块，可配置切块大小与重叠大小（100~2000 / 0 ≤ overlap < size） |
| 向量化 | 默认 DashScope `text-embedding-v4`（DeepSeek 无向量化接口）；可切本地 BGE-M3；离线哈希向量（免密钥演示） |
| 检索 | 稠密检索（HNSW + COSINE）与 **混合检索**（稠密 + Milvus BM25 稀疏，WeightedRanker 融合）；可选 Rerank 重排；可选查询改写 |
| 知识检索 | **跨库分块搜索**：按内容关键字检索用户名下全部（或指定）知识库的分块，结果可跳转文档 |
| 问答 | **DeepSeek** `deepseek-chat` 默认、`deepseek-reasoner` 可选，SSE 流式输出；支持温度 / topP / 最长输出 token / 历史对话轮数；多知识库同时检索 |
| 溯源 | 回答中的 `[1][2]` 与引用面板（文档名、页码、相似度、原文预览）一一对应 |
| 问答反馈 | 助手回答支持**点赞 / 点踩 / 取消**，反馈落库持久化 |
| 对话导出 | 一键导出会话为 **Markdown 文件**（含问答、引用来源清单与推理参数） |
| 统计面板 | **用量统计**：知识库 / 文档 / 分块 / 会话 / 消息 / 累计回答 / 今日回答（按用户隔离） |
| 知识维护 | 分块分页预览、关键字搜索、编辑（自动重新向量化）、启停（不参与检索）、删除 |
| 工程化 | YAML 集中配置 + `.env` 覆盖、控制台与文件双通道日志（按天滚动 + 错误单独留存）、统一响应结构、中文提示词与错误信息、**升级自动补列**（新增字段无需手工 ALTER TABLE） |

---

## 二、检索链路（RAG 流水线）

```
离线侧（知识入库）                              在线侧（问答生成）
─────────────────────────────                  ─────────────────────────────
上传文件 (PDF/PPT/MD/图片/DOCX/TXT)             用户问题
    │                                              │
    ├─ 解析器工厂按后缀路由                         ├─（可选）问题改写：LLM 扩展同义检索式
    │  pypdf / python-pptx / 标题切分 / OCR         ├─ 向量化（embed_query）
    ├─ 句子级切块（size + overlap）                 ├─ Milvus 检索
    ├─ 批量向量化（embed_documents）                │   · dense：HNSW + COSINE
    └─ 写入 Milvus：dense + content(BM25)          │   · hybrid：dense + sparse(BM25) → WeightedRanker
       MySQL 记录 document / chunk 元数据          ├─（可选）Rerank 重排（gte-rerank / 本地 BGE）
                                                   ├─ 阈值过滤 + TopK
                                                   ├─ 组装中文提示词（角色规则 + 参考资料[1..n] + 历史轮数）
                                                   ├─ DeepSeek 流式生成（SSE: start/retrieval/delta/done）
                                                   └─ 落库答案 + 引用信息，前端逐字渲染并可展开引用
```

对照 RAG 技术演进：本系统处于 **Advanced RAG** 阶段（查询改写、混合检索、重排、上下文控制、引用溯源），并保留向 Modular / Agentic RAG 扩展的接口（`Retriever`、`LLMClient`、`VectorStore` 均为可替换组件）。

---

## 三、目录结构

```
rag实战/
├── config.yaml                 # 主配置文件（数据库/向量库/模型/RAG 参数/OCR/验证码）
├── .env.example                # 环境变量样例（API Key、MySQL 密码、Milvus 地址）
├── docker-compose.yml          # MySQL 8 + Milvus 2.5（含 etcd / MinIO）
├── pyproject.toml              # 依赖与 pytest 配置
├── run.py                      # 后端启动脚本
├── docs/API.md                 # 前后端接口契约（唯一约定）
├── data/                       # 离线文档目录 + samples 样例文档
├── backend/app/
│   ├── main.py                 # FastAPI 入口：中间件、异常处理、路由、建表
│   ├── core/                   # 配置、日志、安全（密码/JWT）、验证码、统一异常
│   ├── db/                     # SQLAlchemy 模型与会话
│   ├── schemas/                # Pydantic 请求/响应契约
│   ├── api/                    # 依赖注入 + 路由（auth / kb / chat / system）
│   └── services/               # 解析、切块、向量化、向量库、检索、重排、提示词、LLM、业务
├── frontend/
│   └── src/                    # Vue3：views(6) + components(5) + api + stores + styles
├── scripts/
│   ├── check_keys.py           # 两个 API Key 连通性自检（向量化 + 对话 + 推理模型）
│   ├── smoke_e2e.py            # 端到端冒烟：建库→上传→解析入库→检索→流式问答→引用
│   ├── smoke_new_features.py   # 新功能冒烟：统计/批量上传/跨库搜索/反馈/导出（真实服务）
│   ├── dev_local.py            # 本地演示模式启动（SQLite + 内存向量库，无需 Docker）
│   ├── dev.ps1                 # 一键启动前后端（Windows PowerShell，支持 -Demo/-Install）
│   ├── clean_orphans.py        # 清理数据库已无记录的上传文件（--dry-run 预演）
│   └── ui_flow_check.py        # 前后端联调自检（经 Vite 代理跑完整业务流）
└── tests/                      # pytest 单元测试与接口测试（默认离线可跑）
```

---

## 四、快速开始

> 环境要求：Python ≥ 3.10（推荐 3.12/3.13）、Node ≥ 18、Docker（MySQL / Milvus）。

### 1. 启动 MySQL 与 Milvus

```bash
docker compose up -d          # 首次会拉取镜像
docker compose ps             # mysql / etcd / minio / milvus 均为 healthy
```

### 2. 安装后端依赖

```bash
uv sync --extra dev --no-install-project    # 本项目无可安装的 Python 包，跳过项目自身打包
# 或在已激活的 venv 中：pip install ".[dev]" --no-build-isolation
```

> Windows 下用 `.venv\Scripts\python.exe` 执行后续命令；Linux/macOS 用 `.venv/bin/python`。

### 3. 填写配置

```bash
copy .env.example .env        # Windows；Linux/macOS 用 cp
```

编辑 `config.yaml`（或 `.env`）中的关键项：

| 配置项 | 说明 |
| --- | --- |
| `llm.api_key` | **DeepSeek** API Key（也可用环境变量 `DEEPSEEK_API_KEY`） |
| `llm.base_url` | DeepSeek 兼容接口地址，默认 `https://api.deepseek.com/v1` |
| `llm.default_model` | 默认 `deepseek-chat`；`llm.models` 中同时提供 `deepseek-reasoner` |
| `embedding.api_key` / `embedding.base_url` | **DashScope** Key 与地址（向量化、重排、图片 OCR 共用，也可用 `DASHSCOPE_API_KEY`） |
| `mysql.*` | MySQL 连接信息（与 docker-compose 保持一致） |
| `milvus.host` / `milvus.port` | Milvus 地址，默认 `127.0.0.1:19530` |
| `embedding.provider` | `dashscope`（默认）/ `local_bge_m3` / `hash`（离线演示） |
| `milvus.provider` | `milvus`（默认）/ `memory`（无需 Milvus，本地演示与单测） |
| `rerank.enabled` | 是否开启重排（默认关闭） |
| `rag.chunk.*` / `rag.retrieval.*` | 默认切块与检索参数 |
| `captcha.debug_expose` | 仅调试用；生产请保持 `false` |

### 4. 启动后端

```bash
python run.py                 # http://127.0.0.1:8000/docs
```

首次启动会自动创建数据库、数据表、上传与日志目录。

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173（/api 代理到 8000）
```

### 6. 体验

1. 注册账号（需填图形验证码）→ 登录。
2. 「知识库」→ 新建知识库 → 进入文档列表 → 上传 `data/samples/` 下的样例文档（可设置切块大小 / 重叠 / 稠密或混合检索）。
3. 解析完成后进入「对话」→ 勾选知识库 → 提问，答案右侧「引用来源」可查看命中的原文分块。

---

## 五、接口

完整契约见 [`docs/API.md`](docs/API.md)，统一响应：

```json
{ "code": 0, "message": "ok", "data": {} }
```

主要接口分组：

| 分组 | 路径 |
| --- | --- |
| 鉴权 | `GET /api/auth/captcha`、`POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me` |
| 知识库 | `GET/POST /api/kb/`（支持 `?keyword=` 名称搜索）、`PUT/DELETE /api/kb/{id}` |
| 文档 | `GET/POST /api/kb/{id}/documents`、`POST /api/kb/{id}/documents/batch`（批量上传）、`GET /api/kb/documents/{id}/status`、`POST .../reparse`、`DELETE .../{id}` |
| 分块 | `GET /api/kb/documents/{id}/chunks`、`GET /api/kb/chunks/search`（跨库搜索）、`PUT/DELETE /api/kb/chunks/{id}`、`PUT /api/kb/chunks/{id}/enabled` |
| 对话 | `GET /api/chat/models`、`/api/chat/sessions...`、`POST /api/chat/stream`（SSE）、`GET /api/chat/sessions/{id}/export`（导出 Markdown）、`PUT /api/chat/messages/{id}/feedback`（赞/踩） |
| 系统 | `GET /api/health`、`GET /api/system/stats`（用量统计） |

SSE 事件：`start` → `retrieval` → `delta`… → `done`（异常为 `error`）。

---

## 六、测试

```bash
.venv\Scripts\python.exe -m pytest tests/ -v          # Windows
python -m pytest tests/ -v                            # 全部用例（SQLite + 内存向量库 + 假大模型）
python -m pytest tests/ -v -m "not integration"       # 排除集成用例
```

**最近一次实测结果：172 个用例，170 passed、2 skipped（集成用例默认跳过），耗时约 32s。**

上线前的真实链路自检（会真实调用接口，消耗额度）：

```bash
.venv\Scripts\python.exe scripts/check_keys.py    # 校验 DashScope 向量化 + DeepSeek 对话 + reasoner
.venv\Scripts\python.exe scripts/smoke_e2e.py     # 建库→上传→解析入库→检索→流式问答→引用（SQLite + 内存向量库）
.venv\Scripts\python.exe scripts/smoke_new_features.py  # 新功能全链路：统计/批量上传/跨库搜索/流式问答/反馈/导出（需真实服务）
```

> `smoke_new_features.py` 需要后端以 `captcha.debug_expose: true` 启动（脚本化登录要读取验证码明文，仅限本地调试）。

### 无 Docker 的本地演示模式

没有 MySQL / Milvus 时，可用演示模式跑通全流程（业务数据落 SQLite，向量落内存）：

```bash
# 终端 1：后端（内存向量库，进程重启后需重新上传文档）
.venv\Scripts\python.exe scripts/dev_local.py

# 终端 2：前端
cd frontend && npm run dev      # http://127.0.0.1:5173

# 终端 3（可选）：自动跑一遍「注册→登录→建库→上传→流式问答」，确认前后端联通
$env:RAG_DEMO_EXPOSE_CAPTCHA = "1"   # 需用该环境变量重启后端，脚本才能读到验证码明文
.venv\Scripts\python.exe scripts/ui_flow_check.py --base http://127.0.0.1:5173
```

测试覆盖：

| 文件 | 覆盖点 |
| --- | --- |
| `tests/test_security.py` | 密码哈希、JWT 签发/过期/非法密钥 |
| `tests/test_captcha.py` | 验证码生成、渲染、一次性校验、过期 |
| `tests/test_settings.py` | YAML 加载、环境变量展开（DeepSeek / DashScope 两套 Key）、占位 Key 识别、路径与连接串 |
| `tests/test_splitter.py` | 切块上限、重叠、页码保留、非法参数 |
| `tests/test_parsers.py` | Markdown / TXT / PPTX / 破损 PDF / 不支持类型 |
| `tests/test_prompt.py` | 中文提示词结构、上下文拼接与截断、历史顺序 |
| `tests/test_retrieval.py` | 向量化、内存向量库增删、检索、阈值、禁用分块 |
| `tests/test_auth_api.py` | 注册/登录/验证码一次性/鉴权异常/当前用户 |
| `tests/test_kb_api.py` | 知识库 CRUD、上传入库、分块分页/编辑/启停/删除、越权隔离 |
| `tests/test_chat_api.py` | 模型参数、会话 CRUD、SSE 事件顺序、历史轮数、引用来源、404/422 |
| `tests/test_llm_client.py` | DeepSeek 请求体构造、推理模型省略采样参数、Key 占位识别、模型列表 |
| `tests/test_feedback_export.py` | 消息点赞/点踩/取消、反馈边界（用户消息/非法值/越权）、会话导出 Markdown 内容 |
| `tests/test_login_throttle.py` | 登录连续失败锁定、成功重置计数、验证码错误不连坐、锁定过期恢复 |
| `tests/test_system_stats.py` | 统计接口空数据/使用后计数、鉴权、按用户隔离 |
| `tests/test_batch_upload_search.py` | 批量上传（全部成功/部分失败/超量/参数非法）、跨库分块搜索（范围/分页/隔离）、知识库名称搜索 |
| `tests/test_clean_orphans.py` | 孤儿文件识别、空目录清理（含 dry-run） |
| `tests/test_db_migration.py` | 旧库自动补列（数据不丢失）、重复初始化幂等 |
| `tests/test_integration_e2e.py` | 真实 MySQL + Milvus + DeepSeek + DashScope 全链路（`RAG_E2E=1` 时启用） |

离线联调小贴士：把 `embedding.provider` 设为 `hash`、`milvus.provider` 设为 `memory`，即使没有 API Key 与 Milvus 也能跑通上传→检索→流式问答（答案由大模型给出，需要 Key）。

### 端到端实测样例（真实 DashScope 向量化 + 真实 DeepSeek 回答）

上传 `data/samples/产品保修政策.md`（切块 300 / 重叠 50 / 混合检索）后提问「产品保修期是多久？延保怎么买？」：

```
[ingest] status=success chunks=6
[stream] 事件顺序=['start', 'retrieval', 'delta']... 末事件=done，增量 135 段
[citations] 命中 3 条：延保服务(0.71) / 保修期限(0.62) / 保修政策总述(0.58)
[answer] **保修期**：公司所有电子产品自购买之日起提供一年（12 个月）免费保修服务[2]。
         **延保购买方式**：可在购买产品后 30 天内购买「安心延保」服务，延长至两年，费用为售价的 5%[1]。
```

### 前后端联通实测（经 Vite 代理 5173 → 后端 8000）

```
[1/5] 注册成功   [2/5] 登录成功   [3/5] 上传解析：status=success chunks=6
[4/5] SSE 流式：事件=['start','retrieval','delta']…['done']，增量 128 段，首段耗时 4.17s
      给出 5 条引用（产品保修政策.md #1~#5）
[5/5] 消息持久化：['user', 'assistant']
```

说明流式响应可正常穿过 Vite 代理逐段到达浏览器（未被缓冲）。

---

## 七、日志

- 控制台 + `logs/rag_qa.log`（按天滚动，保留 14 天）+ `logs/rag_qa_error.log`（错误单独留存）。
- 关键链路均记录：文档上传/解析耗时/分块数、向量化批次、检索命中数与最高分、大模型调用参数、异常堆栈。

---

## 八、常见问题

1. **向量维度不一致**：`config.yaml` 修改 `embedding.dimension` 后，请更换 `milvus.collection` 名称或清空集合，否则启动检索时会提示维度不匹配。
2. **图片解析报 OCR 失败**：OCR 走 DashScope 云端 `qwen-vl-ocr`，需要 `parser.ocr.api_key`（或 `DASHSCOPE_API_KEY`）有效；如本地已装 tesseract，可将 `parser.ocr.provider` 改为 `pytesseract`。
3. **对话报错「未配置 DeepSeek API Key」**：填写 `config.yaml -> llm.api_key` 或环境变量 `DEEPSEEK_API_KEY`。
4. **选择 deepseek-reasoner 后温度参数无效**：推理模型不支持 `temperature` / `top_p`，后端会自动忽略（官方行为，不是 bug）。
5. **`.ppt` 无法解析**：请另存为 `.pptx`（python-pptx 不支持旧二进制格式）。
6. **回答提示「未在知识库中找到相关内容」**：确认对话页已勾选知识库、文档解析状态为「已完成」、分块未被停用。
7. **流式回答不输出**：检查 `DEEPSEEK_API_KEY` 是否正确（对话）+ `DASHSCOPE_API_KEY` 是否有效（向量化）；接口会以 `error` 事件返回中文原因。
8. **上传后解析失败提示未配置 DashScope Key**：向量化仍依赖 DashScope；如只用 DeepSeek 一个 Key，可把 `embedding.provider` 改为 `local_bge_m3`（需下载模型）或 `hash`（仅演示，语义检索能力弱）。
9. **登录提示「登录失败次数过多，账号已锁定」**：同一账号连续输错 5 次密码会锁定 10 分钟（`config.yaml -> app.login_max_attempts` / `app.login_lock_minutes` 可调整，重启服务也会立即解锁）；验证码输错不计入失败次数。
10. **升级后启动报「Unknown column」**：新版本启动时会自动为已有数据表补充新增列（如 `chat_messages.feedback`），一般无需手工处理；若自动补列失败，可按日志中的表名/列名手工执行 `ALTER TABLE`。

---

## 九、后续可扩展方向

- 结构化知识（表格问答、SQL Agent）、Graph RAG（实体关系图谱检索）
- 多轮检索决策（Agentic RAG：检索-反思-再检索）
- 权限隔离到知识库级共享、问答反馈闭环（点赞/纠错回流微调检索）
