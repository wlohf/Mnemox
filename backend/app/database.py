"""数据库连接和会话管理"""
from sqlalchemy import event, text
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
        cursor.execute("PRAGMA foreign_keys=ON")
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


def _alembic_head_revision() -> str:
    """Read the bundled Alembic head without opening another database connection."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("No Alembic head revision is available for the production schema.")
    return str(head)


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
        # FSRS 调度字段（决策 D1，legacy SM-2 字段保留过渡）
        ("anki_cards", "stability", "REAL"),
        ("anki_cards", "difficulty", "REAL"),
        ("anki_cards", "fsrs_state", "INTEGER"),
        ("anki_cards", "fsrs_step", "INTEGER"),
        ("anki_cards", "last_review_at", "DATETIME"),
        ("review_schedule", "stability", "REAL"),
        ("review_schedule", "difficulty", "REAL"),
        ("review_schedule", "fsrs_state", "INTEGER"),
        ("review_schedule", "fsrs_step", "INTEGER"),
        ("review_schedule", "last_review_at", "DATETIME"),
        # 概念图谱（决策 D1/D2）：错题挂概念外键
        ("wrong_questions", "concept_id", "INTEGER"),
        # Obsidian 增量同步（决策 D6）：笔记外部来源路径
        ("notes", "source_path", "VARCHAR(500)"),
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
            "DROP INDEX IF EXISTS ix_user_memories_user_review_status"
        ))
        await conn.execute(sqlalchemy.text(
            "DROP INDEX IF EXISTS ix_user_memories_user_source"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_user_memories_review_status "
            "ON user_memories(review_status)"
        ))
    except Exception:
        pass

    # The old select-then-insert dedupe allowed concurrent requests to append
    # duplicate ledger events. Preserve historical rows but clear duplicate
    # keys before introducing the durable user/type/key uniqueness contract.
    try:
        await conn.execute(sqlalchemy.text(
            """
            WITH ranked_events AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, event_type, dedupe_key
                        ORDER BY id ASC
                    ) AS duplicate_rank
                FROM learning_events
                WHERE dedupe_key IS NOT NULL
            )
            UPDATE learning_events
            SET dedupe_key = NULL
            WHERE id IN (
                SELECT id FROM ranked_events WHERE duplicate_rank > 1
            )
            """
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_events_user_type_dedupe "
            "ON learning_events(user_id, event_type, dedupe_key) "
            "WHERE dedupe_key IS NOT NULL"
        ))
    except Exception as exc:
        raise RuntimeError("SQLite learning-event dedupe migration failed") from exc

    # Backfill updated_at from created_at for existing rows
    for table in ("goals", "tasks", "notes"):
        try:
            await conn.execute(sqlalchemy.text(
                f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL"
            ))
        except Exception:
            pass

    # Existing local SQLite databases do not run Alembic. Track this one-time
    # backfill explicitly so concepts created after rollout never receive a
    # synthetic legacy row on a later application restart.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS mnemox_lightweight_migrations (
                revision VARCHAR(50) PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))
        marker = await conn.scalar(sqlalchemy.text(
            "SELECT 1 FROM mnemox_lightweight_migrations "
            "WHERE revision = '20260804_01' LIMIT 1"
        ))
        if marker is None:
            await conn.execute(sqlalchemy.text(
                """
                INSERT INTO learner_evidence (
                    user_id, concept_id, evidence_type, evidence_category, dimension,
                    score, reliability, source_event_id, source_type, source_id,
                    observed_at, model_version, payload_version, payload, created_at
                )
                SELECT
                    c.user_id, c.id, 'legacy_mastery', 'legacy', 'overall',
                    CASE
                        WHEN c.mastery < 0 THEN 0.0
                        WHEN c.mastery > 100 THEN 1.0
                        ELSE c.mastery / 100.0
                    END,
                    0.35, NULL, 'legacy', c.name_normalized,
                    COALESCE(c.updated_at, c.created_at, CURRENT_TIMESTAMP),
                    'legacy-concept-mastery-v1', 1,
                    '{"field":"concepts.mastery","scale":"0-100"}',
                    CURRENT_TIMESTAMP
                FROM concepts AS c
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM learner_evidence AS e
                    WHERE e.user_id = c.user_id
                      AND e.concept_id = c.id
                      AND e.evidence_type = 'legacy_mastery'
                      AND e.source_type = 'legacy'
                )
                """
            ))
            await conn.execute(sqlalchemy.text(
                """
                INSERT INTO user_concept_state (
                    user_id, concept_id, mastery_estimate, confidence, forgetting_risk,
                    mastery_dimensions, common_error_type, last_evidence_at,
                    last_reviewed_at, next_review_at, manual_override, source_event_id,
                    reliability, model_version, explanation_summary, created_at, updated_at
                )
                SELECT
                    c.user_id, c.id,
                    CASE
                        WHEN c.mastery < 0 THEN 0.0
                        WHEN c.mastery > 100 THEN 100.0
                        ELSE c.mastery
                    END,
                    0.35, 0.5, '{}', NULL,
                    COALESCE(c.updated_at, c.created_at, CURRENT_TIMESTAMP),
                    NULL, NULL, NULL, NULL, 0.35,
                    'legacy-concept-mastery-v1',
                    '{"basis":"legacy Concept.mastery migration","recomputable":"true"}',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM concepts AS c
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM user_concept_state AS s
                    WHERE s.user_id = c.user_id AND s.concept_id = c.id
                )
                """
            ))
            await conn.execute(sqlalchemy.text(
                "INSERT INTO mnemox_lightweight_migrations (revision) VALUES ('20260804_01')"
        ))
    except Exception as exc:
        raise RuntimeError(
            "SQLite learner-model legacy backfill failed; back up the database "
            "and reconcile its schema before restarting."
        ) from exc

    # Projection outbox is additive and must be present for local SQLite too.
    # ``create_all`` handles fresh databases; this DDL handles databases that
    # predate the model without invoking a destructive table rebuild.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS projection_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                concept_id INTEGER NULL,
                source_event_id INTEGER NOT NULL,
                idempotency_key VARCHAR(200) NOT NULL,
                projection_type VARCHAR(60) NOT NULL DEFAULT 'learner_state',
                model_version VARCHAR(50) NOT NULL DEFAULT 'projection-outbox-v1',
                payload_version INTEGER NOT NULL DEFAULT 1,
                payload JSON NOT NULL DEFAULT '{}',
                occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                locked_at DATETIME NULL,
                processed_at DATETIME NULL,
                last_error TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_projection_outbox_user_key UNIQUE (user_id, idempotency_key),
                CONSTRAINT ck_projection_outbox_status CHECK (status IN ('pending','processing','processed','failed')),
                CONSTRAINT ck_projection_outbox_attempts CHECK (attempts >= 0),
                CONSTRAINT ck_projection_outbox_payload_version CHECK (payload_version >= 1),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                FOREIGN KEY(source_event_id) REFERENCES learning_events(id) ON DELETE CASCADE
            )
            """
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_pending ON projection_outbox(status, available_at, id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_user_concept_time ON projection_outbox(user_id, concept_id, occurred_at)"
        ))
    except Exception as exc:
        raise RuntimeError("SQLite projection outbox migration failed") from exc


async def init_db():
    """Initialize SQLite development storage without mutating production schema."""
    import logging
    import app.models  # noqa: F401

    _logger = logging.getLogger(__name__)

    if not _is_sqlite():
        async with engine.connect() as conn:
            try:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                current_versions = {str(version) for version in result.scalars().all()}
            except Exception as exc:
                raise RuntimeError(
                    "PostgreSQL schema is not managed by Alembic yet. "
                    "Run `python backend/run_migrations.py` before starting the application."
                ) from exc
        expected_head = _alembic_head_revision()
        if current_versions != {expected_head}:
            raise RuntimeError(
                "PostgreSQL schema revision is not current. "
                "Run `python backend/run_migrations.py` before starting the application."
            )
        _logger.info("PostgreSQL schema is managed by Alembic; skipping create_all.")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_lightweight_migrations(conn)

    _logger.info("SQLite development database initialized with lightweight migrations.")

async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
