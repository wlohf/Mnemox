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
        ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "login_failed_window_started_at", "DATETIME"),
        ("users", "login_locked_until", "DATETIME"),
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
        ("pomodoros", "coach_action_attempt_id", "VARCHAR(40)"),
        ("agent_jobs", "payload", "JSON"),
        ("agent_jobs", "result", "JSON"),
        ("agent_jobs", "summary", "TEXT"),
        ("agent_jobs", "updated_at", "DATETIME"),
        ("agent_jobs", "scenario", "VARCHAR(100)"),
        ("agent_jobs", "run_key", "VARCHAR(160)"),
        ("agent_jobs", "attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ("agent_jobs", "scheduled_for", "DATETIME"),
        ("agent_jobs", "started_at", "DATETIME"),
        ("agent_jobs", "finished_at", "DATETIME"),
        ("agent_jobs", "cancel_requested_at", "DATETIME"),
        ("agent_jobs", "resumed_from_job_id", "VARCHAR(32)"),
        ("agent_jobs", "lease_owner", "VARCHAR(64)"),
        ("agent_jobs", "lease_expires_at", "DATETIME"),
        ("agent_jobs", "checkpoint", "JSON"),
        ("agent_execution_logs", "metadata", "JSON"),
        # Coach 行动生命周期：旧 SQLite 数据库也需要区分采纳、开始和放弃。
        ("coach_skill_stats", "started_count", "INTEGER NOT NULL DEFAULT 0"),
        ("coach_skill_stats", "abandoned_count", "INTEGER NOT NULL DEFAULT 0"),
        ("coach_preferences", "proactive_last_evaluated_at", "DATETIME"),
        ("coach_preferences", "proactive_next_evaluate_at", "DATETIME"),
        ("coach_preferences", "proactive_failure_count", "INTEGER NOT NULL DEFAULT 0"),
        ("coach_preferences", "time_zone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
        ("ai_provider_settings", "available_models", "TEXT DEFAULT '[]'"),
        ("ai_provider_settings", "max_context_tokens", "INTEGER"),
        ("ai_provider_settings", "max_output_tokens", "INTEGER"),
        ("ai_provider_settings", "input_price_per_million", "REAL"),
        ("ai_provider_settings", "output_price_per_million", "REAL"),
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
        ("concepts", "review_status", "VARCHAR(20) NOT NULL DEFAULT 'confirmed'"),
        ("concept_edges", "review_status", "VARCHAR(20) NOT NULL DEFAULT 'confirmed'"),
        ("user_concept_state", "attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ("user_concept_state", "correct_count", "INTEGER NOT NULL DEFAULT 0"),
        ("user_concept_state", "hint_count", "INTEGER NOT NULL DEFAULT 0"),
        # Obsidian 增量同步（决策 D6）：笔记外部来源路径
        ("notes", "source_path", "VARCHAR(500)"),
        # Obsidian Vault 一致性：稳定文件身份、缺失状态和冲突候选。
        ("notes", "source_vault_id", "VARCHAR(160)"),
        ("notes", "source_file_id", "VARCHAR(160)"),
        ("notes", "source_sync_hash", "VARCHAR(64)"),
        ("notes", "source_sync_state", "VARCHAR(20)"),
        ("notes", "source_conflict_title", "VARCHAR(200)"),
        ("notes", "source_conflict_content", "TEXT"),
        ("notes", "source_conflict_hash", "VARCHAR(64)"),
        ("notes", "source_conflict_vault_id", "VARCHAR(160)"),
        ("notes", "source_conflict_file_id", "VARCHAR(160)"),
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
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_notes_source_vault_id "
            "ON notes(source_vault_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_notes_source_file_id "
            "ON notes(source_file_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_notes_source_sync_state "
            "ON notes(source_sync_state)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notes_source_identity "
            "ON notes(user_id, source_vault_id, source_file_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_jobs_user_run_key "
            "ON agent_jobs(user_id, run_key)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_jobs_scenario ON agent_jobs(scenario)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_jobs_scheduled_for ON agent_jobs(scheduled_for)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_jobs_resumed_from_job_id ON agent_jobs(resumed_from_job_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_jobs_lease_expires_at ON agent_jobs(lease_expires_at)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_coach_preferences_proactive_next_evaluate_at "
            "ON coach_preferences(proactive_next_evaluate_at)"
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
                dead_lettered_at DATETIME NULL,
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
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(projection_outbox)"))
        outbox_columns = {row[1] for row in result}
        if "dead_lettered_at" not in outbox_columns:
            await conn.execute(sqlalchemy.text(
                "ALTER TABLE projection_outbox ADD COLUMN dead_lettered_at DATETIME"
            ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_pending ON projection_outbox(status, available_at, id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_user_concept_time ON projection_outbox(user_id, concept_id, occurred_at)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_dead_lettered_at "
            "ON projection_outbox(dead_lettered_at)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_operations_active "
            "ON projection_outbox(status, available_at, locked_at, attempts) "
            "WHERE status IN ('pending', 'processing', 'failed')"
        ))
        # Historical rows do not retain the configured retry cap. Request and
        # worker paths persist DLQ markers only after reconciling the active
        # deployment cap.
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS projection_outbox_worker_heartbeats (
                worker_id VARCHAR(120) NOT NULL PRIMARY KEY,
                started_at DATETIME NOT NULL,
                last_heartbeat_at DATETIME NOT NULL,
                last_poll_at DATETIME NULL,
                last_success_at DATETIME NULL,
                last_error_at DATETIME NULL,
                last_projection_failure_at DATETIME NULL,
                stopped_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_projection_outbox_worker_heartbeats_last_heartbeat_at "
            "ON projection_outbox_worker_heartbeats(last_heartbeat_at)"
        ))
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS projection_outbox_retry_policy (
                id INTEGER NOT NULL PRIMARY KEY,
                max_attempts INTEGER NOT NULL,
                policy_version INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_projection_outbox_retry_policy_singleton CHECK (id = 1),
                CONSTRAINT ck_projection_outbox_retry_policy_attempts CHECK (max_attempts >= 1),
                CONSTRAINT ck_projection_outbox_retry_policy_version CHECK (policy_version >= 1)
            )
            """
        ))
    except Exception as exc:
        raise RuntimeError("SQLite projection outbox operations migration failed") from exc

    # Memory declarations are an additive audit table. Fresh local databases
    # receive it through metadata; this DDL upgrades older local SQLite files
    # without rebuilding or overwriting their current user memories.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS memory_declarations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_id INTEGER NOT NULL,
                subject VARCHAR(160) NOT NULL,
                predicate VARCHAR(80) NOT NULL,
                fact_key VARCHAR(100) NOT NULL DEFAULT '',
                value TEXT NOT NULL,
                valid_from DATETIME NOT NULL,
                valid_to DATETIME NULL,
                observed_at DATETIME NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8,
                review_status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
                source_event_id INTEGER NULL,
                source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
                source_id VARCHAR(160) NULL,
                evidence TEXT NULL,
                created_by VARCHAR(30) NOT NULL DEFAULT 'user',
                model_version VARCHAR(80) NULL,
                supersedes_id INTEGER NULL,
                conflicts_with_id INTEGER NULL,
                resolution_reason VARCHAR(255) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(memory_id) REFERENCES user_memories(id) ON DELETE CASCADE,
                FOREIGN KEY(supersedes_id) REFERENCES memory_declarations(id) ON DELETE SET NULL
            )
            """
        ))
        declaration_columns = {
            row[1]
            for row in await conn.execute(sqlalchemy.text("PRAGMA table_info(memory_declarations)"))
        }
        for column, column_type in (
            ("fact_key", "VARCHAR(100) NOT NULL DEFAULT ''"),
            ("conflicts_with_id", "INTEGER"),
            ("resolution_reason", "VARCHAR(255)"),
        ):
            if column not in declaration_columns:
                await conn.execute(
                    sqlalchemy.text(f"ALTER TABLE memory_declarations ADD COLUMN {column} {column_type}")
                )
        await conn.execute(sqlalchemy.text(
            "UPDATE memory_declarations SET fact_key = "
            "COALESCE((SELECT user_memories.memory_key FROM user_memories "
            "WHERE user_memories.id = memory_declarations.memory_id "
            "AND user_memories.user_id = memory_declarations.user_id), '') "
            "WHERE fact_key = ''"
        ))
        await conn.execute(sqlalchemy.text(
            "WITH ranked_facts AS ("
            "SELECT memory_declarations.id, ROW_NUMBER() OVER ("
            "PARTITION BY memory_declarations.user_id, memory_declarations.fact_key "
            "ORDER BY COALESCE(user_memories.is_locked, 0) DESC, "
            "memory_declarations.observed_at DESC, memory_declarations.id DESC"
            ") AS duplicate_rank FROM memory_declarations "
            "LEFT JOIN user_memories ON user_memories.id = memory_declarations.memory_id "
            "AND user_memories.user_id = memory_declarations.user_id "
            "WHERE memory_declarations.review_status = 'confirmed' "
            "AND memory_declarations.valid_to IS NULL AND memory_declarations.fact_key != ''"
            ") UPDATE memory_declarations SET review_status = 'superseded', "
            "valid_to = CURRENT_TIMESTAMP, resolution_reason = 'migration_reconciled_duplicate_fact' "
            "WHERE id IN (SELECT id FROM ranked_facts WHERE duplicate_rank > 1)"
        ))
        await conn.execute(sqlalchemy.text(
            "UPDATE user_memories SET status = 'superseded', review_status = 'superseded' "
            "WHERE EXISTS (SELECT 1 FROM memory_declarations "
            "WHERE memory_declarations.memory_id = user_memories.id "
            "AND memory_declarations.user_id = user_memories.user_id "
            "AND memory_declarations.resolution_reason = 'migration_reconciled_duplicate_fact') "
            "AND NOT EXISTS (SELECT 1 FROM memory_declarations "
            "WHERE memory_declarations.memory_id = user_memories.id "
            "AND memory_declarations.user_id = user_memories.user_id "
            "AND memory_declarations.review_status = 'confirmed' "
            "AND memory_declarations.valid_to IS NULL)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_user_id "
            "ON memory_declarations(user_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_memory_id "
            "ON memory_declarations(memory_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_review_status "
            "ON memory_declarations(review_status)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_user_memory_observed "
            "ON memory_declarations(user_id, memory_id, observed_at)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_user_review_observed "
            "ON memory_declarations(user_id, review_status, observed_at)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_conflicts_with_id "
            "ON memory_declarations(conflicts_with_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_memory_declarations_user_fact_review_valid "
            "ON memory_declarations(user_id, fact_key, review_status, valid_to)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_declarations_user_fact_current "
            "ON memory_declarations(user_id, fact_key) "
            "WHERE review_status = 'confirmed' AND valid_to IS NULL AND fact_key != ''"
        ))
    except Exception as exc:
        raise RuntimeError("SQLite memory declaration migration failed") from exc

    # Retrieval manifests are explicitly rebuildable projections. Keep their
    # lifecycle/tombstone rows durable even after a material is deleted so a
    # failed external-vector cleanup can be retried after an application restart.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS retrieval_projections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_type VARCHAR(30) NOT NULL DEFAULT 'material',
                source_id INTEGER NOT NULL,
                backend VARCHAR(30) NOT NULL DEFAULT 'chroma',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                last_operation VARCHAR(20) NOT NULL DEFAULT 'ingest',
                source_version INTEGER NOT NULL DEFAULT 1,
                indexed_version INTEGER NULL,
                source_signature VARCHAR(64) NULL,
                content_hash VARCHAR(64) NULL,
                configuration_fingerprint VARCHAR(64) NULL,
                embedding_model VARCHAR(160) NULL,
                chunk_size INTEGER NULL,
                chunk_overlap INTEGER NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                vector_chunk_count INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                last_indexed_at DATETIME NULL,
                deleted_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_retrieval_projection_source_backend
                    UNIQUE (user_id, source_type, source_id, backend),
                CONSTRAINT ck_retrieval_projection_status CHECK
                    (status IN ('pending','indexing','ready','degraded','failed','deleting','deleted')),
                CONSTRAINT ck_retrieval_projection_source_version CHECK (source_version >= 1),
                CONSTRAINT ck_retrieval_projection_attempt_count CHECK (attempt_count >= 0),
                CONSTRAINT ck_retrieval_projection_chunk_count CHECK (chunk_count >= 0),
                CONSTRAINT ck_retrieval_projection_vector_chunk_count CHECK (vector_chunk_count >= 0),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_retrieval_projections_user_id "
            "ON retrieval_projections(user_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_retrieval_projections_user_status "
            "ON retrieval_projections(user_id, status, updated_at)"
        ))
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS retrieval_projection_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                projection_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                source_type VARCHAR(30) NOT NULL DEFAULT 'material',
                source_id INTEGER NOT NULL,
                source_version INTEGER NOT NULL DEFAULT 1,
                chunk_index INTEGER NOT NULL,
                chunk_hash VARCHAR(64) NOT NULL,
                text TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_retrieval_projection_chunk UNIQUE (projection_id, chunk_index),
                CONSTRAINT ck_retrieval_projection_chunk_index CHECK (chunk_index >= 0),
                CONSTRAINT ck_retrieval_chunk_source_version CHECK (source_version >= 1),
                FOREIGN KEY(projection_id) REFERENCES retrieval_projections(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_retrieval_projection_chunks_projection_id "
            "ON retrieval_projection_chunks(projection_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_retrieval_projection_chunks_user_id "
            "ON retrieval_projection_chunks(user_id)"
        ))
        await conn.execute(sqlalchemy.text(
            "CREATE INDEX IF NOT EXISTS ix_retrieval_projection_chunks_user_source "
            "ON retrieval_projection_chunks(user_id, source_type, source_id)"
        ))
    except Exception as exc:
        raise RuntimeError("SQLite retrieval projection migration failed") from exc

    # Concept identity and provenance remain canonical SQL data. These tables
    # upgrade existing local databases without requiring Neo4j or an AI service.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS concept_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                concept_id INTEGER NOT NULL,
                alias VARCHAR(120) NOT NULL,
                alias_normalized VARCHAR(120) NOT NULL,
                source VARCHAR(40) NOT NULL DEFAULT 'manual',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_concept_aliases_user_name UNIQUE (user_id, alias_normalized),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE
            )
            """
        ))
        for name, columns in (
            ("ix_concept_aliases_user_id", "user_id"),
            ("ix_concept_aliases_concept_id", "concept_id"),
            ("ix_concept_aliases_user_concept", "user_id, concept_id"),
        ):
            await conn.execute(sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS {name} ON concept_aliases({columns})"))

        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS concept_source_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                concept_id INTEGER NOT NULL,
                edge_id INTEGER NULL,
                source_type VARCHAR(30) NOT NULL DEFAULT 'material',
                source_id INTEGER NOT NULL,
                source_version INTEGER NOT NULL DEFAULT 1,
                excerpt TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8,
                review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_concept_source_evidence_review_status
                    CHECK (review_status IN ('pending', 'confirmed', 'rejected')),
                CONSTRAINT ck_concept_source_evidence_confidence
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
                CONSTRAINT ck_concept_source_evidence_source_version CHECK (source_version >= 1),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                FOREIGN KEY(edge_id) REFERENCES concept_edges(id) ON DELETE CASCADE
            )
            """
        ))
        for name, columns in (
            ("ix_concept_source_evidence_user_id", "user_id"),
            ("ix_concept_source_evidence_concept_id", "concept_id"),
            ("ix_concept_source_evidence_edge_id", "edge_id"),
            ("ix_concept_source_evidence_user_source", "user_id, source_type, source_id"),
            ("ix_concept_source_evidence_user_concept", "user_id, concept_id, review_status"),
        ):
            await conn.execute(
                sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS {name} ON concept_source_evidence({columns})")
            )

        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS concept_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                concept_id INTEGER NULL,
                operation VARCHAR(40) NOT NULL,
                actor VARCHAR(30) NOT NULL DEFAULT 'user',
                payload JSON NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE SET NULL
            )
            """
        ))
        for name, columns in (
            ("ix_concept_audit_events_user_id", "user_id"),
            ("ix_concept_audit_events_concept_id", "concept_id"),
            ("ix_concept_audit_events_user_concept", "user_id, concept_id, created_at"),
        ):
            await conn.execute(
                sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS {name} ON concept_audit_events({columns})")
            )
    except Exception as exc:
        raise RuntimeError("SQLite concept graph provenance migration failed") from exc

    # Mnemox V2 Stages 1-4 are additive. Existing desktop databases receive the
    # canonical source, extraction, entity-resolution, and disposable projection
    # tables without rebuilding any domain table.
    try:
        from app.models.knowledge import (
            Claim,
            ClaimConceptLink,
            ClaimEvidence,
            ClaimRelation,
            EntityResolutionCandidate,
            KnowledgeEmbeddingProjection,
            KnowledgeExtractionRun,
            KnowledgeProjectionOutbox,
            KnowledgeSource,
            KnowledgeSourceRevision,
            KnowledgeUnit,
        )

        knowledge_tables = [
            KnowledgeSource.__table__,
            KnowledgeSourceRevision.__table__,
            KnowledgeUnit.__table__,
            Claim.__table__,
            ClaimEvidence.__table__,
            ClaimRelation.__table__,
            KnowledgeExtractionRun.__table__,
            EntityResolutionCandidate.__table__,
            ClaimConceptLink.__table__,
            KnowledgeEmbeddingProjection.__table__,
            KnowledgeProjectionOutbox.__table__,
        ]
        await conn.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=knowledge_tables,
                checkfirst=True,
            )
        )
        expected_columns = {
            "knowledge_sources": {
                "id", "user_id", "source_type", "source_record_id", "source_key",
                "title_snapshot", "status", "current_revision", "created_at", "updated_at",
                "deleted_at",
            },
            "knowledge_source_revisions": {
                "id", "user_id", "knowledge_source_id", "revision", "content_hash",
                "title_snapshot", "status", "created_at", "superseded_at",
            },
            "knowledge_units": {
                "id", "user_id", "source_revision_id", "parent_unit_id", "unit_type",
                "ordinal", "text", "text_hash", "locator", "created_at",
            },
            "claims": {
                "id", "user_id", "source_revision_id", "statement", "claim_kind",
                "fingerprint", "confidence", "derivation_type", "review_status",
                "lifecycle_status", "extractor_version", "schema_version", "model_version",
                "created_at", "updated_at", "reviewed_at",
            },
            "claim_evidence": {
                "id", "user_id", "claim_id", "knowledge_unit_id", "excerpt",
                "char_start", "char_end", "locator", "grounding_method", "confidence",
                "created_at",
            },
            "claim_relations": {
                "id", "user_id", "from_claim_id", "to_claim_id", "relation_type",
                "confidence", "derivation_type", "review_status", "rationale",
                "evidence_provenance", "model_version", "evaluator_version",
                "created_at", "updated_at", "reviewed_at",
            },
            "knowledge_extraction_runs": {
                "id", "user_id", "source_revision_id", "extractor_type",
                "extractor_version", "schema_version", "provider", "model",
                "prompt_hash", "input_hash", "status", "attempt_count",
                "available_at", "locked_at", "lease_owner", "started_at",
                "finished_at", "last_error", "usage", "stats", "created_at",
                "updated_at",
            },
            "entity_resolution_candidates": {
                "id", "user_id", "extraction_run_id", "knowledge_unit_id", "claim_id",
                "mention_text", "mention_normalized", "mention_context", "relation_type",
                "candidate_concept_id", "exact_score", "alias_score", "lexical_score",
                "vector_score", "context_score", "combined_score", "decision",
                "resolved_concept_id", "decided_by", "decided_at", "identity_hash",
                "created_at", "updated_at",
            },
            "claim_concept_links": {
                "id", "user_id", "claim_id", "concept_id", "relation_type", "mention_text",
                "confidence", "derivation_type", "review_status", "resolution_candidate_id",
                "created_at", "updated_at",
            },
            "knowledge_embedding_projections": {
                "id", "user_id", "object_type", "object_id", "content_hash",
                "configuration_fingerprint", "embedding_model", "collection", "vector_key",
                "status", "attempt_count", "last_error", "indexed_at", "deleted_at",
                "created_at", "updated_at",
            },
            "knowledge_projection_outbox": {
                "id", "user_id", "aggregate_type", "aggregate_id", "aggregate_version",
                "operation", "projection_target", "idempotency_key", "payload_version",
                "payload", "status", "attempts", "available_at", "locked_at", "lease_owner",
                "processed_at", "last_error", "dead_lettered_at", "created_at", "updated_at",
            },
        }
        for table_name, required in expected_columns.items():
            actual = {
                row[1]
                for row in await conn.execute(
                    sqlalchemy.text(f"PRAGMA table_info({table_name})")
                )
            }
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(f"{table_name} missing columns: {', '.join(missing)}")
        revision_indexes = {
            row[1]
            for row in await conn.execute(
                sqlalchemy.text("PRAGMA index_list(knowledge_source_revisions)")
            )
        }
        if "uq_knowledge_source_revisions_current" not in revision_indexes:
            raise RuntimeError("knowledge Source current-revision index is missing")
        await conn.execute(sqlalchemy.text(
            "INSERT OR IGNORE INTO mnemox_lightweight_migrations (revision) "
            "VALUES ('20260902_19')"
        ))
        await conn.execute(sqlalchemy.text(
            "INSERT OR IGNORE INTO mnemox_lightweight_migrations (revision) "
            "VALUES ('20260903_20')"
        ))
        await conn.execute(sqlalchemy.text(
            "INSERT OR IGNORE INTO mnemox_lightweight_migrations (revision) "
            "VALUES ('20260903_21')"
        ))
        await conn.execute(sqlalchemy.text(
            "INSERT OR IGNORE INTO mnemox_lightweight_migrations (revision) "
            "VALUES ('20260903_22')"
        ))
    except Exception as exc:
        raise RuntimeError("SQLite canonical knowledge schema migration failed") from exc

    # Coach action attempts bridge a recommendation to a later domain event.
    # Fresh databases get this from metadata; this additive DDL keeps existing
    # local files replayable without running Alembic at application startup.
    try:
        await conn.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS coach_action_attempts (
                id VARCHAR(40) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                nudge_id VARCHAR(40) NOT NULL,
                action_type VARCHAR(80) NOT NULL DEFAULT 'open_route',
                route VARCHAR(200) NULL,
                action_payload JSON NOT NULL DEFAULT '{}',
                status VARCHAR(20) NOT NULL DEFAULT 'started',
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                observed_at DATETIME NULL,
                completed_at DATETIME NULL,
                abandoned_at DATETIME NULL,
                expires_at DATETIME NULL,
                linked_event_id INTEGER NULL,
                linked_event_type VARCHAR(80) NULL,
                outcome_source VARCHAR(40) NULL,
                outcome_reason VARCHAR(120) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(nudge_id) REFERENCES coach_nudges(id) ON DELETE CASCADE,
                FOREIGN KEY(linked_event_id) REFERENCES learning_events(id) ON DELETE SET NULL
            )
            """
        ))
        for name, columns in (
            ("ix_coach_action_attempts_user_id", "user_id"),
            ("ix_coach_action_attempts_nudge_id", "nudge_id"),
            ("ix_coach_action_attempts_status", "status"),
            ("ix_coach_action_attempts_started_at", "started_at"),
            ("ix_coach_action_attempts_linked_event_id", "linked_event_id"),
            ("ix_coach_action_attempts_user_nudge_status", "user_id, nudge_id, status"),
            ("ix_pomodoros_coach_action_attempt_id", "coach_action_attempt_id"),
        ):
            table = "pomodoros" if name.startswith("ix_pomodoros") else "coach_action_attempts"
            await conn.execute(sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})"))
    except Exception as exc:
        raise RuntimeError("SQLite Coach action-attempt migration failed") from exc


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
