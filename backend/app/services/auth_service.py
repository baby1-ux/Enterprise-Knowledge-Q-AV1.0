"""用户服务：注册、登录、当前用户。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.captcha import captcha_store
from ..core.config import Settings, settings as current_settings
from ..core.errors import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.rate_limit import login_throttle
from ..core.security import create_access_token, hash_password, verify_password
from ..db.models import User
from ..schemas.common import format_datetime

logger = get_logger("auth_service")


def user_to_dict(user: User) -> dict:
    """用户对象转响应字典（时间统一格式化）。"""
    return {
        "id": user.id,
        "username": user.username,
        "created_at": format_datetime(user.created_at),
    }


class AuthService:
    """账号相关业务逻辑。"""

    def __init__(self, db: Session, cfg: Settings | None = None) -> None:
        self.db = db
        self.settings = cfg or current_settings()

    # ------------------------------------------------------------------
    def verify_captcha(self, captcha_id: str, captcha_code: str) -> None:
        """校验图形验证码，失败抛出业务异常。"""
        if not captcha_store.verify(captcha_id, captcha_code):
            raise ValidationError("验证码错误或已过期，请刷新后重试")

    def get_user(self, user_id: int) -> User:
        """按 ID 获取用户。"""
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        return user

    def get_user_by_username(self, username: str) -> User | None:
        """按账号获取用户。"""
        return self.db.scalars(select(User).where(User.username == username)).first()

    # ------------------------------------------------------------------
    def register(self, username: str, password: str, confirm_password: str, captcha_id: str, captcha_code: str) -> User:
        """用户注册。"""
        self.verify_captcha(captcha_id, captcha_code)

        username = username.strip()
        if password != confirm_password:
            raise ValidationError("两次输入的密码不一致")
        if self.get_user_by_username(username) is not None:
            raise ValidationError("该用户名已被注册，请更换后重试")

        user = User(username=username, password_hash=hash_password(password))
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        logger.info("用户注册成功：id=%s username=%s", user.id, user.username)
        return user

    def login(self, username: str, password: str, captcha_id: str, captcha_code: str) -> tuple[User, str]:
        """用户登录，返回 (用户, 令牌)。"""
        username = username.strip()

        # 1. 防爆破检查：锁定期间直接拒绝，不再消耗图形验证码
        locked, remain_minutes = login_throttle.check(username)
        if locked:
            logger.info("登录被锁定拦截：username=%s 剩余约 %s 分钟", username, remain_minutes)
            raise ValidationError(f"登录失败次数过多，账号已锁定，请 {remain_minutes} 分钟后再试")

        # 2. 图形验证码（错误不计入失败次数，未验证身份不应连坐）
        self.verify_captcha(captcha_id, captcha_code)

        user = self.get_user_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            just_locked, _ = login_throttle.record_failure(username)
            if just_locked:
                logger.info("登录失败达到上限，账号已锁定：username=%s", username)
                raise ValidationError(f"登录失败次数过多，账号已锁定，请 {self.settings.app.login_lock_minutes} 分钟后再试")
            logger.info("登录失败（账号或密码错误）：username=%s", username)
            raise ValidationError("账号或密码错误，请重新输入")

        login_throttle.record_success(username)
        token = create_access_token(
            subject=user.id,
            secret_key=self.settings.app.secret_key,
            expires_minutes=self.settings.app.access_token_expire_minutes,
            extra_claims={"username": user.username},
        )
        logger.info("用户登录成功：id=%s username=%s", user.id, user.username)
        return user, token
