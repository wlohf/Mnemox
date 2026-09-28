"""SQLite runs the same Alembic chain as PostgreSQL, including legacy files."""
import asyncio
import hashlib
import inspect
import sqlite3
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app import database
from app.database import Base

# Accepted differences between a caught-up legacy file and a fresh Alembic
# build: SQLite stores REAL and FLOAT with the same affinity, and adding the
# wrong_questions.concept_id foreign key would require a table rebuild.
_TOLERATED_LEGACY_DIFFS = {"modify_type", "add_fk"}


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _revision(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}


def _schema_diffs(path: Path) -> list:
    def include(_obj, name, type_, _reflected, _compare_to):
        return not (type_ == "table" and name == "mnemox_lightweight_migrations")

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as connection:
            connection.dialect.supports_comments = False
            context = MigrationContext.configure(
                connection, opts={"include_object": include, "compare_type": True}
            )
            return compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()


def _diff_kind(diff) -> str:
    first = diff[0] if isinstance(diff, list) else diff
    return first[0]


def _init_db_against(path: Path) -> None:
    async def run() -> None:
        engine = create_async_engine(_url(path))
        try:
            with patch.object(database, "engine", engine), patch.object(database, "_is_sqlite", lambda: True):
                await database.init_db()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _head() -> str:
    return ScriptDirectory.from_config(database._alembic_config()).get_current_head()


def test_fresh_sqlite_is_built_by_alembic_without_drift(tmp_path: Path):
    path = tmp_path / "fresh.db"
    _init_db_against(path)

    assert _revision(path) == {_head()}
    assert _schema_diffs(path) == []


def test_versioned_sqlite_is_upgraded_to_head(tmp_path: Path):
    path = tmp_path / "versioned.db"
    command.upgrade(database._alembic_config(_url(path)), "20260903_21")

    _init_db_against(path)

    assert _revision(path) == {_head()}
    assert _schema_diffs(path) == []


def test_unversioned_legacy_sqlite_is_caught_up_stamped_and_keeps_rows(tmp_path: Path):
    path = tmp_path / "legacy.db"
    # A v1.3-era desktop file: built at the baseline, then its version erased
    # the way the hand-written runtime always left SQLite files.
    command.upgrade(database._alembic_config(_url(path)), "20260801_00")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute(
            "INSERT INTO users (id, username, email, hashed_password) "
            "VALUES (1, 'legacy', 'legacy@example.test', 'hash')"
        )
        connection.execute("INSERT INTO notes (id, user_id, title, content) VALUES (1, 1, 'kept', 'body')")

    _init_db_against(path)
    _init_db_against(path)  # A second start is a no-op upgrade.

    assert _revision(path) == {_head()}
    unexpected = [diff for diff in _schema_diffs(path) if _diff_kind(diff) not in _TOLERATED_LEGACY_DIFFS]
    assert unexpected == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT title FROM notes WHERE id = 1").fetchone() == ("kept",)


def test_legacy_baseline_revision_is_part_of_the_chain():
    script = ScriptDirectory.from_config(database._alembic_config())
    ancestors = {revision.revision for revision in script.walk_revisions("base", "heads")}
    assert database.SQLITE_LEGACY_BASELINE_REVISION in ancestors


# Updating this digest means the legacy catch-up changed. That is only valid
# for fixing the catch-up itself; new schema belongs in an Alembic revision.
_FROZEN_LIGHTWEIGHT_DIGEST = "3580e61a45c5eb9eda3da944b676841137233145360bedb3c198c9b455f7361a"


def test_lightweight_catch_up_is_frozen():
    source = inspect.getsource(database._run_lightweight_migrations)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert digest == _FROZEN_LIGHTWEIGHT_DIGEST, (
        "app.database._run_lightweight_migrations is frozen: add an Alembic "
        "revision (runnable on SQLite and PostgreSQL) instead of new DDL here."
    )
