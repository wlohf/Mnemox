"""Alembic env.py - async migration environment."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base

# Import the package-level registry so Base.metadata includes every current model.
import app.models  # noqa: F401

config = context.config

# The desktop/SQLite runtime migrates in-process at startup; it passes
# ``configure_logger=False`` so the ini file cannot reset application logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


# Disposable sparse-search projections that app.services.sparse_knowledge_index
# creates at runtime (SQLite FTS5 and its shadow tables, PostgreSQL FTS tables).
# They are rebuilt on demand, so autogenerate must never propose dropping them.
_RUNTIME_TABLE_PREFIXES = ("knowledge_claim_fts", "knowledge_claim_sparse", "knowledge_sparse_dirty")


def _include_object(obj, name, type_, reflected, compare_to):
    # Local SQLite keeps a small one-time migration ledger outside Alembic.
    # It is not part of the production schema and must not appear as a pending
    # drop during ``alembic check``.
    if type_ == "table":
        return name != "mnemox_lightweight_migrations" and not str(name).startswith(_RUNTIME_TABLE_PREFIXES)
    table = getattr(obj, "table", None)
    return not (table is not None and str(table.name).startswith(_RUNTIME_TABLE_PREFIXES))

# The application runner and tests can provide a specific connection URL through
# Alembic's Config object.  The bundled ini intentionally leaves it empty so
# direct ``alembic`` use falls back to the application setting instead.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_comments=False,
        include_object=_include_object,
        render_as_batch=str(url or "").startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    # The frozen v1.3 baseline predates most ORM column comments. Comments are
    # documentation rather than a runtime contract; comparing them would make
    # every real PostgreSQL rehearsal report hundreds of false-positive ALTER
    # COMMENT operations while obscuring structural drift.
    # The frozen baseline intentionally does not carry the newer ORM comment
    # catalog. Disable dialect comment reflection for autogenerate checks;
    # structural drift remains fully compared.
    connection.dialect.supports_comments = False
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_comments=False,
        include_object=_include_object,
        # Every revision must run on SQLite and PostgreSQL; autogenerate emits
        # batch operations for SQLite, which cannot ALTER most constraints.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
