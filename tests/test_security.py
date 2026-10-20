"""安全模块单元测试：密码哈希与 JWT。"""

from __future__ import annotations

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    decode_token,
    generate_password,
    hash_password,
    verify_password,
)

# 测试用密钥（长度满足 HS256 建议的 32 字节以上）
TEST_SECRET = "unit-test-secret-key-0123456789abcdef"
OTHER_SECRET = "another-unit-test-secret-key-0123456789"


def test_hash_password_format_and_verify() -> None:
    """密码哈希可被正确校验，且格式符合约定。"""
    stored = hash_password("abc12345")
    assert stored.startswith("pbkdf2_sha256$")
    assert len(stored.split("$")) == 4
    assert verify_password("abc12345", stored) is True


def test_verify_password_rejects_wrong_password() -> None:
    """错误密码校验失败。"""
    stored = hash_password("abc12345")
    assert verify_password("abc123456", stored) is False
    assert verify_password("", stored) is False


def test_same_password_produces_different_hash() -> None:
    """相同密码每次加盐不同，哈希结果不同。"""
    assert hash_password("abc12345") != hash_password("abc12345")


@pytest.mark.parametrize("stored", ["", "abc", "md5$1$salt$hash", "pbkdf2_sha256$abc$salt$hash"])
def test_verify_password_handles_invalid_hash(stored: str) -> None:
    """非法哈希格式一律返回 False，不抛异常。"""
    assert verify_password("abc12345", stored) is False


def test_hash_password_rejects_empty() -> None:
    """空密码不允许生成哈希。"""
    with pytest.raises(ValueError):
        hash_password("")


def test_access_token_roundtrip() -> None:
    """令牌签发后可正确解析出用户 ID。"""
    token = create_access_token(
        subject=42, secret_key=TEST_SECRET, expires_minutes=30, extra_claims={"username": "tom"}
    )
    payload = decode_token(token, TEST_SECRET)
    assert payload["sub"] == "42"
    assert payload["username"] == "tom"
    assert payload["type"] == "access"


def test_access_token_expired() -> None:
    """过期令牌解析失败并给出中文提示。"""
    token = create_access_token(subject=1, secret_key=TEST_SECRET, expires_minutes=-1)
    with pytest.raises(TokenError) as excinfo:
        decode_token(token, TEST_SECRET)
    assert "过期" in str(excinfo.value)


def test_access_token_wrong_secret() -> None:
    """密钥不匹配时令牌无效。"""
    token = create_access_token(subject=1, secret_key=TEST_SECRET, expires_minutes=30)
    with pytest.raises(TokenError):
        decode_token(token, OTHER_SECRET)


def test_generate_password_length() -> None:
    """随机密码长度符合要求。"""
    assert len(generate_password(12)) == 12
