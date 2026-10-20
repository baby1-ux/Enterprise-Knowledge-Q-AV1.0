"""对话接口：模型参数、会话管理、消息历史、流式问答（SSE）。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.logging import get_logger
from ...db.models import ChatMessage, User
from ...db.session import get_db
from ...schemas.chat import (
    ChatModelsOut,
    ChatStreamRequest,
    MessageFeedbackUpdate,
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from ...services.chat_service import ChatService, message_to_dict, session_to_dict
from ..deps import get_chat_service, get_current_user, get_settings_dep
from ..helpers import dump, ok, sse_event

router = APIRouter(prefix="/chat", tags=["对话"])
logger = get_logger("api.chat")

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/models", summary="可选模型与默认参数")
def get_models(
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """返回对话页可选的模型列表与默认推理参数。"""
    return ok(dump(ChatModelsOut(**service.model_info())))


# ============================================================ 会话
@router.get("/sessions", summary="会话列表")
def list_sessions(
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """列出当前用户的全部会话。"""
    sessions = service.list_sessions(current_user.id)
    return ok([dump(SessionOut(**item)) for item in sessions])


@router.post("/sessions", summary="新建会话")
def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """新建对话会话（可指定名称、知识库与推理参数）。"""
    session = service.create_session(current_user.id, payload)
    data = session_to_dict(session)
    data["kb_names"] = []
    return ok(dump(SessionOut(**data)), "创建成功")


@router.put("/sessions/{session_id}", summary="更新会话")
def update_session(
    session_id: int,
    payload: SessionUpdate,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """更新会话名称、知识库或推理参数。"""
    session = service.update_session(current_user.id, session_id, payload)
    data = session_to_dict(session)
    data["kb_names"] = service.kb_names_for(current_user.id, data["kb_ids"])
    return ok(dump(SessionOut(**data)), "更新成功")


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """删除会话及其历史消息。"""
    service.delete_session(current_user.id, session_id)
    return ok({"deleted": True}, "删除成功")


@router.get("/sessions/{session_id}/messages", summary="会话消息")
def list_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """读取会话的全部历史消息（含引用来源）。"""
    messages: list[ChatMessage] = service.list_messages(current_user.id, session_id)
    return ok([dump(MessageOut(**message_to_dict(message))) for message in messages])


@router.get("/sessions/{session_id}/export", summary="导出会话（Markdown）")
def export_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """导出会话为 Markdown 文件（含回答、引用来源与推理参数）。"""
    markdown = service.export_session_markdown(current_user.id, session_id)
    session = service.get_session(current_user.id, session_id)
    filename = f"{session.name or '对话'}.md"
    # 文件名做 URL 编码，避免中文在响应头中报错
    return Response(
        content=markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.put("/messages/{message_id}/feedback", summary="消息反馈（赞/踩）")
def feedback_message(
    message_id: int,
    payload: MessageFeedbackUpdate,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """对助手回答提交反馈：like / dislike / 取消（feedback 传 null）。"""
    message = service.feedback_message(current_user.id, message_id, payload.feedback)
    return ok(dump(MessageOut(**message_to_dict(message))), "反馈成功")


# ============================================================ 流式问答
@router.post("/stream", summary="流式问答（SSE）")
def stream_chat(
    payload: ChatStreamRequest,
    current_user: User = Depends(get_current_user),
    cfg: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """基于所选知识库检索并流式生成回答。

    响应为 text/event-stream，事件：start / retrieval / delta / done / error。
    """
    # 先校验会话归属与模型合法性：不通过时直接返回 404 / 400，避免建立无意义的流式连接
    validator = ChatService(db, cfg)
    validator.get_session(current_user.id, payload.session_id)
    if payload.model:
        validator.ensure_supported_model(payload.model)

    service = ChatService(None, cfg)

    def event_generator():
        try:
            for event, data in service.stream_answer(current_user.id, payload):
                yield sse_event(event, data)
        except Exception as exc:  # noqa: BLE001 - SSE 内部异常统一转 error 事件
            logger.exception("流式问答异常")
            yield sse_event("error", {"message": f"服务异常：{exc}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)
