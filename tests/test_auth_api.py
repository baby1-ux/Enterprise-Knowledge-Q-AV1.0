"""鉴权接口测试：验证码、注册、登录、当前用户。"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD, TEST_USERNAME, fetch_captcha, login_user, register_user


def test_captcha_endpoint_returns_image(client: TestClient) -> None:
    """验证码接口返回 ID 与 base64 图片。"""
    captcha_id, code = fetch_captcha(client)
    assert len(captcha_id) == 32
    assert len(code) == 4

    response = client.get("/api/auth/captcha")
    data = response.json()["data"]
    assert data["image"].startswith("data:image/png;base64,")


def test_register_success(client: TestClient) -> None:
    """注册成功后返回用户 ID 与用户名。"""
    data = register_user(client)
    assert data["username"] == TEST_USERNAME
    assert data["id"] >= 1


def test_register_password_mismatch(client: TestClient) -> None:
    """两次密码不一致注册失败。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": "zhangsan",
            "password": "abc12345",
            "confirm_password": "abc123456",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 400
    assert "两次输入的密码不一致" in body["message"]


def test_register_wrong_captcha(client: TestClient) -> None:
    """验证码错误时注册失败。"""
    captcha_id, _ = fetch_captcha(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": "lisi",
            "password": "abc12345",
            "confirm_password": "abc12345",
            "captcha_id": captcha_id,
            "captcha_code": "0000",
        },
    )
    assert response.status_code == 400
    assert "验证码" in response.json()["message"]


def test_register_duplicate_username(client: TestClient) -> None:
    """重复用户名注册失败。"""
    register_user(client)
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": TEST_USERNAME,
            "password": "abc12345",
            "confirm_password": "abc12345",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 400
    assert "已被注册" in response.json()["message"]


def test_register_invalid_username_format(client: TestClient) -> None:
    """非法账号格式返回 422 与中文提示。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": "a",
            "password": "abc12345",
            "confirm_password": "abc12345",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 422
    assert "账号名称" in response.json()["message"]


def test_login_success_returns_token(client: TestClient) -> None:
    """登录成功返回 Bearer 令牌。"""
    register_user(client)
    token = login_user(client)
    assert token.count(".") == 2


def test_login_wrong_password(client: TestClient) -> None:
    """密码错误登录失败。"""
    register_user(client)
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/login",
        json={
            "username": TEST_USERNAME,
            "password": "wrong-password",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 400
    assert "账号或密码错误" in response.json()["message"]


def test_login_unknown_user(client: TestClient) -> None:
    """不存在的账号登录失败。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": TEST_PASSWORD, "captcha_id": captcha_id, "captcha_code": code},
    )
    assert response.status_code == 400


def test_captcha_is_single_use(client: TestClient) -> None:
    """同一验证码不能重复使用。"""
    register_user(client)
    captcha_id, code = fetch_captcha(client)
    payload = {"username": TEST_USERNAME, "password": TEST_PASSWORD, "captcha_id": captcha_id, "captcha_code": code}
    first = client.post("/api/auth/login", json=payload)
    second = client.post("/api/auth/login", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400
    assert "验证码" in second.json()["message"]


def test_me_requires_token(client: TestClient) -> None:
    """未携带令牌访问受保护接口返回 401。"""
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "登录" in response.json()["message"]


def test_me_returns_current_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    """携带令牌可获取当前用户信息。"""
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"] == TEST_USERNAME
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", data["created_at"])


def test_me_rejects_invalid_token(client: TestClient) -> None:
    """非法令牌返回 401。"""
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert response.status_code == 401


def test_me_rejects_bad_header_format(client: TestClient) -> None:
    """令牌格式错误返回 401。"""
    response = client.get("/api/auth/me", headers={"Authorization": "Token abc"})
    assert response.status_code == 401


def test_logout(client: TestClient, auth_headers: dict[str, str]) -> None:
    """退出登录接口返回成功。"""
    response = client.post("/api/auth/logout", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["data"]["logout"] is True
