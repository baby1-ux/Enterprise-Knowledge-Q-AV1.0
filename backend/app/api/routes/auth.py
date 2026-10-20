"""鉴权接口：图形验证码、注册、登录、当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.captcha import captcha_store
from ...core.config import Settings
from ...core.logging import get_logger
from ...db.models import User
from ...db.session import get_db
from ...schemas.user import (
    CaptchaData,
    LoginData,
    LoginRequest,
    RegisterRequest,
    UserOut,
    UserRegisterOut,
)
from ...services.auth_service import AuthService, user_to_dict
from ..deps import get_current_user, get_settings_dep
from ..helpers import dump, ok

router = APIRouter(prefix="/auth", tags=["鉴权"])
logger = get_logger("api.auth")


@router.get("/captcha", summary="获取图形验证码")
def get_captcha(cfg: Settings = Depends(get_settings_dep)) -> dict:
    """生成验证码图片（base64）。"""
    captcha_id, code, image = captcha_store.create()
    data = CaptchaData(captcha_id=captcha_id, image=image, code=code if cfg.captcha.debug_expose else None)
    return ok(dump(data))


@router.post("/register", summary="用户注册")
def register(payload: RegisterRequest, db: Session = Depends(get_db), cfg: Settings = Depends(get_settings_dep)) -> dict:
    """注册新账号（需通过图形验证码）。"""
    service = AuthService(db, cfg)
    user = service.register(
        username=payload.username,
        password=payload.password,
        confirm_password=payload.confirm_password,
        captcha_id=payload.captcha_id,
        captcha_code=payload.captcha_code,
    )
    return ok(dump(UserRegisterOut.model_validate(user)), "注册成功")


@router.post("/login", summary="用户登录")
def login(payload: LoginRequest, db: Session = Depends(get_db), cfg: Settings = Depends(get_settings_dep)) -> dict:
    """账号密码登录（需通过图形验证码）。"""
    service = AuthService(db, cfg)
    user, token = service.login(
        username=payload.username,
        password=payload.password,
        captcha_id=payload.captcha_id,
        captcha_code=payload.captcha_code,
    )
    data = LoginData(access_token=token, token_type="bearer", user=UserOut(**user_to_dict(user)))
    return ok(dump(data), "登录成功")


@router.get("/me", summary="当前登录用户")
def me(current_user: User = Depends(get_current_user)) -> dict:
    """返回当前登录用户信息。"""
    return ok(dump(UserOut(**user_to_dict(current_user))))


@router.post("/logout", summary="退出登录")
def logout(current_user: User = Depends(get_current_user)) -> dict:
    """退出登录（JWT 无状态，前端清除本地令牌即可）。"""
    logger.info("用户退出登录：username=%s", current_user.username)
    return ok({"logout": True}, "已退出登录")
