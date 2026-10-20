# 企业内容知识问答系统 · 前端

基于 **Vue 3（`<script setup>` 组合式 API）+ Vite 5 + Vue Router 4 + Pinia 2 + Element Plus 2（中文语言包）** 实现的前端工程，
配套后端为同仓库的 FastAPI 服务，接口契约见 `../docs/API.md`。

## 一、功能页面

| 路由 | 页面 | 主要能力 |
| --- | --- | --- |
| `/login` | 登录页 | 账号、密码、图形验证码（点击图片刷新），回车提交 |
| `/register` | 注册页 | 账号、密码、确认密码、验证码；前端先校验两次密码一致 |
| `/chat` | 对话页 | 会话列表（新建/重命名/删除）、知识库多选、推理参数抽屉、流式回答与引用来源 |
| `/kb` | 知识库管理 | 卡片网格展示知识库，新建/编辑/删除，点击卡片进入文档列表 |
| `/kb/:kbId/documents` | 文档列表 | 上传解析（切块大小/重叠/检索方式）、状态轮询、重新解析、删除、进入分块预览 |
| `/kb/documents/:docId/chunks` | 分块预览 | 分页浏览、关键字搜索、编辑（字数统计）、删除、启用/停用 |

未登录访问需要登录的页面会跳转 `/login`；已登录访问 `/login`、`/register` 会跳转 `/chat`。

## 二、技术栈与依赖

- Vue 3 / Vite 5 / Vue Router 4 / Pinia 2
- Element Plus 2（中文语言包 `zh-cn`，主题色通过 CSS 变量覆盖为品牌紫 `#6366f1`）
- markdown-it（`html:false`、`linkify:true`）+ highlight.js 渲染助手回答
- 请求使用原生 `fetch` 封装（未引入 axios），SSE 使用 `fetch` + `ReadableStream` 解析

所有 `import` 的第三方包均已列在 `package.json` 的 `dependencies` / `devDependencies` 中。

## 三、目录结构

```
frontend/
├── index.html                # 入口 HTML
├── package.json              # 依赖与脚本
├── vite.config.js            # 别名 @ 与 /api 代理到 http://127.0.0.1:8000
├── .env.development          # VITE_API_BASE=/api
└── src/
    ├── main.js               # 应用入口（Pinia / Router / Element Plus 中文包）
    ├── App.vue               # 根组件
    ├── router/index.js       # 路由表与登录守卫
    ├── stores/auth.js        # 登录态（token + 用户信息，localStorage 持久化）
    ├── api/
    │   ├── request.js        # 统一请求封装：注入 Bearer、解包 {code,message,data}、401 跳登录
    │   ├── auth.js           # 验证码 / 注册 / 登录 / 当前用户
    │   ├── kb.js             # 知识库、文档、分块接口
    │   ├── chat.js           # 会话、消息、模型参数接口
    │   └── stream.js         # SSE 流式问答解析（start/retrieval/delta/done/error）
    ├── styles/main.css       # 主题变量、全局样式、Element Plus 主题覆盖、动效
    ├── layouts/MainLayout.vue# 顶部导航 + 主内容区
    ├── components/
    │   ├── CaptchaInput.vue   # 验证码输入 + 点击刷新
    │   ├── ChatBubble.vue     # 消息气泡 + markdown 渲染 + 引用来源折叠
    │   ├── ParamDrawer.vue    # 右侧推理参数抽屉
    │   ├── KbSelector.vue     # 知识库多选
    │   └── UploadDialog.vue   # 上传文档 + 切块参数配置
    └── views/
        ├── LoginView.vue
        ├── RegisterView.vue
        ├── ChatView.vue
        ├── KbManageView.vue
        ├── KbDocumentsView.vue
        └── KbChunksView.vue
```

## 四、启动方式

> 本工程仅提供代码与配置，尚未执行任何安装或构建命令（用户明确要求先不处理环境下载）。

1. 安装依赖（需要 Node.js 18+，推荐 20+）：

   ```bash
   cd frontend
   npm install
   ```

2. 先启动后端 FastAPI 服务，确认监听 `http://127.0.0.1:8000`（接口前缀 `/api`）。

3. 启动前端开发服务器：

   ```bash
   npm run dev
   ```

   默认地址：`http://127.0.0.1:5173`。

4. 构建生产包（可选）：

   ```bash
   npm run build
   npm run preview
   ```

### 接口地址说明

- 开发环境：`.env.development` 中 `VITE_API_BASE=/api`，由 `vite.config.js` 的 `server.proxy` 把 `/api` 转发到
  `http://127.0.0.1:8000`，因此无需处理跨域。
- 若部署到与后端不同的域名，可在 `.env.production` 中把 `VITE_API_BASE` 设为完整后端地址（需后端开启 CORS）。

## 五、关键实现说明

- **统一响应处理**：`api/request.js` 统一注入 `Authorization: Bearer <token>`，解包 `{ code, message, data }`，
  `code !== 0` 时抛出 `ApiError`（`message` 为后端中文提示，422 校验错误会拼接字段提示）；401 时清除登录态、提示并跳转登录页。
- **SSE 解析**：`api/stream.js` 使用缓冲区 + `\n\n` 切分事件块，支持跨 chunk 粘包、多行 `data:`、`\r\n` 换行、
  `[DONE]` 兼容，收到 `done`/`error` 立即终止；`AbortController` 支持「停止生成」。
- **流式渲染**：助手回答按 `delta` 增量写回消息对象，`markdown-it` 增量渲染，滚动跟随（距底部 140px 内自动吸底）。
- **参数抽屉**：自定义固定定位面板（不使用遮罩），打开时聊天区整体左移，保证聊天区始终可操作。
- **解析进度轮询**：文档状态为 `pending`/`parsing` 时每 1.5s 轮询 `/api/kb/documents/{doc_id}/status`，
  全部落地后刷新整表；组件卸载时清除定时器。

## 六、注意事项

- 验证码「使用一次即失效」，登录/注册失败后组件会自动刷新验证码。
- 分块预览页依赖路由 `query` 中的 `kbId`、`name` 展示所属文档名与返回链接，刷新页面参数仍保留在 URL 中。
- 助手回答中的引用来源可折叠，展示文档名、页码、相似度（0~1 自动换算为百分比）。
