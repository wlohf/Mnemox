"""The single place that knows how the two supported databases differ.

SQLite serves the desktop app and source self-hosting; PostgreSQL serves the
hosted deployment. Callers ask for a capability here instead of branching on
``dialect.name`` themselves.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_DIALECTS = frozenset({"postgresql", "sqlite"})


def dialect_name(db: Any) -> str:
    """Dialect of a session, connection, or engine; ``""`` when unbound."""
    # Engines and connections carry the dialect; sessions reach it via a bind.
    dialect = getattr(db, "dialect", None)
    if dialect is None:
        bind = getattr(db, "bind", None)
        if bind is None and callable(getattr(db, "get_bind", None)):
            bind = db.get_bind()
        dialect = getattr(bind, "dialect", None)
    return str(getattr(dialect, "name", "") or "")


def is_postgresql(db: Any) -> bool:
    """PostgreSQL alone needs cross-process coordination (advisory locks)."""
    return dialect_name(db) == "postgresql"


def conflict_insert(db: Any, table: Any):
    """INSERT construct with ``ON CONFLICT`` support for the session's database.

    Both dialect constructs expose the same ``on_conflict_do_nothing`` /
    ``on_conflict_do_update(index_elements=...)`` API, so one statement serves
    SQLite and PostgreSQL.
    """
    name = dialect_name(db)
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        raise RuntimeError(f"Unsupported database dialect {name!r}: use SQLite or PostgreSQL.")
    return dialect_insert(table)
