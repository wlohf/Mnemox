"""数据库连接和会话管理"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings


def _is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _sqlite_connect_args() -> dict:
    if not _is_sqlite_url(settings.DATABASE_URL):
        return {}
    return {"timeout": 30}


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()

# 创建异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args=_sqlite_connect_args(),
)

if _is_sqlite_url(settings.DATABASE_URL):
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

# 创建会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 声明基类
Base = declarative_base()


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _is_sqlite() -> bool:
    return _is_sqlite_url(settings.DATABASE_URL)


async def _run_lightweight_migrations(conn):
    """Add new columns to existing tables if they don't exist (SQLite-safe)."""
    if not _is_sqlite():
        return  # PostgreSQL uses Alembic

    import sqlalchemy

    # user_id migrations for all user-scoped tables
    user_id_tables = [
        "materials", "goals", "chat_projects", "chat_conversations",
        "notes", "pomodoros", "daily_stats", "study_sessions",
        "questions", "wrong_questions", "review_schedule",
        "ai_provider_settings", "ai_routing_settings", "ai_search_settings", "web_search_cache",
        "user_memories", "conversation_summaries", "daily_plans",
        "agent_jobs", "agent_execution_logs", "coach_skill_stats",
    ]

    for table in user_id_tables:
        try:
            result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result}
            if "user_id" not in existing:
                await conn.execute(sqlalchemy.text(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
                ))
        except Exception:
            pass  # Table may not exist yet

    # Other column migrations
    # NOTE: SQLite ALTER TABLE ADD COLUMN requires constant defaults.
    # CURRENT_TIMESTAMP is NOT allowed — use NULL or a literal string instead,
    # then backfill with UPDATE afterwards.
    other_migrations = [
        ("user_memories", "material_id", "INTEGER"),
        ("user_memories", "memory_type", "VARCHAR(20) DEFAULT 'semantic'"),
        ("user_memories", "source_type", "VARCHAR(50)"),
        ("user_memories", "source_id", "VARCHAR(100)"),
        ("user_memories", "evidence", "TEXT"),
        ("user_memories", "expires_at", "DATETIME"),
        ("user_memories", "review_status", "VARCHAR(20) DEFAULT 'confirmed'"),
        ("conversation_summaries", "questions_asked", "TEXT"),
        ("conversation_summaries", "confusions", "TEXT"),
        ("conversation_summaries", "misconceptions", "TEXT"),
        ("conversation_summaries", "review_prompts", "TEXT"),
        ("conversation_summaries", "reflection_turn_count", "INTEGER DEFAULT 0"),
        ("goals", "updated_at", "DATETIME"),
        ("tasks", "updated_at", "DATETIME"),
        ("notes", "note_type", "VARCHAR(20)"),
        ("notes", "material_id", "INTEGER"),
        ("notes", "chapter_id", "INTEGER"),
        ("notes", "tags", "TEXT"),
        ("notes", "updated_at", "DATETIME"),
        ("materials", "file_hash", "VARCHAR(64)"),
        ("materials", "content_hash", "VARCHAR(64)"),
        ("materials", "content_status", "VARCHAR(20) DEFAULT 'pending'"),
        # P2: 错题三档标签 + 掌握度评分
        ("wrong_questions", "knowledge_point", "VARCHAR(100)"),
        ("wrong_questions", "recall_difficulty", "VARCHAR(20)"),
        ("wrong_questions", "mastery_score", "REAL DEFAULT 0.0"),
        ("tasks", "parent_task_id", "INTEGER"),
        ("pomodoros", "task_id", "INTEGER"),
        ("agent_jobs", "payload", "JSON"),
        ("agent_jobs", "result", "JSON"),
        ("agent_jobs", "summary", "TEXT"),
        ("agent_jobs", "updated_at", "DATETIME"),
        ("agent_execution_logs", "metadata", "JSON"),
        ("ai_provider_settings", "available_models", "TEXT DEFAULT '[]'"),
        ("ai_provider_settings", "max_context_tokens", "INTEGER"),
        ("ai_provider_settings", "max_output_tokens", "INTEGER"),
        ("ai_routing_settings", "model", "VARCHAR(100)"),
        ("learning_events", "source", "VARCHAR(50)"),
        ("learning_events", "dedupe_key", "VARCHAR(160)"),
        ("learning_events", "goal_id", "INTEGER"),
        ("learning_events", "task_id", "INTEGER"),
        ("learning_events", "note_id", "INTEGER"),
        ("learning_events", "wrong_question_id", "INTEGER"),
    ]

    for table, column, col_type in other_migrations:
        try:
            result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result}
            if column not in existing:
                await conn.execute(sqlalchemy.text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                ))
        except Exception:
            pass

    try:
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_learning_events_user_type_time "
            "ON learning_events(user_id, event_type, timestamp)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_learning_events_dedupe_key "
            "ON learning_events(dedupe_key)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_user_memories_user_review_status "
            "ON user_memories(user_id, review_status, status)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_user_memories_user_source "
            "ON user_memories(user_id, source_type, source_id)"
        ))
    except Exception:
        pass

    # Backfill updated_at from created_at for existing rows
    for table in ("goals", "tasks", "notes"):
        try:
            await conn.execute(sqlalchemy.text(
                f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL"
            ))
        except Exception:
            pass


async def init_db():
    """初始化数据库（创建所有表）"""
    import logging
    import app.models  # noqa: F401

    _logger = logging.getLogger(__name__)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_lightweight_migrations(conn)

    # 警告：生产环境应使用 Alembic 管理迁移
    if not _is_sqlite():
        _logger.warning(
            "❗ 生产环境检测到手写迁移逻辑。建议使用 Alembic 管理 schema 迁移，"
            "避免多环境 schema 漂移和数据丢失风险。"
        )
    else:
        _logger.info(
            "📝 开发环境使用 SQLite + 轻量迁移。生产部署前请配置 Alembic。"
        )

async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
