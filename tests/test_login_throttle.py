"""登录防爆破测试：连续失败锁定、成功重置、验证码错误不连坐。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core.rate_limit import LoginThrottle, login_throttle

from tests.conftest import TEST_PASSWORD, TEST_USERNAME, fetch_captcha, register_user


def _attempt_login(client: TestClient, password: str = TEST_PASSWORD, username: str = TEST_USERNAME) -> dict:
    """带验证码发起一次登录，返回响应 JSON。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "captcha_id": captcha_id, "captcha_code": code},
    )
    assert response.status_code in (200, 400), response.text
    return response.json()


def _attempt_login_wrong_captcha(client: TestClient, username: str = TEST_USERNAME) -> dict:
    """使用错误验证码登录（验证码错误，不应计入失败次数）。"""
    captcha_id, _ = fetch_captcha(client)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASSWORD, "captcha_id": captcha_id, "captcha_code": "ZZZZ"},
    )
    assert response.status_code == 400, response.text
    return response.json()


def test_login_locked_after_max_failures(client: TestClient, app_env) -> None:
    """连续输错密码达到上限后锁定，即使密码正确也拒绝。"""
    register_user(client)
    app_env.app.login_max_attempts = 3
    app_env.app.login_lock_minutes = 10
    login_throttle.configure(max_attempts=3, lock_minutes=10)
    login_throttle.clear()
    try:
        # 前两次：普通失败提示
        for _ in range(2):
            body = _attempt_login(client, password="wrong-password")
            assert "账号或密码错误" in body["message"]
            assert "已锁定" not in body["message"]

        # 第 3 次失败达到上限：立即锁定
        locked_now = _attempt_login(client, password="wrong-password")
        assert "已锁定" in locked_now["message"]
        assert "10 分钟" in locked_now["message"]

        # 第 4 次：密码正确也应被锁定
        locked = _attempt_login(client)
        assert "已锁定" in locked["message"]
        assert "10 分钟" in locked["message"]
    finally:
        login_throttle.clear()


def test_login_success_resets_failure_count(client: TestClient, app_env) -> None:
    """登录成功后失败计数清零，不会因历史失败被锁定。"""
    register_user(client)
    app_env.app.login_max_attempts = 3
    app_env.app.login_lock_minutes = 10
    login_throttle.configure(max_attempts=3, lock_minutes=10)
    login_throttle.clear()
    try:
        _attempt_login(client, password="wrong-password")
        _attempt_login(client, password="wrong-password")

        # 成功登录一次，计数清零
        ok_body = _attempt_login(client)
        assert ok_body["code"] == 0

        # 再失败两次仍未达上限
        _attempt_login(client, password="wrong-password")
        body = _attempt_login(client, password="wrong-password")
        assert "账号或密码错误" in body["message"]
        assert "已锁定" not in body["message"]
    finally:
        login_throttle.clear()


def test_captcha_error_not_counted(client: TestClient, app_env) -> None:
    """验证码错误不计入登录失败（未验证身份不应连坐）。"""
    register_user(client)
    app_env.app.login_max_attempts = 3
    app_env.app.login_lock_minutes = 10
    login_throttle.configure(max_attempts=3, lock_minutes=10)
    login_throttle.clear()
    try:
        for _ in range(3):
            body = _attempt_login_wrong_captcha(client)
            assert "验证码" in body["message"]

        # 验证码正确 + 密码正确：仍然可以登录
        ok_body = _attempt_login(client)
        assert ok_body["code"] == 0
    finally:
        login_throttle.clear()


def test_throttle_lock_expires() -> None:
    """锁定过期后自动恢复（单元测试，使用短锁定时长）。"""
    throttle = LoginThrottle(max_attempts=3, lock_seconds=1)
    throttle.record_failure("alice")
    throttle.record_failure("alice")
    assert throttle.check("alice") == (False, 0)

    locked, minutes = throttle.record_failure("alice")
    assert locked is True
    assert minutes == 1
    assert throttle.check("alice")[0] is True

    time.sleep(1.05)
    assert throttle.check("alice") == (False, 0)


def test_throttle_success_clears_and_case_insensitive() -> None:
    """成功后清除记录；用户名大小写不敏感。"""
    throttle = LoginThrottle(max_attempts=5, lock_seconds=600)
    throttle.record_failure("Alice")
    throttle.record_failure("alice")
    assert throttle.check("ALICE") == (False, 0)  # 未达上限

    throttle.record_success("ALICE")
    # 清零后再失败一次不会立刻锁定
    locked, _ = throttle.record_failure("alice")
    assert locked is False
