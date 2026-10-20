"""FastAPI 依赖注入：数据库会话、当前用户、服务实例。"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from ..core.config import Settings, settings as current_settings
from ..core.errors import UnauthorizedError
from ..core.logging import get_logger
from ..core.security import TokenError, decode_token
from ..db.models import User
from ..db.session import get_db
from ..services.chat_service import ChatService
from ..services.kb_service import KnowledgeBaseService

logger = get_logger("api.deps")


def get_settings_dep() -> Settings:
    """当前配置。"""
    return current_settings()


def _extract_token(authorization: str | None) -> str:
    """从 Authorization 头中提取 Bearer Token。"""
    if not authorization:
        raise UnauthorizedError("请先登录")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("登录凭证格式不正确，请重新登录")
    return parts[1].strip()


def get_current_user(
    authorization: str | None = Header(default=None, description="Bearer <token>"),
    db: Session = Depends(get_db),
    cfg: Settings = Depends(get_settings_dep),
) -> User:
    """解析当前登录用户。"""
    token = _extract_token(authorization)
    try:
        payload = decode_token(token, cfg.app.secret_key)
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError("登录凭证无效，请重新登录") from exc

    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("账号不存在或已被删除，请重新登录")
    return user


def get_db_session(db: Session = Depends(get_db)) -> Iterator[Session]:
    """请求级数据库会话（显式依赖，便于在测试中覆盖）。"""
    yield db


def get_kb_service(
    db: Session = Depends(get_db), cfg: Settings = Depends(get_settings_dep)
) -> KnowledgeBaseService:
    """知识库服务。"""
    return KnowledgeBaseService(db, cfg)


def get_chat_service(
    db: Session = Depends(get_db), cfg: Settings = Depends(get_settings_dep)
) -> ChatService:
    """对话服务。"""
    return ChatService(db, cfg)
