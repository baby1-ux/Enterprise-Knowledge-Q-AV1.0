"""图形验证码单元测试。"""

from __future__ import annotations

from app.core.captcha import CaptchaStore, generate_captcha_code, render_captcha_image


def test_generate_code_length_and_charset() -> None:
    """验证码长度固定且不含易混淆字符。"""
    code = generate_captcha_code(4)
    assert len(code) == 4
    assert set(code) <= set("23456789ABCDEFGHJKLMNPQRSTUVWXYZ")


def test_render_returns_png_data_uri() -> None:
    """渲染结果为 base64 PNG data URI。"""
    image = render_captcha_image("AB34", 130, 44)
    assert image.startswith("data:image/png;base64,")
    assert len(image) > 200


def test_store_verify_case_insensitive_and_single_use() -> None:
    """验证码大小写不敏感，且使用一次后失效。"""
    store = CaptchaStore(expire_seconds=300)
    captcha_id, code, image = store.create()
    assert image.startswith("data:image/png;base64,")
    assert store.verify(captcha_id, code.lower()) is True
    assert store.verify(captcha_id, code) is False


def test_store_rejects_wrong_code() -> None:
    """错误验证码校验失败。"""
    store = CaptchaStore(expire_seconds=300)
    captcha_id, _, _ = store.create()
    assert store.verify(captcha_id, "0000") is False


def test_store_rejects_unknown_id() -> None:
    """不存在的验证码 ID 校验失败。"""
    store = CaptchaStore(expire_seconds=300)
    assert store.verify("not-exists", "1234") is False


def test_store_rejects_expired_code() -> None:
    """过期验证码校验失败。"""
    store = CaptchaStore(expire_seconds=-1)
    captcha_id, code, _ = store.create()
    assert store.verify(captcha_id, code) is False


def test_store_clear() -> None:
    """清空后不再保留任何验证码。"""
    store = CaptchaStore()
    store.create()
    store.create()
    assert store.size == 2
    store.clear()
    assert store.size == 0
