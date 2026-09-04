"""Unified extraction, grounding, persistence, and durable run lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    EntityResolutionCandidate,
    KnowledgeExtractionRun,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.schemas.knowledge_extraction import (
    ExtractedClaim,
    ExtractedConceptMention,
    ExtractedEvidence,
    KnowledgeExtractionResult,
)
from app.utils.error_safety import safe_exception_summary
from app.utils.prompt_safety import wrap_untrusted_context
from app.utils.utc import to_utc_iso, utc_now_db


SCHEMA_VERSION = 1
DETERMINISTIC_EXTRACTOR_VERSION = "deterministic-rules-v1"
LLM_EXTRACTOR_VERSION = "llm-json-v1"
RUN_STATUSES = frozenset({"queued", "running", "succeeded", "partial", "failed", "cancelled"})
RETRYABLE_STATUSES = frozenset({"partial", "failed", "cancelled"})

_PUNCTUATION_MAP = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "…": "...",
    }
)
_MARKDOWN_PREFIX = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_DEFINITION = re.compile(
    r"^(?P<name>.{2,80}?)(?:\s*[：:]\s*|\s+(?:是指|指的是|means|refers to|is defined as)\s+)(?P<body>.{4,})$",
    re.IGNORECASE,
)
_ALIAS = re.compile(
    r"(?P<name>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58})"
    r"\s*[（(](?P<alias>[^()（）\n]{2,80})[）)]"
)
_ARROW = re.compile(
    r"(?P<first>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58}?)"
    r"\s*(?:→|->)\s*"
    r"(?P<second>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58})"
)
_PREREQUISITE = re.compile(
    r"(?P<first>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58}?)"
    r"\s*(?:是|为)\s*"
    r"(?P<second>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58}?)"
    r"\s*(?:的)?先修(?:知识|概念|条件)?"
)
_CAUSAL_MARKERS = ("导致", "因此", "所以", "because", "therefore", "results in", "causes")
_RECOMMENDATION_MARKERS = ("应该", "建议", "需要", "must", "should", "recommend")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_claim_statement(statement: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(statement or "")).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def claim_fingerprint(statement: str) -> str:
    normalized = normalize_claim_statement(statement)
    if not normalized:
        raise ValueError("Claim 内容不能为空。")
    return _sha256(normalized)


def _clean_statement(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_concept(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" -*_`#：:，,。.;；")[:120]


def _json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if len(text) > int(settings.KNOWLEDGE_EXTRACTION_MAX_OUTPUT_CHARS):
        raise ValueError("抽取输出超过允许的最大长度。")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("抽取输出必须是 JSON 对象。")
    return value


class DeterministicKnowledgeExtractor:
    """Conservative local rules adapted to the shared extraction schema."""

    extractor_type = "deterministic"
    version = DETERMINISTIC_EXTRACTOR_VERSION

    async def extract(self, unit: KnowledgeUnit) -> KnowledgeExtractionResult:
        claims: list[ExtractedClaim] = []
        seen: set[str] = set()

        def add(
            quote: str,
            *,
            statement: str | None = None,
            claim_kind: str = "observation",
            concepts: Iterable[str] = (),
            confidence: float = 0.78,
        ) -> None:
            if len(claims) >= int(settings.KNOWLEDGE_EXTRACTION_MAX_CLAIMS_PER_UNIT):
                return
            clean_quote = str(quote or "").strip()
            clean_statement = _clean_statement(statement or _MARKDOWN_PREFIX.sub("", clean_quote))
            fingerprint = claim_fingerprint(clean_statement) if clean_statement else ""
            if not clean_quote or not clean_statement or fingerprint in seen:
                return
            mentions = []
            mention_seen: set[str] = set()
            for concept in concepts:
                clean = _clean_concept(concept)
                key = clean.casefold()
                if len(clean) >= 2 and key not in mention_seen:
                    mentions.append(ExtractedConceptMention(text=clean, relation_type="about"))
                    mention_seen.add(key)
            claims.append(
                ExtractedClaim(
                    local_id=f"c{len(claims) + 1}",
                    statement=clean_statement[:500],
                    claim_kind=claim_kind,
                    evidence=[ExtractedEvidence(quote=clean_quote)],
                    concepts=mentions,
                    confidence=confidence,
                )
            )
            seen.add(fingerprint)

        for raw_line in str(unit.text or "").splitlines():
            quote = raw_line.strip()
            if not quote or re.fullmatch(r"#{1,6}\s+.+", quote):
                continue
            line = _MARKDOWN_PREFIX.sub("", quote).strip()
            definition = _DEFINITION.match(line)
            if definition:
                add(
                    quote,
                    statement=line,
                    claim_kind="definition",
                    concepts=[definition.group("name")],
                    confidence=0.86,
                )
                continue
            prerequisite = _PREREQUISITE.search(line)
            arrow = _ARROW.search(line)
            relation = prerequisite or arrow
            if relation:
                add(
                    quote,
                    statement=line,
                    claim_kind="principle",
                    concepts=[relation.group("first"), relation.group("second")],
                    confidence=0.82,
                )
                continue
            alias = _ALIAS.search(line)
            if alias and len(line) <= 240:
                add(
                    quote,
                    statement=line,
                    claim_kind="observation",
                    concepts=[alias.group("name"), alias.group("alias")],
                    confidence=0.8,
                )
                continue
            lowered = line.casefold()
            if any(marker in lowered for marker in _CAUSAL_MARKERS):
                add(quote, statement=line, claim_kind="causal", confidence=0.74)
            elif any(marker in lowered for marker in _RECOMMENDATION_MARKERS):
                add(quote, statement=line, claim_kind="recommendation", confidence=0.74)

        return KnowledgeExtractionResult(claims=claims, relations=[])


class LLMKnowledgeExtractor:
    """Provider-neutral LLM extractor with native-structured and JSON paths."""

    extractor_type = "llm"
    version = LLM_EXTRACTOR_VERSION

    def __init__(self, provider: Any):
        self.provider = provider

    @staticmethod
    def _prompt(unit: KnowledgeUnit) -> str:
        schema = json.dumps(
            KnowledgeExtractionResult.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        instructions = (
            "从下面一个来源 Unit 中提取可独立比较的原子 Claim。只概括来源实际表达的内容。"
            "每条 Claim 必须给出可在原文定位的逐字 evidence.quote；关系只能引用本次 local_id。"
            "不要输出推理过程，不要创建来源没有表达的事实。输出必须严格满足 JSON Schema：\n"
            f"{schema}\n"
        )
        return instructions + wrap_untrusted_context(
            "知识来源 Unit",
            str(unit.text or "")[: int(settings.KNOWLEDGE_EXTRACTION_MAX_UNIT_CHARS)],
            source=f"knowledge_unit:{int(unit.id)}",
            max_chars=int(settings.KNOWLEDGE_EXTRACTION_MAX_UNIT_CHARS),
        )

    @staticmethod
    def _structured_unsupported(exc: BaseException) -> bool:
        if isinstance(exc, (AttributeError, NotImplementedError, TypeError)):
            return True
        text = str(exc).casefold()
        return any(
            marker in text
            for marker in (
                "response_format",
                "json_schema",
                "structured output",
                "not support",
                "unsupported",
                "unknown parameter",
            )
        )

    async def extract(self, unit: KnowledgeUnit) -> KnowledgeExtractionResult:
        prompt = self._prompt(unit)
        messages = [{"role": "user", "content": prompt}]
        response: Any = None
        supports_structured = bool(
            getattr(self.provider, "supports_structured_output", lambda: False)()
        )
        if supports_structured:
            try:
                response = await asyncio.wait_for(
                    self.provider.chat_structured(
                        messages=messages,
                        response_model=KnowledgeExtractionResult,
                        system_prompt="你是保守的知识 Claim 抽取器。只返回指定结构。",
                        temperature=0.1,
                    ),
                    timeout=float(settings.KNOWLEDGE_EXTRACTION_TIMEOUT_SECONDS),
                )
            except Exception as exc:
                if not self._structured_unsupported(exc):
                    raise
        if response is None:
            response = await asyncio.wait_for(
                self.provider.chat(
                    messages=messages,
                    system_prompt="你是保守的知识 Claim 抽取器，只输出 JSON。",
                    temperature=0.1,
                ),
                timeout=float(settings.KNOWLEDGE_EXTRACTION_TIMEOUT_SECONDS),
            )
        if isinstance(response, KnowledgeExtractionResult):
            result = response
        elif isinstance(response, str):
            result = KnowledgeExtractionResult.model_validate(_json_object(response))
        else:
            result = KnowledgeExtractionResult.model_validate(response)
        if len(result.model_dump_json()) > int(settings.KNOWLEDGE_EXTRACTION_MAX_OUTPUT_CHARS):
            raise ValueError("抽取输出超过允许的最大长度。")
        max_claims = int(settings.KNOWLEDGE_EXTRACTION_MAX_CLAIMS_PER_UNIT)
        if len(result.claims) > max_claims:
            result = result.model_copy(
                update={
                    "claims": result.claims[:max_claims],
                    "relations": [
                        relation
                        for relation in result.relations
                        if relation.from_local_id in {claim.local_id for claim in result.claims[:max_claims]}
                        and relation.to_local_id in {claim.local_id for claim in result.claims[:max_claims]}
                    ],
                }
            )
        return result


@dataclass(frozen=True)
class GroundedEvidence:
    excerpt: str
    char_start: int
    char_end: int
    grounding_method: str
    confidence: float


@dataclass(frozen=True)
class GroundedClaim:
    candidate: ExtractedClaim
    statement: str
    evidence: tuple[GroundedEvidence, ...]


@dataclass(frozen=True)
class GroundingResult:
    claims: tuple[GroundedClaim, ...]
    accepted_relations: int
    rejected_claims: int
    rejected_evidence: int


def _normalize_with_map(value: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    source_indexes: list[int] = []
    for source_index, raw_char in enumerate(str(value or "")):
        normalized_piece = unicodedata.normalize("NFKC", raw_char).translate(_PUNCTUATION_MAP)
        for char in normalized_piece:
            if char.isspace():
                if not chars or chars[-1] == " ":
                    continue
                chars.append(" ")
                source_indexes.append(source_index)
            else:
                chars.append(char.casefold())
                source_indexes.append(source_index)
    while chars and chars[0] == " ":
        chars.pop(0)
        source_indexes.pop(0)
    while chars and chars[-1] == " ":
        chars.pop()
        source_indexes.pop()
    return "".join(chars), source_indexes


def locate_evidence(unit_text: str, evidence: ExtractedEvidence) -> GroundedEvidence | None:
    """Locate a quote exactly, then with bounded Unicode/space/punctuation normalization."""

    text = str(unit_text or "")
    quote = str(evidence.quote or "")
    if not quote:
        return None
    if evidence.char_start is not None:
        start = int(evidence.char_start)
        end = int(evidence.char_end) if evidence.char_end is not None else start + len(quote)
        if 0 <= start < end <= len(text) and text[start:end] == quote:
            return GroundedEvidence(quote, start, end, "exact_span", 1.0)
    exact_start = text.find(quote)
    if exact_start >= 0:
        return GroundedEvidence(
            quote,
            exact_start,
            exact_start + len(quote),
            "exact_span",
            1.0,
        )

    normalized_text, source_map = _normalize_with_map(text)
    normalized_quote, _ = _normalize_with_map(quote)
    if not normalized_quote or not source_map:
        return None
    normalized_start = normalized_text.find(normalized_quote)
    if normalized_start < 0:
        return None
    normalized_end = normalized_start + len(normalized_quote)
    start = source_map[normalized_start]
    end = source_map[normalized_end - 1] + 1
    if start < 0 or end <= start or end > len(text):
        return None
    return GroundedEvidence(text[start:end], start, end, "normalized_span", 0.96)


def _is_uninformative(statement: str, evidence: tuple[GroundedEvidence, ...], unit_text: str) -> bool:
    clean = _clean_statement(statement)
    if not clean or len(clean) > min(500, int(settings.KNOWLEDGE_CLAIM_MAX_CHARS)):
        return True
    if clean.startswith("#"):
        return True
    for grounded in evidence:
        line_start = str(unit_text).rfind("\n", 0, grounded.char_start) + 1
        line_end = str(unit_text).find("\n", grounded.char_end)
        if line_end < 0:
            line_end = len(str(unit_text))
        line = str(unit_text)[line_start:line_end].strip()
        if line.startswith("#") and _clean_statement(line.lstrip("# ")) == clean:
            return True
    return False


def ground_extraction_result(
    unit_text: str,
    result: KnowledgeExtractionResult,
) -> GroundingResult:
    grounded_claims: list[GroundedClaim] = []
    accepted_ids: set[str] = set()
    rejected_claims = 0
    rejected_evidence = 0
    for candidate in result.claims[: int(settings.KNOWLEDGE_EXTRACTION_MAX_CLAIMS_PER_UNIT)]:
        grounded: list[GroundedEvidence] = []
        spans: set[tuple[int, int]] = set()
        for evidence in candidate.evidence:
            located = locate_evidence(unit_text, evidence)
            if located is None:
                rejected_evidence += 1
                continue
            span = (located.char_start, located.char_end)
            if span not in spans:
                grounded.append(located)
                spans.add(span)
        grounded_tuple = tuple(grounded)
        statement = _clean_statement(candidate.statement)
        if not grounded_tuple or _is_uninformative(statement, grounded_tuple, unit_text):
            rejected_claims += 1
            continue
        grounded_claims.append(
            GroundedClaim(candidate=candidate, statement=statement, evidence=grounded_tuple)
        )
        accepted_ids.add(candidate.local_id)
    accepted_relations = 0
    for relation in result.relations:
        if relation.from_local_id not in accepted_ids or relation.to_local_id not in accepted_ids:
            continue
        if relation.evidence_quote is not None and locate_evidence(
            unit_text,
            ExtractedEvidence(quote=relation.evidence_quote),
        ) is None:
            continue
        accepted_relations += 1
    return GroundingResult(
        claims=tuple(grounded_claims),
        accepted_relations=accepted_relations,
        rejected_claims=rejected_claims,
        rejected_evidence=rejected_evidence,
    )


async def create_extraction_run(
    db: AsyncSession,
    *,
    user_id: int,
    source_revision_id: int,
    extractor_type: str,
    extractor_version: str | None = None,
    schema_version: int = SCHEMA_VERSION,
    provider: str | None = None,
    model: str | None = None,
    force: bool = False,
) -> KnowledgeExtractionRun:
    normalized_type = str(extractor_type).strip().lower()
    if normalized_type not in {"deterministic", "llm"}:
        raise ValueError("仅支持 deterministic 或 llm 自动抽取。")
    version = extractor_version or (
        DETERMINISTIC_EXTRACTOR_VERSION
        if normalized_type == "deterministic"
        else LLM_EXTRACTOR_VERSION
    )
    revision = await db.scalar(
        select(KnowledgeSourceRevision)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            KnowledgeSourceRevision.id == int(source_revision_id),
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.status == "active",
        )
        .with_for_update()
    )
    if revision is None:
        raise PermissionError("来源版本不存在、不可见或不属于当前用户。")
    # The input hash describes source input only; extractor/schema versions are
    # separate columns in the durable idempotency key.
    input_hash = str(revision.content_hash)
    run = await db.scalar(
        select(KnowledgeExtractionRun).where(
            KnowledgeExtractionRun.source_revision_id == int(revision.id),
            KnowledgeExtractionRun.extractor_type == normalized_type,
            KnowledgeExtractionRun.extractor_version == version,
            KnowledgeExtractionRun.schema_version == int(schema_version),
            KnowledgeExtractionRun.input_hash == input_hash,
        )
    )
    now = utc_now_db()
    if run is not None:
        if int(run.user_id) != int(user_id):
            raise PermissionError("Extraction Run 不属于当前用户。")
        if force:
            run.status = "queued"
            run.available_at = now
            run.locked_at = None
            run.lease_owner = None
            run.finished_at = None
            run.last_error = None
            run.attempt_count = 0
            run.stats = {}
            run.usage = {}
        return run
    prompt_hash = (
        _sha256("knowledge-claim-extraction-prompt-v1")
        if normalized_type == "llm"
        else None
    )
    run = KnowledgeExtractionRun(
        user_id=int(user_id),
        source_revision_id=int(revision.id),
        extractor_type=normalized_type,
        extractor_version=version,
        schema_version=int(schema_version),
        provider=(str(provider)[:80] if provider else None),
        model=(str(model)[:120] if model else None),
        prompt_hash=prompt_hash,
        input_hash=input_hash,
        status="queued",
        available_at=now,
        usage={},
        stats={},
    )
    db.add(run)
    await db.flush()
    return run


async def ensure_default_extraction_runs(
    db: AsyncSession,
    *,
    user_id: int,
    source_revision_id: int,
) -> list[KnowledgeExtractionRun]:
    runs = [
        await create_extraction_run(
            db,
            user_id=int(user_id),
            source_revision_id=int(source_revision_id),
            extractor_type="deterministic",
        )
    ]
    if settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED:
        runs.append(
            await create_extraction_run(
                db,
                user_id=int(user_id),
                source_revision_id=int(source_revision_id),
                extractor_type="llm",
            )
        )
    return runs


async def recover_expired_extraction_runs(
    db: AsyncSession,
    *,
    now=None,
    lease_seconds: int | None = None,
) -> int:
    observed = now or utc_now_db()
    cutoff = observed - timedelta(
        seconds=int(lease_seconds or settings.KNOWLEDGE_EXTRACTION_LEASE_SECONDS)
    )
    rows = list(
        (
            await db.scalars(
                select(KnowledgeExtractionRun)
                .where(
                    KnowledgeExtractionRun.status == "running",
                    KnowledgeExtractionRun.locked_at.is_not(None),
                    KnowledgeExtractionRun.locked_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for run in rows:
        run.status = "queued"
        run.available_at = observed
        run.locked_at = None
        run.lease_owner = None
        run.last_error = "Extraction lease expired; queued for recovery."
    await db.flush()
    return len(rows)


async def claim_next_extraction_run(
    db: AsyncSession,
    *,
    worker_id: str,
    now=None,
    max_attempts: int | None = None,
    lease_seconds: int | None = None,
) -> KnowledgeExtractionRun | None:
    observed = now or utc_now_db()
    attempts = int(max_attempts or settings.KNOWLEDGE_EXTRACTION_MAX_ATTEMPTS)
    lease_cutoff = observed - timedelta(
        seconds=int(lease_seconds or settings.KNOWLEDGE_EXTRACTION_LEASE_SECONDS)
    )
    eligible = or_(
        (
            KnowledgeExtractionRun.status.in_(("queued", "failed"))
            & (KnowledgeExtractionRun.available_at <= observed)
        ),
        (
            (KnowledgeExtractionRun.status == "running")
            & (KnowledgeExtractionRun.locked_at.is_not(None))
            & (KnowledgeExtractionRun.locked_at <= lease_cutoff)
        ),
    )
    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(eligible, KnowledgeExtractionRun.attempt_count < attempts)
        .order_by(KnowledgeExtractionRun.available_at, KnowledgeExtractionRun.created_at, KnowledgeExtractionRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    run.status = "running"
    run.attempt_count = int(run.attempt_count or 0) + 1
    run.locked_at = observed
    run.lease_owner = str(worker_id)[:120]
    run.started_at = run.started_at or observed
    run.finished_at = None
    run.last_error = None
    await db.flush()
    return run


async def retry_extraction_run(
    db: AsyncSession,
    *,
    user_id: int,
    run_id: int,
    force: bool = False,
) -> KnowledgeExtractionRun:
    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(
            KnowledgeExtractionRun.id == int(run_id),
            KnowledgeExtractionRun.user_id == int(user_id),
        )
        .with_for_update()
    )
    if run is None:
        raise PermissionError("Extraction Run 不存在或不属于当前用户。")
    if run.status == "running":
        raise ValueError("正在运行的 Extraction Run 不能重试。")
    if run.status == "succeeded" and not force:
        return run
    if run.status not in RETRYABLE_STATUSES and run.status != "succeeded":
        raise ValueError("当前 Extraction Run 状态不能重试。")
    run.status = "queued"
    run.available_at = utc_now_db()
    run.locked_at = None
    run.lease_owner = None
    run.finished_at = None
    run.last_error = None
    run.attempt_count = 0
    if force:
        run.stats = {}
        run.usage = {}
    await db.flush()
    return run


async def cancel_extraction_run(
    db: AsyncSession,
    *,
    user_id: int,
    run_id: int,
) -> KnowledgeExtractionRun:
    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(
            KnowledgeExtractionRun.id == int(run_id),
            KnowledgeExtractionRun.user_id == int(user_id),
        )
        .with_for_update()
    )
    if run is None:
        raise PermissionError("Extraction Run 不存在或不属于当前用户。")
    if run.status in {"succeeded", "partial", "cancelled"}:
        return run
    run.status = "cancelled"
    run.finished_at = utc_now_db()
    run.locked_at = None
    run.lease_owner = None
    await db.flush()
    return run


async def mark_extraction_run_failed(
    db: AsyncSession,
    *,
    run_id: int,
    worker_id: str,
    error: BaseException | str,
    retry_delay_seconds: float,
) -> bool:
    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(
            KnowledgeExtractionRun.id == int(run_id),
            KnowledgeExtractionRun.status == "running",
            KnowledgeExtractionRun.lease_owner == str(worker_id)[:120],
        )
        .with_for_update()
    )
    if run is None:
        return False
    summary = (
        safe_exception_summary(error)
        if isinstance(error, BaseException)
        else safe_exception_summary(RuntimeError(str(error)))
    )
    now = utc_now_db()
    run.status = "failed"
    run.last_error = summary[:500]
    run.available_at = now + timedelta(seconds=max(0.0, float(retry_delay_seconds)))
    run.finished_at = now
    run.locked_at = None
    run.lease_owner = None
    await db.flush()
    return True


async def _persist_grounded_claims(
    db: AsyncSession,
    *,
    run: KnowledgeExtractionRun,
    unit: KnowledgeUnit,
    grounding: GroundingResult,
    model_version: str | None,
) -> tuple[int, int]:
    from app.services.entity_resolution_service import resolve_claim_mentions
    from app.services.knowledge_projection_service import enqueue_knowledge_object_projection

    claim_count = 0
    evidence_count = 0
    unit_locator = dict(unit.locator or {})
    unit_source_start = int(unit_locator.get("char_start") or 0)
    for grounded in grounding.claims:
        fingerprint = claim_fingerprint(grounded.statement)
        claim = await db.scalar(
            select(Claim).where(
                Claim.source_revision_id == int(run.source_revision_id),
                Claim.fingerprint == fingerprint,
            )
        )
        if claim is None:
            claim = Claim(
                user_id=int(run.user_id),
                source_revision_id=int(run.source_revision_id),
                statement=grounded.statement,
                claim_kind=grounded.candidate.claim_kind,
                fingerprint=fingerprint,
                confidence=float(grounded.candidate.confidence),
                derivation_type=("explicit" if run.extractor_type == "deterministic" else "inferred"),
                review_status="pending",
                lifecycle_status="active",
                extractor_version=str(run.extractor_version),
                schema_version=int(run.schema_version),
                model_version=(str(model_version)[:120] if model_version else None),
            )
            db.add(claim)
            await db.flush()
            claim_count += 1
        elif int(claim.user_id) != int(run.user_id):
            raise PermissionError("Claim 与 Extraction Run 用户不一致。")
        elif claim.derivation_type != "manual" and claim.review_status == "pending":
            claim.confidence = max(float(claim.confidence or 0.0), float(grounded.candidate.confidence))

        existing_evidence = list(
            (
                await db.scalars(
                    select(ClaimEvidence).where(
                        ClaimEvidence.claim_id == int(claim.id),
                        ClaimEvidence.user_id == int(run.user_id),
                    )
                )
            ).all()
        )
        existing_absolute_spans = {
            (
                int((row.locator or {}).get("source_char_start")),
                int((row.locator or {}).get("source_char_end")),
            )
            for row in existing_evidence
            if (row.locator or {}).get("source_char_start") is not None
            and (row.locator or {}).get("source_char_end") is not None
        }
        existing_unit_spans = {
            (int(row.knowledge_unit_id), int(row.char_start), int(row.char_end))
            for row in existing_evidence
        }
        for evidence in grounded.evidence:
            absolute_span = (
                unit_source_start + int(evidence.char_start),
                unit_source_start + int(evidence.char_end),
            )
            unit_span = (int(unit.id), int(evidence.char_start), int(evidence.char_end))
            if absolute_span in existing_absolute_spans or unit_span in existing_unit_spans:
                continue
            locator = dict(unit_locator)
            locator.update(
                {
                    "source_char_start": absolute_span[0],
                    "source_char_end": absolute_span[1],
                }
            )
            db.add(
                ClaimEvidence(
                    user_id=int(run.user_id),
                    claim_id=int(claim.id),
                    knowledge_unit_id=int(unit.id),
                    excerpt=evidence.excerpt,
                    char_start=int(evidence.char_start),
                    char_end=int(evidence.char_end),
                    locator=locator,
                    grounding_method=evidence.grounding_method,
                    confidence=min(
                        float(grounded.candidate.confidence),
                        float(evidence.confidence),
                    ),
                )
            )
            evidence_count += 1
            existing_absolute_spans.add(absolute_span)
            existing_unit_spans.add(unit_span)
        await db.flush()
        await enqueue_knowledge_object_projection(
            db,
            user_id=int(run.user_id),
            object_type="claim",
            object_id=int(claim.id),
        )
        await resolve_claim_mentions(
            db,
            run=run,
            unit=unit,
            claim=claim,
            mentions=grounded.candidate.concepts,
        )
    return claim_count, evidence_count


def _usage_add(total: dict[str, Any], current: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    result = dict(total or {})
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        result[key] = int(result.get(key) or 0) + int(current.get(key) or 0)
    current_cost = current.get("configured_cost_usd")
    if current_cost is not None:
        result["configured_cost_usd"] = round(
            float(result.get("configured_cost_usd") or 0.0) + float(current_cost),
            8,
        )
        result["pricing_configured"] = True
    result["latency_ms"] = round(float(result.get("latency_ms") or 0.0) + elapsed_ms, 3)
    return result


async def _daily_llm_tokens(db: AsyncSession, user_id: int) -> int:
    start = utc_now_db().replace(hour=0, minute=0, second=0, microsecond=0)
    usages = list(
        (
            await db.scalars(
                select(KnowledgeExtractionRun.usage).where(
                    KnowledgeExtractionRun.user_id == int(user_id),
                    KnowledgeExtractionRun.extractor_type == "llm",
                    KnowledgeExtractionRun.created_at >= start,
                )
            )
        ).all()
    )
    return sum(int((usage or {}).get("total_tokens") or 0) for usage in usages)


async def process_claimed_extraction_run(
    db: AsyncSession,
    *,
    run_id: int,
    worker_id: str,
    provider: Any | None = None,
    extractor: Any | None = None,
) -> KnowledgeExtractionRun:
    """Process one leased run; Unit failures are isolated and produce partial."""

    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(
            KnowledgeExtractionRun.id == int(run_id),
            KnowledgeExtractionRun.status == "running",
            KnowledgeExtractionRun.lease_owner == str(worker_id)[:120],
        )
        .with_for_update()
    )
    if run is None:
        raise LookupError("Extraction Run 不存在、未运行或租约不属于当前 worker。")
    revision = await db.scalar(
        select(KnowledgeSourceRevision)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            KnowledgeSourceRevision.id == int(run.source_revision_id),
            KnowledgeSourceRevision.user_id == int(run.user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.status == "active",
        )
        .with_for_update()
    )
    if revision is None:
        run.status = "cancelled"
        run.finished_at = utc_now_db()
        run.locked_at = None
        run.lease_owner = None
        run.last_error = "Source revision is no longer current."
        await db.flush()
        return run
    units = list(
        (
            await db.scalars(
                select(KnowledgeUnit)
                .where(
                    KnowledgeUnit.user_id == int(run.user_id),
                    KnowledgeUnit.source_revision_id == int(run.source_revision_id),
                )
                .order_by(KnowledgeUnit.ordinal, KnowledgeUnit.id)
            )
        ).all()
    )
    stats = dict(run.stats or {})
    processed_ids = {int(value) for value in stats.get("processed_unit_ids", [])}
    failures = [
        item
        for item in stats.get("failed_units", [])
        if isinstance(item, dict) and int(item.get("unit_id") or -1) not in processed_ids
    ]
    stats.update(
        {
            "total_units": len(units),
            "processed_unit_ids": sorted(processed_ids),
            "failed_units": failures,
            "claims": int(stats.get("claims") or 0),
            "evidence": int(stats.get("evidence") or 0),
            "mentions": int(stats.get("mentions") or 0),
            "relations": int(stats.get("relations") or 0),
            "rejected": int(stats.get("rejected") or 0),
            "rejected_evidence": int(stats.get("rejected_evidence") or 0),
        }
    )
    if extractor is None:
        if run.extractor_type == "deterministic":
            extractor = DeterministicKnowledgeExtractor()
        elif run.extractor_type == "llm":
            if provider is None:
                from app.ai.factory import AIProviderFactory

                provider = await AIProviderFactory.create_provider(
                    db=db,
                    scenario="material_analyze",
                    user_id=int(run.user_id),
                )
            extractor = LLMKnowledgeExtractor(provider)
        else:
            raise ValueError("不支持的自动 extractor_type。")

    model_version = str(getattr(provider, "model", "") or "") or None
    if provider is not None:
        run.provider = str(getattr(provider, "provider_name", type(provider).__name__))[:80]
        run.model = str(getattr(provider, "model", ""))[:120] or None
    usage = dict(run.usage or {})
    call_count = int(usage.get("call_count") or 0)
    estimated_tokens = int(usage.get("estimated_tokens") or 0)
    daily_tokens = await _daily_llm_tokens(db, int(run.user_id)) if run.extractor_type == "llm" else 0

    for unit in units:
        unit_id = int(unit.id)
        if unit_id in processed_ids:
            continue
        if run.extractor_type == "llm":
            estimate = max(1, math.ceil(len(str(unit.text or "")) / 4))
            if (
                call_count >= int(settings.KNOWLEDGE_LLM_MAX_CALLS_PER_RUN)
                or estimated_tokens + estimate > int(settings.KNOWLEDGE_LLM_MAX_ESTIMATED_TOKENS_PER_RUN)
                or daily_tokens + estimated_tokens + estimate
                > int(settings.KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER)
            ):
                failures.append({"unit_id": unit_id, "error": "knowledge_extraction_budget_exhausted"})
                continue
            estimated_tokens += estimate
            call_count += 1
        started = time.perf_counter()
        try:
            async with db.begin_nested():
                candidate = await extractor.extract(unit)
                if not isinstance(candidate, KnowledgeExtractionResult):
                    candidate = KnowledgeExtractionResult.model_validate(candidate)
                grounding = ground_extraction_result(str(unit.text or ""), candidate)
                written_claims, written_evidence = await _persist_grounded_claims(
                    db,
                    run=run,
                    unit=unit,
                    grounding=grounding,
                    model_version=model_version,
                )
                stats["claims"] += written_claims
                stats["evidence"] += written_evidence
                stats["mentions"] += sum(
                    len(claim.candidate.concepts) for claim in grounding.claims
                )
                stats["relations"] += grounding.accepted_relations
                stats["rejected"] += grounding.rejected_claims
                stats["rejected_evidence"] += grounding.rejected_evidence
            processed_ids.add(unit_id)
            failures = [item for item in failures if int(item.get("unit_id") or -1) != unit_id]
        except Exception as exc:
            failures.append(
                {
                    "unit_id": unit_id,
                    "error": safe_exception_summary(exc, max_chars=240),
                }
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if provider is not None:
            get_usage = getattr(provider, "get_last_usage", lambda: {})
            usage = _usage_add(usage, dict(get_usage() or {}), elapsed_ms)

    stats["processed_unit_ids"] = sorted(processed_ids)
    deduped_failures: dict[int, dict[str, Any]] = {}
    for failure in failures:
        failure_id = int(failure.get("unit_id") or -1)
        if failure_id not in processed_ids:
            deduped_failures[failure_id] = failure
    stats["failed_units"] = list(deduped_failures.values())
    usage["call_count"] = call_count
    usage["estimated_tokens"] = estimated_tokens
    run.stats = stats
    run.usage = usage
    run.status = "partial" if stats["failed_units"] else "succeeded"
    run.finished_at = utc_now_db()
    run.locked_at = None
    run.lease_owner = None
    run.last_error = (
        f"{len(stats['failed_units'])} Unit(s) failed; successful Units were retained."
        if stats["failed_units"]
        else None
    )
    await db.flush()
    return run


def serialize_extraction_run(run: KnowledgeExtractionRun) -> dict[str, Any]:
    return {
        "id": int(run.id),
        "source_revision_id": int(run.source_revision_id),
        "extractor_type": str(run.extractor_type),
        "extractor_version": str(run.extractor_version),
        "schema_version": int(run.schema_version),
        "provider": run.provider,
        "model": run.model,
        "status": str(run.status),
        "attempt_count": int(run.attempt_count or 0),
        "available_at": to_utc_iso(run.available_at) if run.available_at else None,
        "started_at": to_utc_iso(run.started_at) if run.started_at else None,
        "finished_at": to_utc_iso(run.finished_at) if run.finished_at else None,
        "last_error": run.last_error,
        "usage": dict(run.usage or {}),
        "stats": dict(run.stats or {}),
        "created_at": to_utc_iso(run.created_at) if run.created_at else None,
        "updated_at": to_utc_iso(run.updated_at) if run.updated_at else None,
    }


def _aggregate_status(statuses: set[str]) -> str:
    for status in ("running", "queued", "partial", "failed", "cancelled"):
        if status in statuses:
            return status
    return "succeeded" if "succeeded" in statuses else "not_started"


async def extraction_summary_map(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: str,
    source_record_ids: Iterable[int],
) -> dict[int, dict[str, Any]]:
    record_ids = sorted({int(value) for value in source_record_ids})
    if not record_ids or not settings.KNOWLEDGE_V2_ENABLED:
        return {}
    sources = list(
        (
            await db.scalars(
                select(KnowledgeSource).where(
                    KnowledgeSource.user_id == int(user_id),
                    KnowledgeSource.source_type == str(source_type),
                    KnowledgeSource.source_record_id.in_(record_ids),
                    KnowledgeSource.status == "active",
                )
            )
        ).all()
    )
    source_by_record = {int(source.source_record_id): source for source in sources}
    revisions = list(
        (
            await db.scalars(
                select(KnowledgeSourceRevision).where(
                    KnowledgeSourceRevision.user_id == int(user_id),
                    KnowledgeSourceRevision.knowledge_source_id.in_(
                        [int(source.id) for source in sources] or [-1]
                    ),
                    KnowledgeSourceRevision.status == "current",
                )
            )
        ).all()
    )
    revision_by_source = {int(revision.knowledge_source_id): revision for revision in revisions}
    revision_ids = [int(revision.id) for revision in revisions]
    runs = list(
        (
            await db.scalars(
                select(KnowledgeExtractionRun)
                .where(
                    KnowledgeExtractionRun.user_id == int(user_id),
                    KnowledgeExtractionRun.source_revision_id.in_(revision_ids or [-1]),
                )
                .order_by(KnowledgeExtractionRun.created_at, KnowledgeExtractionRun.id)
            )
        ).all()
    )
    runs_by_revision: dict[int, list[KnowledgeExtractionRun]] = {}
    for run in runs:
        runs_by_revision.setdefault(int(run.source_revision_id), []).append(run)
    pending_rows = (
        await db.execute(
            select(Claim.source_revision_id, func.count(Claim.id))
            .where(
                Claim.user_id == int(user_id),
                Claim.source_revision_id.in_(revision_ids or [-1]),
                Claim.lifecycle_status == "active",
                Claim.review_status == "pending",
            )
            .group_by(Claim.source_revision_id)
        )
    ).all()
    pending_by_revision = {int(revision_id): int(count) for revision_id, count in pending_rows}
    resolution_rows = (
        await db.execute(
            select(Claim.source_revision_id, func.count(EntityResolutionCandidate.id))
            .join(Claim, Claim.id == EntityResolutionCandidate.claim_id)
            .where(
                EntityResolutionCandidate.user_id == int(user_id),
                EntityResolutionCandidate.decision == "pending",
                Claim.user_id == int(user_id),
                Claim.source_revision_id.in_(revision_ids or [-1]),
                Claim.lifecycle_status == "active",
            )
            .group_by(Claim.source_revision_id)
        )
    ).all()
    resolution_by_revision = {
        int(revision_id): int(count) for revision_id, count in resolution_rows
    }
    summaries: dict[int, dict[str, Any]] = {}
    for record_id in record_ids:
        source = source_by_record.get(record_id)
        revision = revision_by_source.get(int(source.id)) if source is not None else None
        current_runs = runs_by_revision.get(int(revision.id), []) if revision is not None else []
        latest_by_type: dict[str, KnowledgeExtractionRun] = {}
        for run in current_runs:
            latest_by_type[str(run.extractor_type)] = run
        statuses = {str(run.status) for run in latest_by_type.values()}
        summaries[record_id] = {
            "enabled": True,
            "llm_enabled": bool(settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED),
            "source_revision_id": int(revision.id) if revision is not None else None,
            "status": _aggregate_status(statuses),
            "deterministic_status": (
                str(latest_by_type["deterministic"].status)
                if "deterministic" in latest_by_type
                else "not_started"
            ),
            "llm_status": (
                str(latest_by_type["llm"].status)
                if "llm" in latest_by_type
                else ("not_started" if settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED else "disabled")
            ),
            "pending_claim_count": pending_by_revision.get(int(revision.id), 0)
            if revision is not None
            else 0,
            "pending_resolution_count": resolution_by_revision.get(int(revision.id), 0)
            if revision is not None
            else 0,
            "runs": [serialize_extraction_run(run) for run in current_runs],
        }
    return summaries


async def get_material_extraction_summary(
    db: AsyncSession,
    *,
    user_id: int,
    material_id: int,
) -> dict[str, Any]:
    summaries = await extraction_summary_map(
        db,
        user_id=int(user_id),
        source_type="material",
        source_record_ids=[int(material_id)],
    )
    if int(material_id) in summaries:
        return summaries[int(material_id)]
    return {
        "enabled": bool(settings.KNOWLEDGE_V2_ENABLED),
        "llm_enabled": bool(settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED),
        "source_revision_id": None,
        "status": "not_registered" if settings.KNOWLEDGE_V2_ENABLED else "disabled",
        "deterministic_status": "not_started",
        "llm_status": "disabled" if not settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED else "not_started",
        "pending_claim_count": 0,
        "pending_resolution_count": 0,
        "runs": [],
    }
