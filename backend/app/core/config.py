"""配置加载：读取 config.yaml + .env，支持 ${ENV} / ${ENV:-默认值} 占位符。"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml
from pydantic import BaseModel, Field

# 项目根目录：backend/app/core/config.py -> 上溯 3 级
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config.yaml"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# 配置文件中预置的占位 Key（未替换时视为"未配置"）
_PLACEHOLDER_KEY_MARKERS = ("sk-请", "请替换", "your-api-key", "your_api_key", "sk-xxx", "sk-***")


def is_placeholder_api_key(key: str | None) -> bool:
    """判断 API Key 是否为空或仍是配置模板里的占位值。"""
    if not key or not str(key).strip():
        return True
    text = str(key).strip()
    return any(marker in text.lower() for marker in _PLACEHOLDER_KEY_MARKERS)


class AppConfig(BaseModel):
    """应用基础配置。"""

    name: str = "企业内容知识问答系统"
    version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    secret_key: str = "rag-qa-system-secret-key"
    access_token_expire_minutes: int = 1440
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    upload_dir: str = "data/uploads"
    log_dir: str = "logs"
    log_level: str = "INFO"
    max_upload_size_mb: int = 50
    login_max_attempts: int = Field(default=5, description="同一账号连续登录失败次数上限，达到后锁定")
    login_lock_minutes: int = Field(default=10, description="登录失败达到上限后的锁定时长（分钟）")
    # 注册时自动授予 admin 角色的账号（与现有用户隔离，便于首部署引导）
    admin_usernames: list[str] = Field(default_factory=list, description="注册即授予管理员角色的账号白名单")
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".pdf",
            ".ppt",
            ".pptx",
            ".md",
            ".markdown",
            ".txt",
            ".docx",
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".webp",
        ]
    )


class MySQLConfig(BaseModel):
    """MySQL 业务库配置。"""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "123456"
    database: str = "rag_qa"
    charset: str = "utf8mb4"
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True
    echo: bool = False
    url_override: str = ""

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        return (
            f"mysql+pymysql://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?charset={self.charset}"
        )


class MilvusConfig(BaseModel):
    """Milvus 向量库配置。"""

    host: str = "127.0.0.1"
    port: int = 19530
    user: str = ""
    password: str = ""
    database: str = "rag_qa"
    collection: str = "rag_chunks"
    provider: str = "milvus"  # milvus | memory
    index_type: str = "HNSW"
    metric_type: str = "COSINE"
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    search_ef: int = 64

    @property
    def uri(self) -> str:
        return f"http://{self.host}:{self.port}"


class EmbeddingConfig(BaseModel):
    """文本向量化配置（默认 DashScope，DeepSeek 不提供向量化接口）。"""

    provider: str = "dashscope"  # dashscope | local_bge_m3 | hash
    model: str = "text-embedding-v4"
    dimension: int = 1024
    batch_size: int = 10
    timeout: int = 30
    max_retries: int = 3
    base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    api_key: str = ""
    model_path: str = "models/bge-m3"


class RerankConfig(BaseModel):
    """检索结果重排配置。"""

    enabled: bool = False
    provider: str = "dashscope"  # dashscope | local_bge
    model: str = "gte-rerank-v2"
    base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    api_key: str = ""
    model_path: str = "models/bge-reranker-v2-m3"
    top_n: int = 6
    timeout: int = 30


class ModelOption(BaseModel):
    """可选大模型。"""

    value: str
    label: str
    description: str = ""


def default_model_options() -> list[ModelOption]:
    """DeepSeek 默认可选模型。"""
    return [
        ModelOption(value="deepseek-chat", label="DeepSeek-Chat", description="通用对话模型（V3），响应快，适合绝大多数问答"),
        ModelOption(value="deepseek-reasoner", label="DeepSeek-Reasoner", description="推理模型（R1），会先思考再作答，适合复杂推理问题"),
    ]


class LLMDefaults(BaseModel):
    """大模型默认推理参数。"""

    temperature: float = 0.3
    top_p: float = 0.8
    max_tokens: int = 2048
    history_rounds: int = 5


class LLMConfig(BaseModel):
    """对话大模型配置（DeepSeek，OpenAI 兼容接口）。"""

    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    default_model: str = "deepseek-chat"
    timeout: int = 120
    models: list[ModelOption] = Field(default_factory=default_model_options)
    defaults: LLMDefaults = Field(default_factory=LLMDefaults)

    def model_values(self) -> list[str]:
        """可选模型的 value 列表。"""
        return [option.value for option in self.models]


class ChunkConfig(BaseModel):
    """默认切块参数。"""

    size: int = 500
    overlap: int = 50


class RetrievalConfig(BaseModel):
    """检索参数。"""

    mode: str = "hybrid"  # dense | hybrid
    top_k: int = 5
    candidate_multiplier: int = 4
    score_threshold: float = 0.2
    hybrid_alpha: float = 0.7


class QueryRewriteConfig(BaseModel):
    """问题改写开关。"""

    enabled: bool = False


class ContextConfig(BaseModel):
    """提示词上下文限制。"""

    max_chars: int = 6000


class RagConfig(BaseModel):
    """RAG 流水线整体参数。"""

    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    query_rewrite: QueryRewriteConfig = Field(default_factory=QueryRewriteConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)


class OCRConfig(BaseModel):
    """图片 OCR 配置（默认 DashScope 多模态模型）。"""

    provider: str = "dashscope"  # dashscope | pytesseract
    model: str = "qwen-vl-ocr-latest"
    base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    api_key: str = ""
    timeout: int = 60
    language: str = "chi_sim+eng"


class PDFConfig(BaseModel):
    """PDF 解析配置。"""

    max_pages: int = 300


class ParserConfig(BaseModel):
    """文档解析配置。"""

    ocr: OCRConfig = Field(default_factory=OCRConfig)
    pdf: PDFConfig = Field(default_factory=PDFConfig)


class CaptchaConfig(BaseModel):
    """图形验证码配置。"""

    length: int = 4
    width: int = 130
    height: int = 44
    expire_seconds: int = 300
    debug_expose: bool = False


class Settings(BaseModel):
    """完整应用配置。"""

    app: AppConfig = Field(default_factory=AppConfig)
    mysql: MySQLConfig = Field(default_factory=MySQLConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)

    project_root: Path = Field(default=PROJECT_ROOT, exclude=True)

    # ---------------- 派生路径 ----------------
    def resolve_path(self, relative: str) -> Path:
        """把配置中的相对路径解析为绝对路径（相对项目根目录）。"""
        path = Path(relative)
        return path if path.is_absolute() else (self.project_root / path)

    @property
    def upload_path(self) -> Path:
        return self.resolve_path(self.app.upload_dir)

    @property
    def log_path(self) -> Path:
        return self.resolve_path(self.app.log_dir)

    @property
    def database_url(self) -> str:
        return self.mysql.url


def _expand_env(value: Any) -> Any:
    """递归展开配置值中的 ${ENV} 占位符。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(
            lambda m: os.getenv(m.group(1), m.group(2) if m.group(2) is not None else ""),
            value,
        )
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _load_dotenv() -> None:
    """加载项目根目录下的 .env（若存在）。"""
    try:
        from dotenv import load_dotenv

        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    except Exception:  # pragma: no cover - dotenv 缺失不影响主流程
        pass


def load_settings(config_file: str | Path | None = None) -> Settings:
    """从配置文件读取配置；文件不存在时使用内置默认值。"""
    _load_dotenv()

    path = Path(config_file or os.getenv("RAG_CONFIG_FILE") or DEFAULT_CONFIG_FILE)
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw = _expand_env(raw)

    settings = Settings(**raw)
    settings.project_root = PROJECT_ROOT

    # ---------- API Key 兜底：配置文件中未填写（或仍是占位值）时读取环境变量 ----------
    if is_placeholder_api_key(settings.llm.api_key):
        env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if env_key:
            settings.llm.api_key = env_key

    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        for section in (settings.embedding, settings.rerank, settings.parser.ocr):
            if is_placeholder_api_key(section.api_key):
                section.api_key = dashscope_key

    if not settings.llm.models:
        settings.llm.models = default_model_options()
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return load_settings()


def reload_settings(config_file: str | Path | None = None) -> Settings:
    """重新加载配置（测试用）。"""
    get_settings.cache_clear()
    settings = load_settings(config_file)
    get_settings.cache_clear()
    _SETTINGS_HOLDER["settings"] = settings
    return settings


_SETTINGS_HOLDER: dict[str, Settings] = {}


def settings() -> Settings:
    """获取当前生效配置（可被测试覆盖）。"""
    if "settings" in _SETTINGS_HOLDER:
        return _SETTINGS_HOLDER["settings"]
    return get_settings()


def override_settings(new_settings: Settings) -> None:
    """覆盖全局配置（测试用）。"""
    _SETTINGS_HOLDER["settings"] = new_settings


def clear_settings_override() -> None:
    """清除配置覆盖，恢复为配置文件（测试用）。"""
    _SETTINGS_HOLDER.clear()
