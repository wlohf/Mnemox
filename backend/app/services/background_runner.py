"""Bounded in-process runner for work that must outlive one HTTP request.

Submitted work survives a client disconnect but not a process restart. Callers
must either keep a recoverable SQL state (for example a ``pending`` projection
that startup recovery re-ingests) or accept that best-effort work may be lost.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Hashable

from app.utils.error_safety import safe_exception_summary

logger = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """Run detached tasks with a global concurrency bound and per-key ordering.

    Work sharing a key runs one at a time in submission order, so two chat
    turns of one conversation never enrich the same summary concurrently.
    """

    def __init__(self, name: str, *, max_concurrency: int) -> None:
        self.name = name
        self.max_concurrency = max(1, int(max_concurrency))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        # key -> [lock, number of queued or running tasks holding a reference]
        self._keys: dict[Hashable, list] = {}

    def _bind_running_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # asyncio primitives are loop-bound; tests run one loop per case.
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
            self._tasks = set()
            self._keys = {}

    def submit(self, key: Hashable, work: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
        """Schedule ``work`` and keep a strong reference until it finishes."""
        self._bind_running_loop()
        entry = self._keys.get(key)
        if entry is None:
            entry = self._keys[key] = [asyncio.Lock(), 0]
        entry[1] += 1
        task = asyncio.create_task(self._run(key, entry, work), name=f"{self.name}:{key}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, key: Hashable, entry: list, work: Callable[[], Awaitable[None]]) -> None:
        try:
            async with entry[0]:
                async with self._semaphore:
                    await work()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "后台任务失败 runner=%s key=%s: %s",
                self.name,
                key,
                safe_exception_summary(exc),
            )
        finally:
            entry[1] -= 1
            if entry[1] == 0 and self._keys.get(key) is entry:
                self._keys.pop(key, None)

    @property
    def pending_count(self) -> int:
        return sum(1 for task in self._tasks if not task.done())

    async def drain(self, timeout: float) -> None:
        """Wait for in-flight work, then cancel whatever outlives ``timeout``."""
        if self._loop is not asyncio.get_running_loop():
            return
        tasks = [task for task in self._tasks if not task.done()]
        if not tasks:
            return
        _done, still_running = await asyncio.wait(tasks, timeout=max(0.0, float(timeout)))
        for task in still_running:
            task.cancel()
        if still_running:
            logger.warning("后台任务在关闭时被取消 runner=%s count=%d", self.name, len(still_running))
            await asyncio.gather(*still_running, return_exceptions=True)


# Post-turn chat enrichment calls model providers; keep bursts bounded.
chat_turn_enrichment_runner = BackgroundTaskRunner("chat-turn-enrichment", max_concurrency=4)
# Material vectorization calls the embedding provider for every chunk.
material_projection_runner = BackgroundTaskRunner("material-projection", max_concurrency=2)


async def drain_background_runners(timeout: float) -> None:
    """Give request-detached work a bounded grace period during shutdown."""
    await asyncio.gather(
        chat_turn_enrichment_runner.drain(timeout),
        material_projection_runner.drain(timeout),
    )
