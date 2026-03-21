"""应用配置管理"""
from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import List
from pathlib import Path
import os
import warnings

# 项目根目录（config.py 位于 backend/app/config.py）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "study.db"
_DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"
_DEFAULT_PG_URL = "postgresql+asyncpg://postgres:password@localhost:5432/study_assistant"

# Use PostgreSQL when DB_PASSWORD env is set (production), otherwise SQLite (local dev)
_DEFAULT_DB_URL = _DEFAULT_PG_URL if os.environ.get("DB_PASSWORD") else _DEFAULT_SQLITE_URL


class Settings(BaseSettings):
    """应用配置"""

    # 数据库配置（默认使用项目根目录/data/study.db 的绝对路径）
    DATABASE_URL: str = _DEFAULT_DB_URL
    
    # AI 提供商配置
    DEFAULT_AI_PROVIDER: str = "openai"
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # OpenCode (optional defaults for OpenAI provider)
    OPENCODE_API_KEY_GGBOOM: str = ""
    OPENCODE_MODEL_GGBOOM: str = "gpt-5.2-codex"
    OPENCODE_BASE_URL_GGBOOM: str = "https://ai.qaq.al/v1"
    
    # Claude
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-5-20251101"
    CLAUDE_BASE_URL: str = "https://api.anthropic.com"
    
    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-pro"
    
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
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

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

        return self


# 全局配置实例
settings = Settings()

# 启动时校验 SECRET_KEY
if settings.SECRET_KEY == "change-me-in-production":
    warnings.warn(
        "\n⚠️  CRITICAL: SECRET_KEY 仍为默认值 'change-me-in-production'！"
        "\n   请在 .env 文件中设置一个安全的随机密钥。"
        "\n   例如: SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')\n",
        stacklevel=1,
    )
