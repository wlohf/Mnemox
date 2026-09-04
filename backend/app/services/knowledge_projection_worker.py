"""Lifecycle-managed consumer for Stage 3 knowledge projection commands."""
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.services.knowledge_projection_service import (
    KNOWLEDGE_PROJECTION_TARGET,
    NEO4J_GRAPH_PROJECTION_TARGET,
    SPARSE_KNOWLEDGE_PROJECTION_TARGET,
    claim_next_knowledge_projection,
    process_claimed_knowledge_projection,
)
from app.utils.error_safety import safe_exception_summary


def default_knowledge_projection_worker_id() -> str:
    host = str(socket.gethostname() or "worker").strip() or "worker"
    return f"knowledge-projection:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"[:120]


class KnowledgeProjectionWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        embedding_index: Any | None = None,
        poll_interval_seconds: float = 2.0,
        batch_size: int = 20,
        max_attempts: int = 5,
        lease_seconds: int = 120,
        retry_base_seconds: float = 5.0,
    ) -> None:
        if poll_interval_seconds <= 0 or batch_size < 1 or max_attempts < 1 or lease_seconds < 1:
            raise ValueError("知识投影 worker 配置必须大于 0。")
        self._session_factory = session_factory
        self.worker_id = (worker_id or default_knowledge_projection_worker_id())[:120]
        self._embedding_index = embedding_index
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = int(batch_size)
        self._max_attempts = int(max_attempts)
        self._lease_seconds = int(lease_seconds)
        self._retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._polls = 0
        self._claimed = 0
        self._processed = 0
        self._failed = 0
        self._last_error: str | None = None
        targets: list[str] = []
        if settings.KNOWLEDGE_EMBEDDING_ENABLED:
            targets.append(KNOWLEDGE_PROJECTION_TARGET)
        if str(settings.KNOWLEDGE_SPARSE_BACKEND or "reference").strip().casefold() != "reference":
            targets.append(SPARSE_KNOWLEDGE_PROJECTION_TARGET)
        if (
            str(settings.GRAPH_BACKEND or "sql").strip().casefold() == "neo4j"
            or settings.NEO4J_GRAPH_SHADOW
            or settings.NEO4J_GRAPH_ENABLED
        ):
            targets.append(NEO4J_GRAPH_PROJECTION_TARGET)
        self._projection_targets = tuple(targets or (KNOWLEDGE_PROJECTION_TARGET,))

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "polls": self._polls,
            "claimed": self._claimed,
            "processed": self._processed,
            "failed": self._failed,
            "last_error": self._last_error,
            "poll_interval_seconds": self._poll_interval_seconds,
        }

    def health_snapshot(self) -> dict[str, Any]:
        result = self.snapshot()
        result.pop("last_error", None)
        return result

    async def _claim_one(self) -> int | None:
        async with self._session_factory() as session:
            try:
                row = await claim_next_knowledge_projection(
                    session,
                    worker_id=self.worker_id,
                    max_attempts=self._max_attempts,
                    lease_seconds=self._lease_seconds,
                    projection_targets=self._projection_targets,
                )
                if row is None:
                    await session.rollback()
                    return None
                identifier = int(row.id)
                await session.commit()
                return identifier
            except BaseException:
                await session.rollback()
                raise

    async def _process_one(self, outbox_id: int) -> str:
        async with self._session_factory() as session:
            try:
                status = await process_claimed_knowledge_projection(
                    session,
                    outbox_id=int(outbox_id),
                    worker_id=self.worker_id,
                    embedding_index=self._embedding_index,
                    max_attempts=self._max_attempts,
                    retry_base_seconds=self._retry_base_seconds,
                )
                await session.commit()
                return status
            except BaseException:
                await session.rollback()
                raise

    async def run_once(self) -> dict[str, int]:
        totals = {"claimed": 0, "processed": 0, "failed": 0}
        for _ in range(self._batch_size):
            outbox_id = await self._claim_one()
            if outbox_id is None:
                break
            totals["claimed"] += 1
            try:
                status = await self._process_one(outbox_id)
            except Exception as exc:
                totals["failed"] += 1
                self._last_error = safe_exception_summary(exc)
                continue
            if status == "processed":
                totals["processed"] += 1
            else:
                totals["failed"] += 1
        self._polls += 1
        self._claimed += totals["claimed"]
        self._processed += totals["processed"]
        self._failed += totals["failed"]
        if totals["failed"] == 0:
            self._last_error = None
        return totals

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._task = asyncio.create_task(
            self._run(),
            name=f"knowledge-projection:{self.worker_id}",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        self._task = None
        self._running = False

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await self.run_once()
                except Exception as exc:
                    self._last_error = safe_exception_summary(exc)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            self._running = False
