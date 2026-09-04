"""Cross-process serialization for long-running operations.

User-scoped retrieval mutations take a shared global lock before their own
user lock.  A global retrieval configuration change takes the corresponding
exclusive lock, so a new embedding configuration can never be applied halfway
through an ingest or rebuild.
"""
from __future__ import annotations

import asyncio
import hashlib
import weakref
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


_LOCAL_LOCKS: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


class _LocalReadWriteLock:
    """Small writer-preferred async RW lock for SQLite and single-process use."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._condition:
            while self._writer or self._writers_waiting:
                await self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        async with self._condition:
            self._writers_waiting += 1
            try:
                while self._writer or self._readers:
                    await self._condition.wait()
                self._writer = True
            finally:
                self._writers_waiting -= 1
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()


_LOCAL_GLOBAL_LOCKS: weakref.WeakValueDictionary[str, _LocalReadWriteLock] = (
    weakref.WeakValueDictionary()
)


def stable_advisory_lock_key(namespace: str, identity: int | str) -> int:
    """Map a namespaced identity into PostgreSQL's signed BIGINT lock space."""

    digest = hashlib.blake2b(
        f"{str(namespace).strip()}:{identity}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _local_lock(namespace: str, identity: int | str) -> asyncio.Lock:
    key = (str(namespace), str(identity))
    lock = _LOCAL_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCAL_LOCKS[key] = lock
    return lock


def _local_global_lock(namespace: str) -> _LocalReadWriteLock:
    key = str(namespace)
    lock = _LOCAL_GLOBAL_LOCKS.get(key)
    if lock is None:
        lock = _LocalReadWriteLock()
        _LOCAL_GLOBAL_LOCKS[key] = lock
    return lock


async def _release_postgres_lock(connection, lock_key: int, *, shared: bool = False) -> None:
    try:
        await connection.execute(
            text(
                "SELECT pg_advisory_unlock_shared(:lock_key)"
                if shared
                else "SELECT pg_advisory_unlock(:lock_key)"
            ),
            {"lock_key": lock_key},
        )
    except BaseException:
        # A session-level advisory lock must never return to the pool when its
        # explicit unlock failed. Invalidating closes the physical connection,
        # which makes PostgreSQL release every lock owned by that session.
        await connection.invalidate()
        raise


@asynccontextmanager
async def serialized_global_operation(
    db: AsyncSession,
    *,
    namespace: str,
    exclusive: bool,
) -> AsyncIterator[None]:
    """Coordinate a global operation across local tasks and PostgreSQL nodes.

    PostgreSQL session advisory locks support shared and exclusive modes.  A
    dedicated connection keeps the lock alive while a caller commits durable
    checkpoints on its request session.
    """

    local_lock = _local_global_lock(namespace)
    local_context = local_lock.exclusive() if exclusive else local_lock.shared()
    async with local_context:
        bind = db.bind
        if bind is None or bind.dialect.name != "postgresql":
            yield
            return

        engine = bind if isinstance(bind, AsyncEngine) else bind.engine
        lock_key = stable_advisory_lock_key(namespace, "global")
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_advisory_lock(:lock_key)"
                    if exclusive
                    else "SELECT pg_advisory_lock_shared(:lock_key)"
                ),
                {"lock_key": lock_key},
            )
            try:
                yield
            finally:
                release_task = asyncio.create_task(
                    _release_postgres_lock(connection, lock_key, shared=not exclusive)
                )
                try:
                    await asyncio.shield(release_task)
                except asyncio.CancelledError:
                    await release_task
                    raise


@asynccontextmanager
async def serialized_user_operation(
    db: AsyncSession,
    *,
    namespace: str,
    user_id: int,
) -> AsyncIterator[None]:
    """Serialize one operation per user locally and across PostgreSQL instances.

    The advisory lock uses a dedicated connection because the caller may commit
    durable saga checkpoints while the external operation is still running.
    Keeping the lock connection separate preserves the lock across those commits
    without leaking session-level state into the SQLAlchemy pool.
    """

    async with _local_lock(namespace, int(user_id)):
        bind = db.bind
        if bind is None or bind.dialect.name != "postgresql":
            yield
            return

        engine = bind if isinstance(bind, AsyncEngine) else bind.engine
        lock_key = stable_advisory_lock_key(namespace, int(user_id))
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                yield
            finally:
                release_task = asyncio.create_task(
                    _release_postgres_lock(connection, lock_key)
                )
                try:
                    await asyncio.shield(release_task)
                except asyncio.CancelledError:
                    # Do not let request cancellation return a still-locked
                    # physical connection to the pool.
                    await release_task
                    raise
