"""Anki 风格记忆卡路由"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import csv
import io
from typing import Optional

from uuid import UUID
from app.services.review_attempts import reserve_review_attempt, finish_review_attempt, replay_review_attempt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.anki import AnkiCard
from app.models.user import User
from app.ai.factory import AIProviderFactory
from app.services.learning_event_service import (
    record_review_completed_event,
    record_review_scheduled_event,
)
from app.services.projection_outbox_service import process_event_projection
from app.services.review_scheduler import apply_review
from app.utils.prompt_safety import wrap_untrusted_context
from app.utils.sync import begin_idempotent_operation, complete_idempotent_operation, flush_sync_mutation, require_matching_version
from app.utils.utc import to_db_utc, to_utc_iso, utc_now_db


router = APIRouter()


class AnkiCardCreate(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    tags: Optional[str] = None
    note: Optional[str] = None


class AnkiCardReview(BaseModel):
    attempt_id: UUID
    quality: int = Field(..., ge=0, le=5)
    expected_version: Optional[int] = Field(None, ge=1)
    reviewed_at: Optional[datetime] = None


class AnkiCardUpdate(BaseModel):
    front: Optional[str] = Field(None, min_length=1)
    back: Optional[str] = Field(None, min_length=1)
    tags: Optional[str] = None
    note: Optional[str] = None


class AnkiAIGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    source_text: Optional[str] = None
    count: int = Field(5, ge=1, le=20)
    tags: Optional[str] = None


class AnkiCSVImportRequest(BaseModel):
    csv_text: str = Field(..., min_length=1)


def _to_item(card: AnkiCard) -> dict:
    return {
        "id": card.id,
        "front": card.front,
        "back": card.back,
        "source": card.source,
        "tags": card.tags,
        "note": card.note,
        "due_at": to_utc_iso(card.due_at) if card.due_at else None,
        "interval_days": card.interval_days,
        "ease_factor": card.ease_factor,
        "repetitions": card.repetitions,
        "last_quality": card.last_quality,
        "stability": card.stability,
        "difficulty": card.difficulty,
        "created_at": to_utc_iso(card.created_at) if card.created_at else None,
        "updated_at": to_utc_iso(card.updated_at) if card.updated_at else None,
        "sync_version": card.sync_version,
    }


def _extract_json(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


@router.get("/cards")
async def list_cards(
    scope: str = Query("due", pattern="^(due|all)$"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    after_id: Optional[int] = Query(None, ge=0),
):
    query = select(AnkiCard).where(AnkiCard.user_id == current_user.id)
    if scope == "due":
        query = query.where(AnkiCard.due_at <= utc_now_db())

    if isinstance(after_id, int):
        query = query.where(AnkiCard.id > after_id).order_by(AnkiCard.id.asc())
    else:
        query = query.order_by(AnkiCard.due_at.asc(), AnkiCard.id.asc())
    query = query.limit(limit)
    result = await db.execute(query)
    cards = list(result.scalars().all())
    return [_to_item(card) for card in cards]


@router.post("/cards")
async def create_card(
    body: AnkiCardCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="POST", path="/api/anki/cards", body=body.dict(),
    )
    if operation.replay is not None:
        return operation.replay
    card = AnkiCard(
        user_id=current_user.id,
        front=body.front.strip(),
        back=body.back.strip(),
        source="manual",
        tags=(body.tags or "").strip() or None,
        note=(body.note or "").strip() or None,
        due_at=utc_now_db(),
        interval_days=1,
        ease_factor=250,
        repetitions=0,
    )
    db.add(card)
    await db.flush()
    await db.refresh(card)
    await record_review_scheduled_event(
        db,
        int(current_user.id),
        entity_type="anki_card",
        entity_id=int(card.id),
        due_at=card.due_at or utc_now_db(),
        source="anki_router",
        item_type="anki_card",
        item_id=int(card.id),
        reason="card_created",
    )
    item = _to_item(card)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.put("/cards/{card_id}")
async def update_card(
    card_id: int,
    body: AnkiCardUpdate,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="PUT", path=f"/api/anki/cards/{card_id}", body=body.dict(exclude_unset=True), if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    card = await db.scalar(select(AnkiCard).where(AnkiCard.id == card_id, AnkiCard.user_id == current_user.id))
    if card is None:
        raise HTTPException(status_code=404, detail="卡片不存在")
    require_matching_version(card.sync_version, if_match)
    for field, value in body.dict(exclude_unset=True).items():
        if field in {"front", "back"}:
            if value is None or not value.strip():
                raise HTTPException(status_code=400, detail="卡片正反面内容不能为空")
            value = value.strip()
        setattr(card, field, value)
    await flush_sync_mutation(db)
    await db.refresh(card)
    item = _to_item(card)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.delete("/cards/{card_id}")
async def delete_card(
    card_id: int,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="DELETE", path=f"/api/anki/cards/{card_id}", body={}, if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    card = await db.scalar(select(AnkiCard).where(AnkiCard.id == card_id, AnkiCard.user_id == current_user.id))
    if card is None:
        raise HTTPException(status_code=404, detail="卡片不存在")
    require_matching_version(card.sync_version, if_match)
    await db.delete(card)
    await flush_sync_mutation(db)
    item = {"ok": True}
    await complete_idempotent_operation(db, operation, item)
    return item


@router.post("/cards/{card_id}/review")
async def review_card(
    card_id: int,
    body: AnkiCardReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await reserve_review_attempt(db, int(current_user.id), f"/api/anki/cards/{card_id}/review", body)
    if operation.replay is not None:
        return operation.replay
    result = await db.execute(select(AnkiCard).execution_options(populate_existing=True).where(AnkiCard.id == card_id, AnkiCard.user_id == current_user.id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")

    if body.expected_version is not None:
        require_matching_version(card.sync_version, str(body.expected_version))
    now = to_db_utc(body.reviewed_at) if body.reviewed_at else utc_now_db()
    if now > utc_now_db() + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="复习时间不能晚于当前时间")
    if card.last_review_at and now < to_db_utc(card.last_review_at):
        raise HTTPException(status_code=409, detail={"code": "SYNC_CONFLICT", "message": "其他设备已提交较新的复习，请核对后处理"})
    scheduled_for = card.due_at or now
    schedule = apply_review(card, body.quality, now, due_attr="due_at")

    await flush_sync_mutation(db)
    await db.refresh(card)
    completed_event = await record_review_completed_event(
        db,
        int(current_user.id),
        entity_type="anki_card",
        entity_id=int(card.id),
        scheduled_for=scheduled_for,
        source="anki_router",
        quality=body.quality,
        item_type="anki_card",
        item_id=int(card.id),
        next_due_at=schedule.due_at,
        scheduler=schedule.algorithm,
        occurred_at=now,
    )
    await process_event_projection(
        db,
        user_id=int(current_user.id),
        source_event_id=int(completed_event["id"]),
        max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
        retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
    )
    await record_review_scheduled_event(
        db,
        int(current_user.id),
        entity_type="anki_card",
        entity_id=int(card.id),
        due_at=schedule.due_at,
        source="anki_router",
        item_type="anki_card",
        item_id=int(card.id),
        reason="review_completed",
        occurred_at=now,
    )
    return await finish_review_attempt(db, operation, _to_item(card))


@router.post("/cards/ai-generate")
async def ai_generate_cards(
    body: AnkiAIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source_text = (body.source_text or "").strip()
    prompt = (
        "你是一名学习卡片助手。请根据主题和素材，生成适合记忆复习的问答卡片。\n"
        + wrap_untrusted_context(
            "卡片素材",
            (
                f"主题: {body.topic.strip()}\n"
                f"素材:\n{source_text if source_text else '（无素材，基于主题生成）'}"
            ),
            source=f"anki_generate:{current_user.id}",
        )
        + f"\n数量: {body.count}"
        "\n输出要求：只输出 JSON 数组，不要额外解释。"
        "\n格式：[{'front':'问题','back':'答案'}]"
    )

    provider = await AIProviderFactory.create_provider(db=db, user_id=current_user.id)
    ai_text = await provider.chat(messages=[{"role": "user", "content": prompt}], temperature=0.6)

    raw = _extract_json(ai_text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"AI 输出解析失败: {exc}") from exc

    if not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="AI 输出格式错误：应为数组")

    created = []
    for item in parsed[: body.count]:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front", "")).strip()
        back = str(item.get("back", "")).strip()
        if not front or not back:
            continue

        card = AnkiCard(
            user_id=current_user.id,
            front=front,
            back=back,
            source="ai",
            tags=(body.tags or "").strip() or None,
            due_at=utc_now_db(),
            interval_days=1,
            ease_factor=250,
            repetitions=0,
        )
        db.add(card)
        created.append(card)

    await db.flush()
    for card in created:
        await db.refresh(card)
        await record_review_scheduled_event(
            db,
            int(current_user.id),
            entity_type="anki_card",
            entity_id=int(card.id),
            due_at=card.due_at or utc_now_db(),
            source="anki_router",
            item_type="anki_card",
            item_id=int(card.id),
            reason="ai_card_created",
        )

    return {
        "created": len(created),
        "cards": [_to_item(card) for card in created],
    }


@router.get("/queue")
async def get_anki_queue(
    new_limit: int = Query(20, ge=1, le=200),
    review_limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = utc_now_db()

    review_result = await db.execute(
        select(AnkiCard)
        .where(
            AnkiCard.user_id == current_user.id,
            AnkiCard.due_at <= now,
            AnkiCard.last_quality.is_not(None),
        )
        .order_by(AnkiCard.due_at.asc(), AnkiCard.id.asc())
        .limit(review_limit)
    )
    review_cards = list(review_result.scalars().all())

    new_result = await db.execute(
        select(AnkiCard)
        .where(
            AnkiCard.user_id == current_user.id,
            AnkiCard.last_quality.is_(None),
        )
        .order_by(AnkiCard.created_at.asc(), AnkiCard.id.asc())
        .limit(new_limit)
    )
    new_cards = list(new_result.scalars().all())

    return {
        "new_cards": [_to_item(card) for card in new_cards],
        "review_cards": [_to_item(card) for card in review_cards],
    }


@router.get("/cards/export")
async def export_cards_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AnkiCard)
        .where(AnkiCard.user_id == current_user.id)
        .order_by(AnkiCard.created_at.asc(), AnkiCard.id.asc())
    )
    cards = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "front",
            "back",
            "tags",
            "note",
            "source",
            "due_at",
            "interval_days",
            "ease_factor",
            "repetitions",
            "last_quality",
        ],
    )
    writer.writeheader()
    for card in cards:
        writer.writerow(
            {
                "front": card.front,
                "back": card.back,
                "tags": card.tags or "",
                "note": card.note or "",
                "source": card.source or "manual",
                "due_at": card.due_at.isoformat() if card.due_at else "",
                "interval_days": card.interval_days or 1,
                "ease_factor": card.ease_factor or 250,
                "repetitions": card.repetitions or 0,
                "last_quality": card.last_quality if card.last_quality is not None else "",
            }
        )

    return {
        "filename": f"anki_cards_{utc_now_db().strftime('%Y%m%d_%H%M%S')}.csv",
        "csv": output.getvalue(),
        "count": len(cards),
    }


@router.post("/cards/import")
async def import_cards_csv(
    body: AnkiCSVImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    text = (body.csv_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="CSV 内容不能为空")

    reader = csv.DictReader(io.StringIO(text))
    created = 0
    skipped = 0
    created_cards: list[AnkiCard] = []

    for row in reader:
        front = str(row.get("front", "")).strip()
        back = str(row.get("back", "")).strip()
        if not front or not back:
            skipped += 1
            continue

        due_at_str = str(row.get("due_at", "")).strip()
        due_at = None
        if due_at_str:
            try:
                due_at = datetime.fromisoformat(due_at_str)
            except ValueError:
                due_at = None

        try:
            interval_days = max(1, int(str(row.get("interval_days", "1") or "1")))
        except ValueError:
            interval_days = 1

        try:
            ease_factor = max(130, int(str(row.get("ease_factor", "250") or "250")))
        except ValueError:
            ease_factor = 250

        try:
            repetitions = max(0, int(str(row.get("repetitions", "0") or "0")))
        except ValueError:
            repetitions = 0

        last_quality_raw = str(row.get("last_quality", "")).strip()
        last_quality = None
        if last_quality_raw:
            try:
                last_quality = min(5, max(0, int(last_quality_raw)))
            except ValueError:
                last_quality = None

        card = AnkiCard(
            user_id=current_user.id,
            front=front,
            back=back,
            source=str(row.get("source", "manual") or "manual")[:20],
            tags=str(row.get("tags", "") or "").strip() or None,
            note=str(row.get("note", "") or "").strip() or None,
            due_at=due_at or utc_now_db(),
            interval_days=interval_days,
            ease_factor=ease_factor,
            repetitions=repetitions,
            last_quality=last_quality,
        )
        db.add(card)
        created_cards.append(card)
        created += 1

    await db.flush()
    for card in created_cards:
        await record_review_scheduled_event(
            db,
            int(current_user.id),
            entity_type="anki_card",
            entity_id=int(card.id),
            due_at=card.due_at or utc_now_db(),
            source="anki_router",
            item_type="anki_card",
            item_id=int(card.id),
            reason="card_imported",
        )
    return {"created": created, "skipped": skipped}
