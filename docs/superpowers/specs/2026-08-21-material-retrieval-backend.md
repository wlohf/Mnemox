# Material Retrieval Backend Integration Contract

Date: 2026-08-21

## Goal

Move large-material retrieval behind the unified RetrievalRouter without making the router depend on Chroma internals. Keep the material retrieval implementation replaceable so Chroma, sparse/keyword retrieval, and future Qdrant/FTS backends can be changed independently.

## Responsibility boundary

### RetrievalRouter owns

- deciding whether the request needs materials, notes, memory, concepts, or learner state;
- cross-source loading policy such as L0/L1/L2;
- cross-source RRF/fusion and final result budget;
- source normalization and partial degradation across source families.

### Material retrieval backend owns

- retrieval inside the material source only;
- material scope enforcement after user ownership is resolved in SQL;
- semantic candidates from Chroma;
- sparse/keyword candidates from a replaceable backend;
- within-material-source fusion;
- stable chunk provenance.

Do not let RetrievalRouter query Chroma directly. The only Chroma-specific migration seam should live in `material_retrieval_backend.py` until the legacy RAG service exposes a public storage interface.

## Scope rules

`MaterialSearchScope` is the canonical input for material retrieval:

- `user_id` is mandatory;
- explicit `material_ids` are intersected with user-owned materials;
- `material_id_min` and `material_id_max` are resolved numerically in SQL before Chroma filtering because legacy Chroma metadata stores material IDs as strings;
- `project_id` must be validated through `ChatProject` ownership and is also applied to Chroma when available.

An empty resolved material set means no material search. It must never fall back to an unscoped global Chroma query.

## Chunk provenance

Every material hit exposes at least:

- `material_id`;
- `material_title`;
- `chunk_index`;
- `source`, currently `material:{material_id}#chunk:{chunk_index}`;
- `backend`;
- `backend_scores` and `backend_ranks` when fusion is used.

The router may normalize these fields into its common result schema, but should preserve the chunk-level source so citations/debugging can trace a result to a concrete material fragment.

## Hybrid retrieval

Current modes:

- `chroma`: semantic-only;
- `keyword`: dependency-free BM25-style reference backend;
- `hybrid`: Chroma + keyword candidates fused with RRF.

The current keyword backend is intentionally a compatibility/reference implementation: it loads scoped material text and builds BM25 candidates on demand. This is acceptable for the foundation phase but is not the target large-corpus implementation. It can later be replaced by Qdrant sparse vectors, SQLite/PostgreSQL FTS, or another persistent sparse index without changing RetrievalRouter.

Because both concrete backends may share one request-scoped SQLAlchemy `AsyncSession`, they must not perform concurrent database operations on that same session. Each backend degrades independently; failure of Chroma must not discard usable keyword results, and vice versa.

## RRF layering

There are two possible fusion layers and they must have different meanings:

1. material backend RRF: semantic vs sparse candidates inside the material source;
2. RetrievalRouter RRF: materials vs notes vs memory vs concepts vs learner state.

The router must treat the material backend result as one source family. Do not feed Chroma and keyword candidates separately into the router's cross-source RRF, otherwise material evidence receives an accidental double source weight.

## Index rebuild

`MaterialIndexRebuilder.rebuild_user(user_id)` is the user-scoped one-click Chroma rebuild path.

- it deletes only `user_id` chunks from Chroma;
- it reloads only that user's materials from SQL;
- it restores project metadata while re-indexing;
- it reports indexed material count, chunk count, failures, and the latest RAG error.

The previous `/rag/reindex-all` implementation called the global `reset_index()` and could remove other users' chunks while rebuilding only the current user. The route now delegates to the user-scoped rebuilder.

The keyword reference backend currently has no persistent index, so there is nothing to rebuild for it. When a persistent sparse backend is introduced, its rebuild operation should be added behind the same rebuild service rather than exposed directly to the router.

## Integration into the local RetrievalRouter branch

When `agent/retrieval-foundation` is available, the intended integration is:

1. construct a `MaterialSearchScope` from the router request/user/project/material constraints;
2. call `create_material_retrieval_backend(db, mode="hybrid")` from the router's material source adapter;
3. normalize each `MaterialChunkHit.to_dict()` into the router's common result type while preserving `source`, `chunk_index`, and backend provenance;
4. replace the main-chat direct `get_rag_service().retrieve(...)` path with the router material search path;
5. keep the existing large-material truncation path only as the final fallback when the router returns no usable material chunks;
6. run focused router/material tests, then the full backend and repository CI gates.

This branch intentionally does not edit the unpushed local `RetrievalRouter`, so it can be rebased or cherry-picked without reconstructing or overwriting Phase 1 work.
