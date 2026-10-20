"""安全模块：密码哈希（PBKDF2-SHA256）与 JWT 令牌。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

ALGORITHM = "HS256"
PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16


class TokenError(Exception):
    """令牌解析失败。"""


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """生成密码哈希，格式：pbkdf2_sha256$迭代次数$盐$哈希。"""
    if not isinstance(password, str) or not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码，恒定时间比较，任何异常都视为校验失败。"""
    if not password or not stored_hash:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(
    subject: str | int,
    secret_key: str,
    expires_minutes: int = 1440,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT 访问令牌。"""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_token(token: str, secret_key: str) -> dict[str, Any]:
    """解析并校验 JWT，失败抛出 TokenError。"""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("登录凭证无效，请重新登录") from exc
    if "sub" not in payload:
        raise TokenError("登录凭证无效，请重新登录")
    return payload


def generate_password(length: int = 10) -> str:
    """生成随机密码（供初始化脚本使用）。"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
