"""用户与鉴权相关的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .common import ORMSchema, TimestampSchema

USERNAME_PATTERN = r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,32}$"


class CaptchaData(BaseModel):
    """图形验证码。"""

    captcha_id: str
    image: str
    code: str | None = None  # 仅调试模式下返回


class RegisterRequest(BaseModel):
    """注册请求。"""

    username: str = Field(..., min_length=3, max_length=32, description="账号名称")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    confirm_password: str = Field(..., min_length=6, max_length=64, description="确认密码")
    captcha_id: str = Field(..., min_length=4, description="验证码 ID")
    captcha_code: str = Field(..., min_length=1, max_length=8, description="验证码")

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        import re

        value = value.strip()
        if not re.match(USERNAME_PATTERN, value):
            raise ValueError("账号名称需为 3~32 位中文、字母、数字或下划线")
        return value


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=1, max_length=32, description="账号名称")
    password: str = Field(..., min_length=1, max_length=64, description="密码")
    captcha_id: str = Field(..., min_length=4, description="验证码 ID")
    captcha_code: str = Field(..., min_length=1, max_length=8, description="验证码")


class UserOut(TimestampSchema):
    """用户信息。"""

    id: int
    username: str
    created_at: str | None = None


class UserProfileOut(UserOut):
    """当前用户信息（含角色与管理员标识）。"""

    roles: list[str] = Field(default_factory=list, description="用户拥有的角色代码列表")
    is_admin: bool = Field(default=False, description="是否管理员")


class LoginData(BaseModel):
    """登录成功返回。"""

    access_token: str
    token_type: str = "bearer"
    user: UserProfileOut


class UserRegisterOut(ORMSchema):
    """注册成功返回。"""

    id: int
    username: str
