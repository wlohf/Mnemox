"""应用配置管理"""
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Literal
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
    RATE_LIMIT_MAX_BUCKETS: int = Field(default=10_000, ge=100, le=1_000_000)
    # Forwarded headers are untrusted by default. Public Docker deployment
    # explicitly enables this only because the backend has no public port.
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_HOPS: int = Field(default=0, ge=0, le=5)
    # Public deployments must not let account-configured AI endpoints reach
    # loopback/private infrastructure. Local/desktop development remains
    # allowed unless this is explicitly disabled there too.
    ALLOW_PRIVATE_AI_ENDPOINTS: bool = False
    # RAG embedding configuration is process-wide. Public deployments must
    # explicitly name the account(s) allowed to alter it; an empty list safely
    # disables browser-side mutation while env-based RAG configuration remains
    # available.
    RAG_SETTINGS_ADMIN_USERNAMES: str = ""
    AGENT_LLM_PLANNER_TIMEOUT_SECONDS: float = 12.0
    # Mnemox V2 feature flags remain opt-in. Stage 6 ended 2026-09-04 with
    # Neo4j/Graphiti default-runtime NO-GO. Stage 7 adds an explicit graph
    # backend selector while keeping SQL as the default and canonical source.
    KNOWLEDGE_V2_ENABLED: bool = False
    KNOWLEDGE_LLM_EXTRACTION_ENABLED: bool = False
    ASSOCIATION_V2_ENABLED: bool = False
    ASSOCIATION_V2_SHADOW: bool = False
    ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED: bool = False
    KNOWLEDGE_PATH_ENABLED: bool = False
    KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED: bool = False
    GRAPH_BACKEND: Literal["sql", "neo4j"] = "sql"
    # Stage 7 rollout gate. When Neo4j is selected, reads still require the
    # current user to be admitted by this stable cohort policy and to have a
    # caught-up projection. Explicit user IDs are useful for canary accounts.
    NEO4J_GRAPH_ROLLOUT_PERCENT: int = Field(default=100, ge=0, le=100)
    NEO4J_GRAPH_ROLLOUT_USER_IDS: str = Field(default="", max_length=2_000)
    NEO4J_GRAPH_ENABLED: bool = False
    NEO4J_GRAPH_SHADOW: bool = False
    NEO4J_URI: str = Field(default="bolt://localhost:7687", max_length=500)
    NEO4J_USER: str = Field(default="neo4j", max_length=120)
    NEO4J_PASSWORD: str = Field(default="", max_length=500)
    NEO4J_DATABASE: str = Field(default="neo4j", min_length=1, max_length=120)
    NEO4J_GRAPH_SHADOW_TIMEOUT_SECONDS: float = Field(default=2.0, ge=0.1, le=30.0)
    GRAPHITI_ENABLED: bool = False
    GRAPHITI_SHADOW: bool = False
    GRAPHITI_SHADOW_TIMEOUT_SECONDS: float = Field(default=5.0, ge=0.1, le=60.0)
    # Initial extraction safety and budget defaults. Stage 0 records and
    # validates them but does not start an extraction worker or model call.
    KNOWLEDGE_EXTRACTION_MAX_UNIT_CHARS: int = Field(default=8_000, ge=512, le=50_000)
    KNOWLEDGE_EXTRACTION_MAX_CLAIMS_PER_UNIT: int = Field(default=12, ge=1, le=100)
    KNOWLEDGE_CLAIM_MAX_CHARS: int = Field(default=500, ge=80, le=2_000)
    KNOWLEDGE_EXTRACTION_MAX_OUTPUT_CHARS: int = Field(default=12_000, ge=1_000, le=100_000)
    KNOWLEDGE_EXTRACTION_TIMEOUT_SECONDS: float = Field(default=30.0, ge=1.0, le=300.0)
    KNOWLEDGE_LLM_MAX_CALLS_PER_RUN: int = Field(default=64, ge=1, le=1_000)
    KNOWLEDGE_LLM_MAX_ESTIMATED_TOKENS_PER_RUN: int = Field(
        default=64_000,
        ge=1_024,
        le=10_000_000,
    )
    KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER: int = Field(
        default=256_000,
        ge=1_024,
        le=50_000_000,
    )
    KNOWLEDGE_EXTRACTION_WORKER_POLL_INTERVAL_SECONDS: float = Field(
        default=2.0,
        gt=0,
        le=60,
    )
    KNOWLEDGE_EXTRACTION_WORKER_BATCH_SIZE: int = Field(default=4, ge=1, le=100)
    KNOWLEDGE_EXTRACTION_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    KNOWLEDGE_EXTRACTION_LEASE_SECONDS: int = Field(default=120, ge=30, le=3600)
    KNOWLEDGE_EXTRACTION_RETRY_BASE_SECONDS: float = Field(default=5.0, ge=0, le=3600)
    # Stage 3 keeps knowledge vectors disposable and independently switchable.
    # Exact canonical/alias resolution does not depend on these settings.
    KNOWLEDGE_EMBEDDING_ENABLED: bool = False
    KNOWLEDGE_CHROMA_COLLECTION_NAME: str = Field(
        default="mnemox_knowledge",
        min_length=1,
        max_length=120,
    )
    KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS: float = Field(default=20.0, ge=1.0, le=300.0)
    KNOWLEDGE_RESOLUTION_TOP_K: int = Field(default=5, ge=1, le=50)
    KNOWLEDGE_RESOLUTION_LEXICAL_THRESHOLD: float = Field(default=0.45, ge=0.0, le=1.0)
    KNOWLEDGE_RESOLUTION_MAX_MENTIONS_PER_CLAIM: int = Field(default=8, ge=1, le=50)
    # Stage 5 sparse backend. Auto selects SQLite FTS5 or PostgreSQL native FTS
    # and keeps query-time reference fallback; explicit reference is the rollback.
    KNOWLEDGE_SPARSE_BACKEND: str = Field(
        default="auto",
        pattern="^(auto|reference|sqlite_fts5|postgres_fts)$",
    )
    # Semantic reranking is optional and must never block Association V2.
    KNOWLEDGE_RERANKER_MODE: str = Field(default="feature", pattern="^(feature|llm)$")
    KNOWLEDGE_RERANKER_MODEL: str = Field(default="", max_length=160)
    KNOWLEDGE_RERANKER_TIMEOUT_SECONDS: float = Field(default=3.0, ge=0.1, le=30.0)
    # Expensive canonical signature verification is available for diagnostics;
    # normal lifecycle uses write-time dirty markers plus SQL display revalidation.
    KNOWLEDGE_SPARSE_VERIFY_SIGNATURE: bool = False
    KNOWLEDGE_PROJECTION_WORKER_POLL_INTERVAL_SECONDS: float = Field(
        default=2.0,
        gt=0,
        le=60,
    )
    KNOWLEDGE_PROJECTION_WORKER_BATCH_SIZE: int = Field(default=20, ge=1, le=200)
    KNOWLEDGE_PROJECTION_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    KNOWLEDGE_PROJECTION_LEASE_SECONDS: int = Field(default=120, ge=30, le=3600)
    KNOWLEDGE_PROJECTION_RETRY_BASE_SECONDS: float = Field(default=5.0, ge=0, le=3600)
    # Observation-only A/A instrumentation. Both variants keep identical
    # policy behavior until coverage and attribution are independently proven.
    COACH_INTERVENTION_EXPERIMENT_ENABLED: bool = False
    COACH_INTERVENTION_EXPERIMENT_ID: str = Field(
        default="coach_intervention_aa_v1",
        min_length=1,
        max_length=80,
    )
    COACH_INTERVENTION_EXPERIMENT_SPLIT_PERCENT: int = Field(default=50, ge=1, le=99)
    
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
    # Server-side proactive Coach scan. It is safe to keep enabled because no
    # user is evaluated until that user explicitly turns on proactive Coach.
    AGENT_RUNTIME_SCHEDULER_ENABLED: bool = True
    AGENT_RUNTIME_POLL_INTERVAL_SECONDS: float = Field(default=300.0, ge=30, le=3600)
    AGENT_RUNTIME_BATCH_SIZE: int = Field(default=50, ge=1, le=500)
    AGENT_RUNTIME_USER_INTERVAL_SECONDS: int = Field(default=21600, ge=300, le=86400)
    AGENT_RUNTIME_RETRY_INTERVAL_SECONDS: int = Field(default=900, ge=60, le=21600)
    AGENT_RUNTIME_USER_TIMEOUT_SECONDS: float = Field(default=60.0, ge=1.0, le=600.0)
    AGENT_KERNEL_LEASE_SECONDS: int = Field(default=120, ge=60, le=600)
    AGENT_KERNEL_MAX_MODEL_CALLS: int = Field(default=7, ge=1, le=9)
    AGENT_KERNEL_MAX_ESTIMATED_TOKENS: int = Field(default=32000, ge=512, le=1000000)
    AGENT_KERNEL_DAILY_MODEL_CALLS_PER_USER: int = Field(default=30, ge=1, le=1000)
    AGENT_KERNEL_DAILY_ESTIMATED_TOKENS_PER_USER: int = Field(
        default=128000,
        ge=512,
        le=10000000,
    )
    # Obsidian vault 同步根目录白名单；生产环境必须配置后才允许 vault 同步（决策 D6）
    OBSIDIAN_VAULT_ROOT: str = ""
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    AI_KEY_ENCRYPTION_SECRET: str = ""
    ACCESS_TOKEN_EXPIRE_HOURS: int = Field(default=12, ge=1, le=168)
    AUTH_COOKIE_NAME: str = "mnemox_access_token"
    AUTH_PASSWORD_MIN_LENGTH: int = Field(default=12, ge=8, le=128)
    AUTH_ACCOUNT_MAX_FAILURES: int = Field(default=5, ge=3, le=20)
    AUTH_ACCOUNT_WINDOW_SECONDS: int = Field(default=900, ge=60, le=86_400)
    MAX_IMAGE_PIXELS: int = Field(default=40_000_000, ge=1_000_000, le=250_000_000)
    MAX_OBSIDIAN_ATTACHMENTS: int = Field(default=20, ge=1, le=200)
    MATERIAL_EXTRACT_MAX_CHARS: int = Field(default=2_000_000, ge=10_000, le=20_000_000)
    MATERIAL_EXTRACT_TIMEOUT_SECONDS: float = Field(default=20.0, ge=2.0, le=300.0)
    MATERIAL_ARCHIVE_MAX_UNCOMPRESSED_MB: int = Field(default=50, ge=5, le=500)

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
