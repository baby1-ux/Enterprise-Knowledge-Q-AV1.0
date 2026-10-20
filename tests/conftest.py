"""pytest 公共夹具：临时数据库、测试配置、HTTP 客户端、登录态。

测试默认使用 SQLite + 内存向量库 + 哈希向量化 + 假大模型，
不依赖 MySQL / Milvus / DashScope，可在任何环境下离线运行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest

# 让测试可以直接 import app.*
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.captcha import captcha_store  # noqa: E402
from app.core.config import Settings, clear_settings_override, override_settings  # noqa: E402
from app.db.session import dispose_engine, get_session_factory, init_db, init_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import embedding as embedding_module  # noqa: E402
from app.services import llm as llm_module  # noqa: E402
from app.services import retriever as retriever_module  # noqa: E402
from app.services import vector_store as vector_module  # noqa: E402

TEST_USERNAME = "teacher01"
TEST_PASSWORD = "abc12345"


# --------------------------------------------------------------------- 配置
@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """构造完全离线的测试配置。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.app.name = "企业内容知识问答系统"
    cfg.app.secret_key = "unit-test-secret-key-please-change-0123456789"
    cfg.app.access_token_expire_minutes = 60
    cfg.app.upload_dir = str(tmp_path / "uploads")
    cfg.app.log_dir = str(tmp_path / "logs")
    cfg.app.debug = False

    cfg.mysql.url_override = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    cfg.mysql.echo = False

    cfg.milvus.provider = "memory"

    cfg.llm.provider = "deepseek"
    cfg.llm.api_key = "sk-unit-test-deepseek-key"
    cfg.llm.base_url = "https://api.deepseek.com/v1"
    cfg.llm.default_model = "deepseek-chat"
    cfg.llm.defaults.history_rounds = 5

    # 向量化 / 重排 / OCR 仍走 DashScope，测试里用哈希向量替代，只留一个假 Key 校验配置读取
    cfg.embedding.provider = "hash"
    cfg.embedding.dimension = 64
    cfg.embedding.batch_size = 4
    cfg.embedding.api_key = "sk-unit-test-dashscope-key"
    cfg.embedding.base_url = "https://dashscope.aliyuncs.com/api/v1"
    cfg.rerank.enabled = False
    cfg.rerank.api_key = "sk-unit-test-dashscope-key"
    cfg.parser.ocr.api_key = "sk-unit-test-dashscope-key"

    cfg.rag.retrieval.mode = "dense"
    cfg.rag.retrieval.top_k = 3
    cfg.rag.retrieval.score_threshold = 0.0
    cfg.rag.context.max_chars = 4000

    cfg.captcha.debug_expose = True
    return cfg


@pytest.fixture()
def app_env(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """初始化全局配置、数据库与各类服务缓存。"""
    override_settings(test_settings)
    captcha_store.configure(
        expire_seconds=test_settings.captcha.expire_seconds,
        length=test_settings.captcha.length,
        width=test_settings.captcha.width,
        height=test_settings.captcha.height,
    )
    captcha_store.clear()
    embedding_module.reset_embedder()
    vector_module.reset_vector_store()
    llm_module.reset_llm()
    retriever_module.reset_retriever()

    init_engine(test_settings, force=True)
    init_db(test_settings)

    yield test_settings

    dispose_engine()
    vector_module.reset_vector_store()
    embedding_module.reset_embedder()
    llm_module.reset_llm()
    retriever_module.reset_retriever()
    captcha_store.clear()
    clear_settings_override()


@pytest.fixture()
def client(app_env: Settings) -> Iterator[TestClient]:
    """带生命周期的测试客户端。"""
    app = create_app(app_env)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(app_env: Settings) -> Iterator:
    """直接访问数据库的会话。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------- 鉴权
def fetch_captcha(client: TestClient) -> tuple[str, str]:
    """获取验证码（测试模式下接口会返回明文验证码）。"""
    response = client.get("/api/auth/captcha")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return data["captcha_id"], data["code"]


def register_user(client: TestClient, username: str = TEST_USERNAME, password: str = TEST_PASSWORD) -> dict:
    """注册测试用户。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]


def login_user(client: TestClient, username: str = TEST_USERNAME, password: str = TEST_PASSWORD) -> str:
    """登录并返回 access_token。"""
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]["access_token"]


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    """注册并登录，返回鉴权请求头。"""
    register_user(client)
    token = login_user(client)
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- 假大模型
class FakeLLM:
    """离线假大模型：按固定文本流式输出。"""

    def __init__(self, reply: str = "根据企业资料，产品保修期为一年，自购买之日起计算。[1]") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def model_options(self) -> list[dict[str, str]]:
        return [
            {"value": "deepseek-chat", "label": "DeepSeek-Chat", "description": "通用对话模型（测试）"},
            {"value": "deepseek-reasoner", "label": "DeepSeek-Reasoner", "description": "推理模型（测试）"},
        ]

    def stream_chat(self, messages, model=None, temperature=0.3, top_p=0.8, max_tokens=2048):  # noqa: ANN001
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            }
        )
        step = 6
        for start in range(0, len(self.reply), step):
            yield self.reply[start : start + step]

    def complete(self, messages, model=None, temperature=0.3, top_p=0.8, max_tokens=1024):  # noqa: ANN001
        return "产品保修期"

    def last_messages(self) -> list[dict]:
        return self.calls[-1]["messages"] if self.calls else []


@pytest.fixture()
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """把对话服务中的大模型替换为假实现。"""
    import app.services.chat_service as chat_service_module

    fake = FakeLLM()
    monkeypatch.setattr(chat_service_module, "get_llm", lambda cfg=None: fake)
    return fake


# --------------------------------------------------------------------- 上传辅助
def upload_markdown(
    client: TestClient,
    headers: dict[str, str],
    kb_id: int,
    content: str,
    filename: str = "产品手册.md",
    chunk_size: int = 200,
    chunk_overlap: int = 20,
    retrieval_mode: str = "dense",
) -> dict:
    """上传 Markdown 文档并返回文档响应体（后台任务在测试客户端中同步执行）。"""
    response = client.post(
        f"/api/kb/{kb_id}/documents",
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        data={
            "chunk_size": str(chunk_size),
            "chunk_overlap": str(chunk_overlap),
            "retrieval_mode": retrieval_mode,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def create_kb(client: TestClient, headers: dict[str, str], name: str = "产品知识库") -> dict:
    """创建知识库并返回响应体。"""
    response = client.post("/api/kb/", headers=headers, json={"name": name, "description": "测试用知识库"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


SAMPLE_MARKDOWN = """# 产品保修政策

## 保修期限

公司所有电子产品自购买之日起提供一年免费保修服务。保修期内非人为损坏可免费维修或更换。

## 保修流程

用户需在官网提交保修申请，客服在 2 个工作日内响应，并安排上门取件或寄修。

## 注意事项

以下情况不在保修范围内：进水、摔碰、私自拆机、超出售后服务期限。
"""
