"""应用配置管理"""
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from pathlib import Path
import os
import warnings

from app.utils.paths import resolve_runtime_path

# 项目根目录（config.py 位于 backend/app/config.py）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = resolve_runtime_path("study.db")
_DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"
_DEFAULT_PG_URL = "postgresql+asyncpg://postgres:password@localhost:5432/study_assistant"
_DEFAULT_UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/wlohf/Mnemox/main/release-manifest/latest.json"

# Use PostgreSQL when DB_PASSWORD env is set (production), otherwise SQLite (local dev)
_DEFAULT_DB_URL = _DEFAULT_PG_URL if os.environ.get("DB_PASSWORD") else _DEFAULT_SQLITE_URL


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库配置（默认使用项目根目录/data/study.db 的绝对路径）
    DATABASE_URL: str = _DEFAULT_DB_URL
    
    # AI 提供商配置
    DEFAULT_AI_PROVIDER: str = "openai"
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # OpenAI-compatible custom endpoint (optional; disabled unless explicitly configured)
    OPENCODE_API_KEY_GGBOOM: str = ""
    OPENCODE_MODEL_GGBOOM: str = ""
    OPENCODE_BASE_URL_GGBOOM: str = ""
    
    # Claude
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-5-20251101"
    CLAUDE_BASE_URL: str = "https://api.anthropic.com"
    
    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    
    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    # Qwen
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = "qwen-turbo"
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # RAG 知识库配置（LlamaIndex + ChromaDB）
    RAG_ENABLED: bool = True
    RAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 64
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3
    RAG_COLLECTION_NAME: str = "study_materials"
    SMALL_MATERIAL_THRESHOLD: int = 4000
    MATERIAL_UPLOAD_MAX_MB: int = 200
    IMAGE_UPLOAD_MAX_MB: int = 50
    MAX_REQUEST_BODY_MB: int = 20
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_PER_MINUTE: int = 120
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    AGENT_LLM_PLANNER_TIMEOUT_SECONDS: float = 12.0
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    # Durable projection outbox consumer. Each application instance runs one
    # worker; PostgreSQL row locking coordinates concurrent instances.
    OUTBOX_WORKER_ENABLED: bool = True
    OUTBOX_WORKER_POLL_INTERVAL_SECONDS: float = Field(default=2.0, gt=0, le=60)
    OUTBOX_WORKER_BATCH_SIZE: int = Field(default=50, ge=1, le=500)
    OUTBOX_WORKER_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    OUTBOX_WORKER_RETRY_POLICY_VERSION: int = Field(default=1, ge=1, le=1_000_000)
    # Deployment-visible prefix only. The application adds a unique runtime
    # suffix before persisting the heartbeat primary key.
    OUTBOX_WORKER_ID: str = ""
    OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS: float = Field(default=15.0, gt=0, le=300)
    OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS: int = Field(default=45, ge=5, le=3600)
    OUTBOX_ALERT_BACKLOG_COUNT_THRESHOLD: int = Field(default=100, ge=1, le=100000)
    OUTBOX_ALERT_BACKLOG_AGE_SECONDS: int = Field(default=900, ge=1, le=604800)
    OUTBOX_ALERT_TERMINAL_FAILURE_THRESHOLD: int = Field(default=1, ge=1, le=100000)
    OUTBOX_ALERT_STALE_PROCESSING_THRESHOLD: int = Field(default=1, ge=1, le=100000)
    # Kept empty by default: the internal Prometheus endpoint rejects every
    # request until the deployment provides a dedicated operations secret.
    OUTBOX_OPS_TOKEN: str = ""
    # Obsidian vault 同步根目录白名单；生产环境必须配置后才允许 vault 同步（决策 D6）
    OBSIDIAN_VAULT_ROOT: str = ""
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    AI_KEY_ENCRYPTION_SECRET: str = ""
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # App Update
    APP_VERSION: str = "1.3.0"
    APP_UPDATE_MANIFEST_URL: str = _DEFAULT_UPDATE_MANIFEST_URL

    # Local packaged app
    SERVE_FRONTEND: bool = False
    FRONTEND_DIST_DIR: str = ""
    
    @model_validator(mode="after")
    def apply_opencode_defaults(self):
        if not self.OPENAI_API_KEY and self.OPENCODE_API_KEY_GGBOOM:
            self.OPENAI_API_KEY = self.OPENCODE_API_KEY_GGBOOM

        if (
            (not self.OPENAI_BASE_URL or self.OPENAI_BASE_URL == "https://api.openai.com/v1")
            and self.OPENCODE_BASE_URL_GGBOOM
        ):
            self.OPENAI_BASE_URL = self.OPENCODE_BASE_URL_GGBOOM

        if (
            (not self.OPENAI_MODEL or self.OPENAI_MODEL == "gpt-4")
            and self.OPENCODE_MODEL_GGBOOM
        ):
            self.OPENAI_MODEL = self.OPENCODE_MODEL_GGBOOM

        if not self.APP_UPDATE_MANIFEST_URL.strip():
            self.APP_UPDATE_MANIFEST_URL = _DEFAULT_UPDATE_MANIFEST_URL

        if self.OUTBOX_WORKER_ENABLED:
            heartbeat_headroom = max(
                5.0,
                self.OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS * 0.25,
            )
            minimum_heartbeat_ttl = (
                self.OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS + heartbeat_headroom
            )
            if self.OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS < minimum_heartbeat_ttl:
                raise ValueError(
                    "OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS must be at least "
                    "the heartbeat interval plus scheduling headroom "
                    f"({minimum_heartbeat_ttl:g}s)"
                )

        return self


# 全局配置实例
settings = Settings()

# 启动时校验 SECRET_KEY：开发环境警告，生产环境拒绝启动。
_INSECURE_SECRET_KEY = "change-me-in-production"
_secret_key = settings.SECRET_KEY.strip()
_is_production = settings.ENVIRONMENT.lower() in {"prod", "production"} or bool(os.environ.get("DB_PASSWORD"))
if settings.SECRET_KEY == _INSECURE_SECRET_KEY or len(_secret_key) < 32:
    _secret_message = (
        "\n⚠️  CRITICAL: SECRET_KEY 未安全配置！"
        "\n   请在 .env 文件中设置一个至少 32 字符的随机密钥。"
        "\n   例如: SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')\n"
    )
    if _is_production:
        raise RuntimeError(_secret_message)
    warnings.warn(_secret_message, stacklevel=1)
