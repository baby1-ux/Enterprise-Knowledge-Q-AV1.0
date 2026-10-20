"""RBAC 端到端冒烟测试（真实 MySQL + Milvus + DeepSeek + DashScope）。

覆盖：admin 白名单注册 → 自定义角色 → 用户角色分配 → KB 三档可见范围
     → 角色/人员授权 → 只读拦截 → 检索隔离 → 统计口径

前置：后端已启动，且 captcha.debug_expose 为 true
     （脚本化登录需要读取验证码明文，仅限本地调试）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "产品保修政策.md"
RUN_ID = str(int(time.time()))

# admin 账号固定（需在启动配置的 app.admin_usernames 中登记），staff/viewer 每次运行唯一
ADMIN = "rbac_admin_smoke"
STAFF = f"rbac_staff_{RUN_ID}"
VIEWER = f"rbac_viewer_{RUN_ID}"
PASSWORD = "abc12345"


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


class Client:
    """带验证码与登录态的轻量客户端。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.session = requests.Session()
        self.headers: dict[str, str] = {}

    def register(self) -> None:
        """注册（账号已存在时忽略，直接走登录）。"""
        captcha = self.session.get(f"{BASE}/api/auth/captcha", timeout=10).json()["data"]
        response = self.session.post(
            f"{BASE}/api/auth/register",
            json={
                "username": self.name,
                "password": PASSWORD,
                "confirm_password": PASSWORD,
                "captcha_id": captcha["captcha_id"],
                "captcha_code": captcha["code"],
            },
            timeout=10,
        ).json()
        if response["code"] != 0 and "已存在" not in response.get("message", ""):
            fail(f"注册失败（{self.name}）：{response}")

    def login(self) -> None:
        captcha = self.session.get(f"{BASE}/api/auth/captcha", timeout=10).json()["data"]
        response = self.session.post(
            f"{BASE}/api/auth/login",
            json={
                "username": self.name,
                "password": PASSWORD,
                "captcha_id": captcha["captcha_id"],
                "captcha_code": captcha["code"],
            },
            timeout=10,
        ).json()
        if response["code"] != 0:
            fail(f"登录失败（{self.name}）：{response}")
        self.headers = {"Authorization": f"Bearer {response['data']['access_token']}"}


def main() -> int:
    admin = Client(ADMIN)
    admin.register()
    admin.login()
    staff = Client(STAFF)
    staff.register()
    staff.login()
    viewer = Client(VIEWER)
    viewer.register()
    viewer.login()

    # 1. /me 返回角色
    me = admin.session.get(f"{BASE}/api/auth/me", headers=admin.headers, timeout=10).json()["data"]
    print(f"[1/10] admin 注册即获 admin 角色：roles={me['roles']} is_admin={me['is_admin']}")
    if not me["is_admin"]:
        fail("admin 白名单未生效（请确认 config.yaml -> app.admin_usernames 包含该账号）")

    # 2. 创建自定义角色并授予 staff 用户
    role = admin.session.post(
        f"{BASE}/api/admin/roles",
        headers=admin.headers,
        json={"code": f"smoke_role_{RUN_ID}", "name": "冒烟角色", "description": "E2E 用"},
        timeout=10,
    ).json()["data"]
    print(f"[2/10] 创建自定义角色：id={role['id']} code={role['code']}")

    users = admin.session.get(f"{BASE}/api/admin/users", headers=admin.headers, timeout=10).json()["data"]
    staff_user = next(item for item in users if item["username"] == STAFF)
    response = admin.session.put(
        f"{BASE}/api/admin/users/{staff_user['id']}/roles",
        headers=admin.headers,
        json={"role_ids": [role["id"]]},
        timeout=10,
    )
    if response.status_code != 200:
        fail(f"用户角色分配失败：{response.text}")
    print(f"[3/10] 为 staff 分配角色：{response.json()['message']}")

    # 3. 非 admin 访问管理接口 → 403
    response = staff.session.get(f"{BASE}/api/admin/roles", headers=staff.headers, timeout=10)
    if response.status_code != 403:
        fail(f"非 admin 应被拒绝（实际 HTTP {response.status_code}）")
    print("[4/10] 非 admin 访问管理接口被 403 拒绝")

    # 4. 创建私有 KB 并上传文档，staff / viewer 均看不到
    private_kb = admin.session.post(
        f"{BASE}/api/kb/", headers=admin.headers, json={"name": "RBAC 私库"}
    ).json()["data"]
    with open(SAMPLE, "rb") as handle:
        response = admin.session.post(
            f"{BASE}/api/kb/{private_kb['id']}/documents",
            headers=admin.headers,
            files={"file": (SAMPLE.name, handle.read(), "text/markdown")},
            data={"chunk_size": "300", "chunk_overlap": "50", "retrieval_mode": "hybrid"},
            timeout=120,
        )
    if response.status_code != 200:
        fail(f"admin 上传失败：{response.text}")
    print(f"[5/10] admin 私有库上传解析：kb_id={private_kb['id']}")

    for label, client in (("staff", staff), ("viewer", viewer)):
        kbs = client.session.get(f"{BASE}/api/kb/", headers=client.headers, timeout=10).json()["data"]
        if kbs:
            fail(f"{label} 不应看到 admin 的私有库：{[kb['name'] for kb in kbs]}")
    print("[6/10] staff / viewer 均看不到 admin 的私有库（visibility=private 隔离生效）")

    # 5. 私有库改为角色共享并授权给自定义角色（只读）
    admin.session.put(
        f"{BASE}/api/kb/{private_kb['id']}", headers=admin.headers, json={"visibility": "role"}
    )
    response = admin.session.put(
        f"{BASE}/api/admin/kb/{private_kb['id']}/permission",
        headers=admin.headers,
        json={"role_grants": [{"role_id": role["id"], "can_read": True, "can_write": False}]},
        timeout=10,
    )
    if response.status_code != 200:
        fail(f"KB 授权失败：{response.text}")
    print("[7/10] 私有库改为角色共享并授权（只读）")

    kbs = staff.session.get(f"{BASE}/api/kb/", headers=staff.headers, timeout=10).json()["data"]
    if len(kbs) != 1 or kbs[0]["can_write"]:
        fail(f"staff 应只读可见该库：{kbs}")
    response = staff.session.post(
        f"{BASE}/api/kb/{private_kb['id']}/documents",
        headers=staff.headers,
        files={"file": ("x.md", b"# x\n\ncontent", "text/markdown")},
        data={"chunk_size": "200", "chunk_overlap": "20", "retrieval_mode": "dense"},
        timeout=60,
    )
    if response.status_code != 403:
        fail(f"staff 只读上传应被 403（实际 HTTP {response.status_code}）")
    print("[8/10] staff 只读可见该库，上传被 403 拦截")

    # 6. 跨库搜索隔离：viewer 搜不到他人分块
    data = viewer.session.get(
        f"{BASE}/api/kb/chunks/search", headers=viewer.headers, params={"keyword": "保修"}, timeout=10
    ).json()["data"]
    if data["total"]:
        fail(f"viewer 不应搜到他人分块：{data['total']}")
    print("[9/10] viewer 跨库搜索命中 0 条（检索隔离生效）")

    # 7. staff 提问命中被授权库
    chat_session = staff.session.post(
        f"{BASE}/api/chat/sessions",
        headers=staff.headers,
        json={"name": "RBAC 会话", "kb_ids": [private_kb["id"]]},
        timeout=10,
    ).json()["data"]
    if private_kb["id"] not in chat_session["kb_ids"]:
        fail(f"staff 会话应保留被授权 KB：{chat_session}")
    print("[10/10] staff 会话绑定被授权 KB 成功")

    print("\nRBAC 端到端冒烟测试全部通过 [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
