"""FastAPI 应用入口：中间件、异常处理、路由注册、建表初始化。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import auth, chat, kb, system
from .core.captcha import captcha_store
from .core.config import Settings, get_settings
from .core.errors import AppError, failure
from .core.logging import get_logger, setup_logging
from .db.session import dispose_engine, init_db

# 参数名 -> 中文提示
_FIELD_LABELS = {
    "username": "账号名称",
    "password": "密码",
    "confirm_password": "确认密码",
    "captcha_id": "验证码 ID",
    "captcha_code": "验证码",
    "question": "问题内容",
    "session_id": "会话 ID",
    "name": "名称",
    "content": "内容",
    "file": "文件",
    "chunk_size": "切块大小",
    "chunk_overlap": "重叠大小",
    "retrieval_mode": "检索方式",
    "temperature": "温度",
    "top_p": "topP",
    "max_tokens": "最长输出 token 数",
    "history_rounds": "历史对话轮数",
    "kb_ids": "知识库",
}


def _friendly_validation_message(exc: RequestValidationError) -> str:
    """把 Pydantic 校验错误翻译成中文提示。"""
    messages: list[str] = []
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", []) if item not in ("body", "query", "path")]
        field = location[-1] if location else ""
        label = _FIELD_LABELS.get(field, field or "请求参数")
        reason = error.get("msg", "参数不合法")
        if "Field required" in reason:
            reason = "不能为空"
        elif reason.startswith("String should have at least"):
            reason = "长度不足"
        elif reason.startswith("String should have at most"):
            reason = "长度超限"
        elif reason.startswith("Input should be greater than or equal to"):
            reason = "取值过小"
        elif reason.startswith("Input should be less than or equal to"):
            reason = "取值过大"
        elif reason.startswith("Value error"):
            detail = error.get("ctx", {}) or {}
            reason = str(detail.get("error") or "取值不合法")
        messages.append(f"{label}{'' if reason in ('不能为空',) else '：'}{reason}")
    return "；".join(messages) or "请求参数不合法"


def create_app(cfg: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    cfg = cfg or get_settings()
    setup_logging(cfg.log_path, cfg.app.log_level, app_name="rag_qa")
    logger = get_logger("main")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """启动与关闭时的初始化工作。"""
        cfg.upload_path.mkdir(parents=True, exist_ok=True)
        cfg.log_path.mkdir(parents=True, exist_ok=True)
        captcha_store.configure(
            expire_seconds=cfg.captcha.expire_seconds,
            length=cfg.captcha.length,
            width=cfg.captcha.width,
            height=cfg.captcha.height,
        )
        try:
            init_db(cfg)
        except Exception as exc:  # noqa: BLE001 - 数据库不可用时仍允许启动以便排查
            logger.error("数据库初始化失败，请检查 MySQL 是否已启动：%s", exc)
        logger.info(
            "%s v%s 启动完成：http://%s:%s，向量库=%s，向量化=%s",
            cfg.app.name,
            cfg.app.version,
            cfg.app.host,
            cfg.app.port,
            cfg.milvus.provider,
            cfg.embedding.provider,
        )
        yield
        dispose_engine()
        logger.info("服务已停止")

    app = FastAPI(
        title=cfg.app.name,
        description="基于企业内容知识库的 RAG 问答系统后端接口",
        version=cfg.app.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.app.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ------------------------------------------------------------ 异常处理
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info("业务异常：%s %s -> %s", request.method, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.code,
            content=jsonable_encoder(failure(exc.message, exc.code, exc.data)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        message = _friendly_validation_message(exc)
        logger.info("参数校验失败：%s %s -> %s", request.method, request.url.path, message)
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                failure(message, 422, {"detail": exc.errors()})
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=jsonable_encoder(failure(f"服务器内部错误：{exc}", 500)),
        )

    # ------------------------------------------------------------ 路由
    app.include_router(auth.router, prefix="/api")
    app.include_router(kb.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(system.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def index() -> dict:
        """根路径信息。"""
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "name": cfg.app.name,
                "version": cfg.app.version,
                "docs": "/docs",
                "health": "/api/health",
            },
        }

    return app


app = create_app()
