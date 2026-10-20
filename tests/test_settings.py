"""配置加载单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings, is_placeholder_api_key, load_settings


def test_defaults_when_config_missing(tmp_path: Path) -> None:
    """配置文件不存在时使用内置默认值（对话模型为 DeepSeek）。"""
    cfg = load_settings(tmp_path / "missing.yaml")
    assert cfg.app.port == 8000
    assert cfg.llm.provider == "deepseek"
    assert cfg.llm.default_model == "deepseek-chat"
    assert cfg.llm.base_url.startswith("https://api.deepseek.com")
    assert [option.value for option in cfg.llm.models] == ["deepseek-chat", "deepseek-reasoner"]
    # 向量化仍默认走 DashScope
    assert cfg.embedding.provider == "dashscope"
    assert cfg.embedding.model == "text-embedding-v4"
    assert cfg.rag.retrieval.top_k == 5
    assert cfg.captcha.length == 4


def test_yaml_values_and_env_expansion(tmp_path: Path, monkeypatch) -> None:
    """读取 yaml 并展开 ${ENV:-默认值} 占位符。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
app:
  name: "${RAG_TEST_NAME:-默认系统名}"
  port: 9001
mysql:
  password: "${RAG_TEST_PWD:-123456}"
milvus:
  collection: "unit_test_chunks"
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("RAG_TEST_NAME", "自定义系统名")
    monkeypatch.delenv("RAG_TEST_PWD", raising=False)

    cfg = load_settings(config_file)
    assert cfg.app.name == "自定义系统名"
    assert cfg.app.port == 9001
    assert cfg.mysql.password == "123456"
    assert cfg.milvus.collection == "unit_test_chunks"


def test_database_url_override(tmp_path: Path) -> None:
    """url_override 优先于 MySQL 连接信息。"""
    cfg = Settings()
    cfg.mysql.url_override = "sqlite:///./unit.db"
    assert cfg.database_url == "sqlite:///./unit.db"


def test_mysql_url_contains_charset() -> None:
    """未覆盖时自动拼装 pymysql 连接串。"""
    cfg = Settings()
    cfg.mysql.host = "127.0.0.1"
    cfg.mysql.database = "rag_qa"
    assert cfg.database_url.startswith("mysql+pymysql://")
    assert "charset=utf8mb4" in cfg.database_url


def test_relative_paths_resolve_under_project_root(tmp_path: Path) -> None:
    """相对路径按项目根目录解析。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.app.upload_dir = "data/uploads"
    assert cfg.upload_path == tmp_path / "data" / "uploads"


def test_model_options_have_labels() -> None:
    """默认模型列表包含 deepseek-chat 与 deepseek-reasoner，且都有中文可读名称。"""
    from app.core.config import default_model_options

    models = default_model_options()
    assert [model.value for model in models] == ["deepseek-chat", "deepseek-reasoner"]
    assert all(model.label and model.description for model in models)


@pytest.mark.parametrize(
    "key",
    ["", "   ", "sk-请替换为你的DeepSeek-API-Key", "your-api-key", "sk-xxx"],
)
def test_placeholder_api_key_detected(key: str) -> None:
    """占位 Key 被判定为未配置。"""
    assert is_placeholder_api_key(key) is True


def test_real_api_key_not_placeholder() -> None:
    """真实 Key 判定为已配置。"""
    assert is_placeholder_api_key("sk-abcdef1234567890") is False


def test_env_keys_fill_placeholders(tmp_path: Path, monkeypatch) -> None:
    """配置文件里仍是占位 Key 时用环境变量补全（DeepSeek 与 DashScope 两套 Key 互不影响）。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
llm:
  provider: "deepseek"
  api_key: "sk-请替换为你的DeepSeek-API-Key"
  default_model: "deepseek-chat"
embedding:
  provider: "dashscope"
  api_key: "${DASHSCOPE_API_KEY:-sk-请替换为你的DashScope-API-Key}"
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-real-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-real-key")

    cfg = load_settings(config_file)
    # llm 走「占位值 → 环境变量兜底」
    assert cfg.llm.api_key == "sk-deepseek-real-key"
    # embedding 走「${ENV} 占位符展开」
    assert cfg.embedding.api_key == "sk-dashscope-real-key"
    # 重排与图片 OCR 复用 DashScope Key
    assert cfg.rerank.api_key == "sk-dashscope-real-key"
    assert cfg.parser.ocr.api_key == "sk-dashscope-real-key"
