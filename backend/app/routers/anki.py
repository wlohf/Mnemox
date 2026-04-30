"""Anki 风格记忆卡路由"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.anki import AnkiCard
from app.models.user import User
from app.ai.factory import AIProviderFactory


router = APIRouter()


class AnkiCardCreate(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    tags: Optional[str] = None
    note: Optional[str] = None


class AnkiCardReview(BaseModel):
    quality: int = Field(..., ge=0, le=5)


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
        "due_at": card.due_at.isoformat() if card.due_at else None,
        "interval_days": card.interval_days,
        "ease_factor": card.ease_factor,
        "repetitions": card.repetitions,
        "last_quality": card.last_quality,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }


def _sm2_update(interval_days: int, repetitions: int, ease_factor_scaled: int, quality: int):
    ef = (ease_factor_scaled or 250) / 100.0
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(1.3, ef)

    if quality < 3:
        return 1, 0, int(round(ef * 100))

    if repetitions <= 0:
        next_interval = 1
    elif repetitions == 1:
        next_interval = 6
    else:
        base = interval_days or 1
        next_interval = max(1, int(round(base * ef)))

    return next_interval, repetitions + 1, int(round(ef * 100))


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
):
    query = select(AnkiCard).where(AnkiCard.user_id == current_user.id)
    if scope == "due":
        query = query.where(AnkiCard.due_at <= datetime.now())

    query = query.order_by(AnkiCard.due_at.asc(), AnkiCard.id.asc()).limit(limit)
    result = await db.execute(query)
    cards = list(result.scalars().all())
    return [_to_item(card) for card in cards]


@router.post("/cards")
async def create_card(
    body: AnkiCardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    card = AnkiCard(
        user_id=current_user.id,
        front=body.front.strip(),
        back=body.back.strip(),
        source="manual",
        tags=(body.tags or "").strip() or None,
        note=(body.note or "").strip() or None,
        due_at=datetime.now(),
        interval_days=1,
        ease_factor=250,
        repetitions=0,
    )
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return _to_item(card)


@router.post("/cards/{card_id}/review")
async def review_card(
    card_id: int,
    body: AnkiCardReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(AnkiCard).where(AnkiCard.id == card_id, AnkiCard.user_id == current_user.id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")

    next_interval, next_repetitions, next_ef = _sm2_update(
        card.interval_days or 1,
        card.repetitions or 0,
        card.ease_factor or 250,
        body.quality,
    )
    card.interval_days = next_interval
    card.repetitions = next_repetitions
    card.ease_factor = next_ef
    card.last_quality = body.quality
    card.due_at = datetime.now() + timedelta(days=next_interval)

    await db.flush()
    await db.refresh(card)
    return _to_item(card)


@router.post("/cards/ai-generate")
async def ai_generate_cards(
    body: AnkiAIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source_text = (body.source_text or "").strip()
    prompt = (
        "你是一名学习卡片助手。请根据主题和素材，生成适合记忆复习的问答卡片。"
        f"\n主题: {body.topic.strip()}"
        f"\n素材:\n{source_text if source_text else '（无素材，基于主题生成）'}"
        f"\n数量: {body.count}"
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
            due_at=datetime.now(),
            interval_days=1,
            ease_factor=250,
            repetitions=0,
        )
        db.add(card)
        created.append(card)

    await db.flush()
    for card in created:
        await db.refresh(card)

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
    now = datetime.now()

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
        "filename": f"anki_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
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
            due_at=due_at or datetime.now(),
            interval_days=interval_days,
            ease_factor=ease_factor,
            repetitions=repetitions,
            last_quality=last_quality,
        )
        db.add(card)
        created += 1

    await db.flush()
    return {"created": created, "skipped": skipped}
