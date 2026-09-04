"""Auditable ownership policy for service-layer transaction commits.

Most domain and projection functions participate in the caller's unit of work
and may only flush. A small number of workflow coordinators and independent
workers intentionally commit durable checkpoints. Every such method is listed
here so adding an implicit commit becomes an architecture-test failure instead
of an invisible behavior change.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TransactionOwnerKind(str, Enum):
    """The only supported reasons for a service-layer commit."""

    DURABLE_WORKFLOW = "durable_workflow"
    INDEPENDENT_WORKER = "independent_worker"


@dataclass(frozen=True)
class TransactionOwner:
    kind: TransactionOwnerKind
    rationale: str


TRANSACTION_OWNERS: dict[str, TransactionOwner] = {
    "app.agents.manager.AgentManager.trigger": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Persists a complete synchronous Agent job or its terminal failure before returning.",
    ),
    "app.services.material_service.MaterialService.create_material": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Commits canonical material state before invoking recoverable external vector projection checkpoints.",
    ),
    "app.services.material_service.MaterialService.update_material": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Commits the new canonical material version before rebuilding disposable cross-store projections.",
    ),
    "app.services.material_service.MaterialService.delete_material": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Atomically commits canonical deletion with a durable projection tombstone before external cleanup.",
    ),
    "app.services.retrieval_projection_service.RetrievalProjectionService._ingest_locked": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Persists projection state checkpoints around non-transactional vector-store indexing.",
    ),
    "app.services.retrieval_projection_service.RetrievalProjectionService._forget_locked": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Persists a deletion tombstone and terminal outcome around non-transactional vector cleanup.",
    ),
    "app.services.retrieval_projection_service.RetrievalProjectionService._forget_user_locked": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Finalizes user-scoped SQL projection deletion after external vector cleanup succeeds.",
    ),
    "app.services.retrieval_projection_service.RetrievalProjectionService.mark_configuration_stale": TransactionOwner(
        TransactionOwnerKind.DURABLE_WORKFLOW,
        "Persists an explicit rebuild-required checkpoint for incompatible projection configurations.",
    ),
    "app.services.agent_job_recovery_service.AgentJobRecoveryWorker.run_once": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Owns its short-lived recovery session and commits recovered terminal job states as one batch.",
    ),
    "app.services.agent_runtime_worker.AgentRuntimeWorker._run_user": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Owns one isolated user-cycle session including scheduling and terminal task state.",
    ),
    "app.services.agent_runtime_worker.AgentRuntimeWorker._record_failure_log": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Uses a fresh session to persist bounded retry state after the failed user transaction was rolled back.",
    ),
    "app.services.projection_outbox_worker.ProjectionOutboxWorker._reconcile_terminal_failures": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Owns a maintenance session that reconciles durable dead-letter state before the next claim cycle.",
    ),
    "app.services.projection_outbox_worker.ProjectionOutboxWorker._process_one_row": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Processes each claimed outbox row in a dedicated transaction to isolate retries and failures.",
    ),
    "app.services.projection_outbox_worker.ProjectionOutboxWorker._persist_heartbeat": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Persists worker liveness through a dedicated short-lived session independent of projection work.",
    ),
    "app.services.knowledge_extraction_worker.KnowledgeExtractionWorker._claim_one": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Commits a short extraction lease before any provider call so process crashes remain recoverable.",
    ),
    "app.services.knowledge_extraction_worker.KnowledgeExtractionWorker._finish_one": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Commits one leased extraction outcome while preserving successful Unit savepoints on partial runs.",
    ),
    "app.services.knowledge_extraction_worker.KnowledgeExtractionWorker._record_failure": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Uses a fresh transaction to retain bounded retry state after an extraction transaction fails.",
    ),
    "app.services.knowledge_projection_worker.KnowledgeProjectionWorker._claim_one": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Commits a short knowledge projection lease before touching the disposable vector store.",
    ),
    "app.services.knowledge_projection_worker.KnowledgeProjectionWorker._process_one": TransactionOwner(
        TransactionOwnerKind.INDEPENDENT_WORKER,
        "Commits one knowledge projection outcome in an isolated retryable transaction.",
    ),
}
