# ContextStore Chat Note Migration Design

**Date:** 2026-08-09
**Status:** Approved design, pending implementation plan
**Scope:** Phase 1 `ContextStore` first real business flow

## Goal

Make the user-facing chat note-context retrieval path depend only on the
`ContextStore` interface. Preserve the current chat experience and retrieval
quality while making the active keyword-SQL fallback observable.

This is the first Phase 1 business-flow migration. It deliberately does not
turn the existing AgentKernel prototype into the acceptance path.

## Scope

In scope:

- Both streaming and synchronous chat note-context retrieval paths.
- Note-only retrieval through `ContextStore.retrieve` with
  `source_types=("note",)`.
- Moving the current note tokenization, ranking, excerpt selection, and
  metadata production into `KeywordContextStore`.
- Adapting `ContextItem` values back into the existing `NoteContextHit`
  presentation contract.
- Observability, quality, update, deletion, and user-isolation regression
  coverage.

Out of scope:

- Material RAG, Chroma, Qdrant, reranking, embeddings, or a retrieval spike.
- User memory retrieval and memory declarations.
- Obsidian stable IDs, synchronization conflicts, and deletion workflow.
- A new database schema, Alembic migration, ContextStore outbox projection, or
  new background worker.
- A new end-user settings or status page.

## Chosen Approach

Use a ContextStore-first adapter, not a direct switch to the existing generic
keyword query.

`KeywordContextStore` becomes the owner of the note retrieval profile used by
chat. It preserves the current deterministic semantics:

- English-token and CJK bigram extraction.
- Title and tag matches ranked above body matches.
- A compact excerpt centered around the first matching term.
- A small recency tie-breaker.
- Strict `user_id` filtering in the store, rather than caller convention.

The existing `note_context_service` retains chat-specific presentation
responsibilities: prompt-safety wrapping, prompt construction, and SSE
indicator shaping. It no longer selects or scores `Note` rows directly.

## Architecture

```text
streaming chat / synchronous chat
    -> search_note_context()
    -> ContextStore.retrieve(source_types=("note",))
    -> KeywordContextStore note retrieval profile
    -> ContextItem(metadata: tags, reason, updated_at, retrieval_mode)
    -> NoteContextHit
    -> existing prompt safety wrapper and SSE note indicators
```

The chat router keeps its existing two call sites and fallback boundary. Both
paths call `search_note_context`, so they receive the same retrieval behavior.

## Interface and Metadata

`ContextItem` remains the shared cross-source result type. For note results,
its metadata includes:

| Field | Meaning |
| --- | --- |
| `tags` | Parsed note tags for the existing chat indicator. |
| `reason` | Deterministic, user-safe ranking explanation. |
| `updated_at` | Timestamp used only for presentation and stable tie-breaking. |
| `retrieval_mode` | `keyword_sql` for the active fallback implementation. |

`search_note_context` converts those values into the existing `NoteContextHit`
type. Metadata must be treated as optional and defensive defaults must avoid a
chat failure if a future ContextStore implementation omits a note-specific
field.

## Runtime Behavior

For a non-empty query, the note-context adapter calls the configured global
ContextStore exactly once and requests only notes. The store returns no more
than the requested limit after user-scoped ranking. Empty queries return no
note context.

The keyword-SQL store reads the current `notes` table directly. Consequently,
an update is reflected on the next query and a deleted note is absent on the
next query without a secondary-index update. `ingest` and `forget` remain
valid no-ops for this fallback implementation; this migration does not claim
that a future external index has been implemented.

## Failure and Privacy Rules

- A ContextStore exception is caught at the existing chat boundary. Chat
  continues without appended note context.
- The adapter must not silently fall back to the former direct-SQL retrieval
  implementation; doing so would leave the business path un-migrated.
- Query text, note content, and prompts are not written to retrieval telemetry.
- Every retrieval query includes `user_id` in the ContextStore operation.
  Results belonging to another user are never transformed into chat context.
- Retrieved note text remains wrapped as untrusted context before it is sent to
  an AI provider.

## Observability

Each note result carries `retrieval_mode="keyword_sql"`. The existing
`note_context_indicators` SSE payload exposes that non-sensitive mode as an
additive field on every indicator. The backend emits a structured
`contextstore.retrieve` log with mode, source types, result count, and success
or failure status, without the query or note content.

This provides a testable and operationally useful signal that the keyword
fallback, rather than a future semantic implementation, served the result.

## Acceptance Tests

The implementation must add or adapt focused tests for:

1. Existing retrieval quality cases, including multi-term/CJK matching, title
   and tag ranking, and nearby excerpts.
2. User isolation at the ContextStore and adapter boundaries.
3. ContextStore replacement in tests: the chat adapter calls the configured
   store rather than querying notes directly.
4. Update visibility: changed note content is retrieved on the next request.
5. Deletion visibility: a deleted note is absent on the next request.
6. Prompt safety remains applied to retrieved note content.
7. Streaming chat continues emitting the existing note indicators; synchronous
   chat uses the same adapter.
8. The active `keyword_sql` retrieval mode is observable without exposing
   sensitive content.

No database migration is required. Verification will run the focused backend
tests first, then the relevant chat regression tests, followed by the normal
backend quality checks that remain feasible in the local environment.

## Rollback

The change is code-only. Reverting the adapter and note retrieval profile
restores the prior chat retrieval path without data migration or data loss.
Until an external ContextStore implementation passes a separate spike, the
keyword-SQL store remains the production fallback.
