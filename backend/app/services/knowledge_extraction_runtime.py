"""Extraction orchestration: detached I/O, fenced short Unit checkpoints.

Only this runtime and the lifecycle worker own transactions. Providers receive a
plain detached Unit, never a live session. Provider cancellation is best effort;
late results cannot reach a persistence checkpoint and their reservations remain
charged. A stuck provider applies backpressure rather than spawning more calls.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import select, update

from app.config import settings
from app.models.extraction_budget import ExtractionCall
from app.models.knowledge import KnowledgeExtractionRun, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.schemas.knowledge_extraction import KnowledgeExtractionResult
from app.services.extraction_budget_service import (
    ExtractionBudgetExceeded, ExtractionLeaseLost, reserve_extraction_call, settle_extraction_call,
)
from app.services.knowledge_extraction_service import (
    DeterministicKnowledgeExtractor, LLMKnowledgeExtractor, _persist_grounded_claims,
    _usage_add, ground_extraction_result, normalize_claim_statement,
)
from app.utils.error_safety import safe_exception_summary
from app.utils.utc import utc_now_db


def detach_task(task, tasks, on_finished=None):
    """Bound admission elsewhere; consume late exceptions without logging payloads."""
    tasks.add(task)

    def finished(done):
        try:
            if not done.cancelled():
                error = done.exception()
                if on_finished is not None:
                    on_finished(error)
        finally:
            tasks.discard(done)

    task.add_done_callback(finished)


class ResolutionSnapshot:
    """Read-only lookup cache: entity resolution inside a checkpoint cannot do I/O."""
    def __init__(self):
        self.rows = {}

    async def query_concepts(self, *, user_id, text, top_k):
        return self.rows.get((user_id, normalize_claim_statement(text)), [])[:top_k]


class ExtractionRuntime:
    def __init__(self, sessions, *, run_id, worker_id, lease_token, provider=None,
                 extractor=None, stop_event=None, lease_seconds=None, orphan_tasks=None):
        self.sessions = sessions
        self.run_id = int(run_id)
        self.worker_id = str(worker_id)[:120]
        self.lease_token = str(lease_token)
        self.provider = provider
        self.extractor = extractor
        self.stop_event = stop_event or asyncio.Event()
        self.lease_seconds = float(lease_seconds or settings.KNOWLEDGE_EXTRACTION_LEASE_SECONDS)
        self.orphans = orphan_tasks if orphan_tasks is not None else set()
        self.owns_provider = False
        self.unit = None

    @asynccontextmanager
    async def _transaction(self):
        async with self.sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def _guard(self, db):
        if self.stop_event.is_set():
            raise asyncio.CancelledError()
        # Global lock order: Source -> Run -> Call/Day. A real DML lock also works
        # on SQLite; FOR UPDATE alone would permit stale checkpoint writes there.
        source_ids = select(KnowledgeSourceRevision.knowledge_source_id).join(
            KnowledgeExtractionRun,
            KnowledgeExtractionRun.source_revision_id == KnowledgeSourceRevision.id,
        ).where(KnowledgeExtractionRun.id == self.run_id)
        await db.execute(update(KnowledgeSource).where(KnowledgeSource.id.in_(source_ids)).values(
            updated_at=KnowledgeSource.updated_at,
        ).execution_options(synchronize_session=False))
        now = utc_now_db()
        identity = await db.scalar(update(KnowledgeExtractionRun).where(
            KnowledgeExtractionRun.id == self.run_id,
            KnowledgeExtractionRun.status == 'running',
            KnowledgeExtractionRun.lease_owner == self.worker_id,
            KnowledgeExtractionRun.lease_token == self.lease_token,
            KnowledgeExtractionRun.lease_expires_at > now,
        ).values(locked_at=now, lease_expires_at=now + timedelta(seconds=self.lease_seconds))
            .returning(KnowledgeExtractionRun.id).execution_options(synchronize_session=False))
        if identity is None:
            raise ExtractionLeaseLost('Extraction lease is no longer current')
        run = await db.scalar(select(KnowledgeExtractionRun).where(
            KnowledgeExtractionRun.id == self.run_id,
        ).execution_options(populate_existing=True))
        current = await db.scalar(select(KnowledgeSourceRevision.id).join(KnowledgeSource).where(
            KnowledgeSourceRevision.id == run.source_revision_id,
            KnowledgeSourceRevision.user_id == run.user_id,
            KnowledgeSourceRevision.status == 'current',
            KnowledgeSource.user_id == run.user_id,
            KnowledgeSource.status == 'active',
        ))
        if current is None:
            raise ExtractionLeaseLost('Extraction source revision is no longer current')
        return run

    async def _renew(self):
        async with self._transaction() as db:
            await self._guard(db)

    async def _prepare(self):
        async with self._transaction() as db:
            run = await self._guard(db)
            unit_ids = list((await db.scalars(select(KnowledgeUnit.id).where(
                KnowledgeUnit.source_revision_id == run.source_revision_id,
                KnowledgeUnit.user_id == run.user_id,
            ).order_by(KnowledgeUnit.ordinal, KnowledgeUnit.id))).all())
            stats = dict(run.stats or {})
            for key in ('claims', 'evidence', 'mentions', 'relations', 'rejected', 'rejected_evidence'):
                stats.setdefault(key, 0)
            stats.setdefault('processed_unit_ids', [])
            stats.setdefault('failed_units', [])
            stats['total_units'] = len(unit_ids)
            run.stats = stats
            self.user_id = int(run.user_id)
            self.source_revision_id = int(run.source_revision_id)
            kind = run.extractor_type
        if kind == 'llm':
            if not settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED:
                raise ValueError('LLM extraction is disabled')
            if self.extractor is not None:
                raise ValueError('LLM extraction must use the metered provider path')
            if self.provider is None:
                from app.ai.factory import AIProviderFactory
                # Configuration lookup is read-only; close it before any model I/O.
                async with self.sessions() as db:
                    self.provider = await AIProviderFactory.create_provider(
                        db=db, scenario='material_analyze', user_id=self.user_id,
                    )
                self.owns_provider = True
            cap = int(settings.KNOWLEDGE_LLM_MAX_OUTPUT_TOKENS)
            configure = getattr(self.provider, 'configure_extraction', None)
            if configure is not None:
                configure(cap)
            elif self.owns_provider:
                raise ValueError('Provider does not support bounded extraction calls')
            else:  # Explicit injection seam for local test doubles, not factory providers.
                self.provider.max_output_tokens = min(getattr(self.provider, 'max_output_tokens', cap), cap)
            self.extractor = LLMKnowledgeExtractor(self.provider, invoke=self._invoke)
        elif kind == 'deterministic':
            self.extractor = self.extractor or DeterministicKnowledgeExtractor()
        else:
            raise ValueError('Unsupported automatic extraction type')
        return unit_ids

    async def _load_unit(self, unit_id):
        async with self._transaction() as db:
            run = await self._guard(db)
            if unit_id in (run.stats or {}).get('processed_unit_ids', []):
                return None
            unit = await db.scalar(select(KnowledgeUnit).where(
                KnowledgeUnit.id == unit_id, KnowledgeUnit.user_id == run.user_id,
                KnowledgeUnit.source_revision_id == run.source_revision_id,
            ))
            if unit is None:
                raise ExtractionLeaseLost('Extraction unit no longer exists')
            # Explicitly detach before the transaction closes (also works with
            # expire_on_commit=True session factories).
            db.expunge(unit)
            return unit

    async def _external(self, make_awaitable, on_late=None):
        if self.stop_event.is_set():
            raise asyncio.CancelledError()
        if any(not task.done() for task in self.orphans):
            raise RuntimeError('A cancelled provider has not stopped; further calls are paused')
        task = asyncio.create_task(make_awaitable())
        stop = asyncio.create_task(self.stop_event.wait())
        deadline = time.monotonic() + float(settings.KNOWLEDGE_EXTRACTION_TIMEOUT_SECONDS)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError('Extraction provider call timed out')
                done, _ = await asyncio.wait(
                    {task, stop}, timeout=min(remaining, 1.0, self.lease_seconds / 3),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop in done or self.stop_event.is_set():
                    raise asyncio.CancelledError()
                if task in done:
                    if task.cancelled():
                        raise RuntimeError('Provider cancelled its own request')
                    return task.result()
                # Renewal also observes user cancellation and source replacement.
                await self._renew()
        except BaseException as exc:
            task.cancel()
            # Do not wait_for(task): it can wait forever for ignored cancellation.
            late = on_late if isinstance(exc, (asyncio.CancelledError, asyncio.TimeoutError, ExtractionLeaseLost)) else None
            detach_task(task, self.orphans, on_finished=late)
            raise
        finally:
            stop.cancel()

    async def _invoke(self, method, kwargs):
        if any(not task.done() for task in self.orphans):
            raise RuntimeError('A cancelled provider has not stopped; further calls are paused')
        call_id = str(uuid.uuid4())
        # Conservative preflight: UTF-8 bytes (not chars/4), schema/system overhead,
        # and the configured output bound. This is a token guard, not a dollar bill.
        encoded = json.dumps(kwargs.get('messages', []), ensure_ascii=False).encode('utf-8')
        estimate = len(encoded) + len(str(kwargs.get('system_prompt', '')).encode('utf-8')) + 256
        if method == 'chat_structured':
            estimate += len(json.dumps(KnowledgeExtractionResult.model_json_schema()).encode('utf-8'))
        estimate += int(self.provider.max_output_tokens)
        async with self._transaction() as db:
            run = await self._guard(db)
            await reserve_extraction_call(
                db, call_id=call_id, user_id=run.user_id, run_id=run.id,
                unit_id=self.unit.id, lease_token=self.lease_token, estimated_tokens=estimate,
                provider=str(getattr(self.provider, 'provider_name', type(self.provider).__name__))[:80],
                model=str(getattr(self.provider, 'model', '') or '')[:120] or None,
            )
        getattr(self.provider, 'clear_last_usage', lambda: None)()

        def late_completed(error):
            try:
                usage = dict(getattr(self.provider, 'get_last_usage', lambda: {})() or {})
            except Exception:
                return  # Keep the conservative unknown charge if usage is unavailable.

            async def reconcile():
                async with self._transaction() as db:
                    await settle_extraction_call(db, call_id=call_id,
                                                 state='failed' if error is not None else 'succeeded', usage=usage)
            # Keep admission closed until late accounting also finishes.
            detach_task(asyncio.create_task(reconcile()), self.orphans)

        state = 'unknown'
        try:
            result = await self._external(lambda: getattr(self.provider, method)(**kwargs), on_late=late_completed)
            state = 'succeeded'
            return result
        except (asyncio.CancelledError, asyncio.TimeoutError, ExtractionLeaseLost):
            raise
        except Exception:
            state = 'failed'
            raise
        finally:
            usage = dict(getattr(self.provider, 'get_last_usage', lambda: {})() or {})
            # Accounting is independent of domain fencing: an already-issued call
            # remains charged even if the user cancelled or replaced its source.
            async with self._transaction() as db:
                await settle_extraction_call(db, call_id=call_id, state=state, usage=usage)

    async def _usage(self, db, run):
        rows = list((await db.scalars(select(ExtractionCall).where(ExtractionCall.run_id == run.id))).all())
        if not rows:
            return  # Preserve pre-ledger usage: it must never silently reset.
        usage = {}
        for row in rows:
            usage = _usage_add(usage, dict(row.usage or {}), 0)
        usage.update(
            call_count=len(rows), estimated_tokens=sum(row.estimated_tokens for row in rows),
            charged_tokens=sum(row.charged_tokens for row in rows),
            unknown_calls=sum(row.state in ('reserved', 'unknown') for row in rows),
        )
        run.usage = usage

    async def _resolution_snapshot(self, grounding):
        snapshot = ResolutionSnapshot()
        if not settings.KNOWLEDGE_EMBEDDING_ENABLED:
            return snapshot
        from app.services.knowledge_embedding_service import get_knowledge_embedding_index
        from app.services.entity_resolution_service import find_known_concept_identity
        from app.services.concept_service import normalize_concept_name
        queries = {}
        async with self.sessions() as db:
            for claim in grounding.claims:
                seen = set()
                for mention in list(claim.candidate.concepts)[:int(settings.KNOWLEDGE_RESOLUTION_MAX_MENTIONS_PER_CLAIM)]:
                    normalized = normalize_concept_name(mention.text)
                    identity = (normalized, str(mention.relation_type))
                    if len(normalized) < 2 or identity in seen:
                        continue
                    seen.add(identity)
                    concept, _ = await find_known_concept_identity(
                        db, user_id=self.user_id, source_revision_id=self.source_revision_id,
                        normalized=normalized, relation_type=str(mention.relation_type),
                    )
                    if concept is None:
                        text = f'{mention.text}\n{claim.statement}'
                        queries[(self.user_id, normalize_claim_statement(text))] = text
        # Retain exact/alias/manual fast paths: prefetch must not add paid calls
        # for identities which already resolve entirely in SQL.
        for key, text in queries.items():
            try:
                await self._renew()
                snapshot.rows[key] = await self._external(lambda: get_knowledge_embedding_index().query_concepts(
                    user_id=self.user_id, text=text, top_k=int(settings.KNOWLEDGE_RESOLUTION_TOP_K),
                ))
            except (asyncio.CancelledError, ExtractionLeaseLost):
                raise
            except Exception:
                # Preserve SQL review fallback; optional embedding budgets remain separate.
                snapshot.rows[key] = []
        return snapshot

    async def _checkpoint(self, unit, grounding=None, resolution=None, error=None):
        async with self._transaction() as db:
            run = await self._guard(db)
            current = await db.get(KnowledgeUnit, unit.id)
            if current is None or current.text_hash != unit.text_hash or current.text != unit.text:
                raise ExtractionLeaseLost('Extraction unit changed during the provider call')
            stats = dict(run.stats or {})
            processed = set(stats.get('processed_unit_ids', []))
            if unit.id in processed:
                return
            failures = [entry for entry in stats.get('failed_units', []) if entry.get('unit_id') != unit.id]
            if error is None:
                claims, evidence = await _persist_grounded_claims(
                    db, run=run, unit=current, grounding=grounding,
                    model_version=getattr(self.provider, 'model', None),
                    embedding_index=resolution or ResolutionSnapshot(),
                )
                stats['claims'] += claims
                stats['evidence'] += evidence
                stats['mentions'] += sum(len(claim.candidate.concepts) for claim in grounding.claims)
                stats['relations'] += grounding.accepted_relations
                stats['rejected'] += grounding.rejected_claims
                stats['rejected_evidence'] += grounding.rejected_evidence
                processed.add(unit.id)
            else:
                # Validation/SDK/SQL exceptions can echo entire source payloads.
                # Only controlled budget messages and exception types belong in metadata.
                reason = safe_exception_summary(error, max_chars=240) if isinstance(error, ExtractionBudgetExceeded) else f'knowledge_extraction_unit_failed:{type(error).__name__}'
                failures.append({'unit_id': unit.id, 'error': reason})
            stats['processed_unit_ids'] = sorted(processed)
            stats['failed_units'] = failures
            run.stats = stats
            if self.provider is not None:
                run.provider = str(getattr(self.provider, 'provider_name', type(self.provider).__name__))[:80]
                run.model = str(getattr(self.provider, 'model', '') or '')[:120] or None
            await self._usage(db, run)

    async def _finish(self):
        async with self._transaction() as db:
            run = await self._guard(db)
            await self._usage(db, run)
            stats = run.stats or {}
            incomplete = len(stats.get('processed_unit_ids', [])) < stats.get('total_units', 0)
            run.status = 'partial' if incomplete or stats.get('failed_units') else 'succeeded'
            run.last_error = 'Some Units are unfinished; committed checkpoints were retained.' if run.status == 'partial' else None
            run.finished_at = utc_now_db()
            run.locked_at = run.lease_owner = run.lease_token = run.lease_expires_at = None
            await db.flush()
            db.expunge(run)
            return run

    async def _close_provider(self):
        close = getattr(self.provider, 'close_extraction', None)
        if not self.owns_provider or close is None:
            return
        task = asyncio.create_task(close())
        done, _ = await asyncio.wait({task}, timeout=1.0)
        if task not in done:
            task.cancel()
            detach_task(task, self.orphans)
        elif not task.cancelled():
            # Cleanup failure must not erase already-committed Unit checkpoints.
            task.exception()

    async def run(self):
        try:
            unit_ids = await self._prepare()
            for unit_id in unit_ids:
                self.unit = await self._load_unit(unit_id)
                if self.unit is None:
                    continue
                try:
                    if isinstance(self.extractor, LLMKnowledgeExtractor):
                        candidate = await self.extractor.extract(self.unit)
                    else:
                        candidate = await self._external(lambda: self.extractor.extract(self.unit))
                    candidate = KnowledgeExtractionResult.model_validate(candidate)
                    grounding = ground_extraction_result(str(self.unit.text or ''), candidate)
                    resolution = await self._resolution_snapshot(grounding)
                    await self._checkpoint(self.unit, grounding=grounding, resolution=resolution)
                except (asyncio.CancelledError, ExtractionLeaseLost):
                    raise
                except Exception as exc:
                    # A separate short transaction records failure; a failed Unit
                    # cannot undo earlier checkpoints or a provider reservation.
                    await self._checkpoint(self.unit, error=exc)
                    if isinstance(exc, ExtractionBudgetExceeded) or any(not task.done() for task in self.orphans):
                        break
            return await self._finish()
        finally:
            await self._close_provider()
