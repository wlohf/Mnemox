"""Authenticated sync negotiation and unpaginated single-record conflict previews."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.goal import Goal, Task
from app.models.anki import AnkiCard
from app.models.material import Material, Chapter
from app.routers import notes, goals, anki, wrong_questions

router = APIRouter()


@router.get('/capabilities')
async def capabilities(current_user: User = Depends(get_current_user)):
    return {'protocol_version': 1}


@router.get('/{module}/{record_id}')
async def get_sync_record(
    module: Literal['notes', 'goals', 'goalTasks', 'ankiCards', 'wrongQuestions'],
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = int(current_user.id)
    item = None
    if module == 'notes':
        record = await notes._get_note_for_response(db, record_id, user_id)
        if record is not None:
            item = notes._to_item(record)
    elif module == 'goals':
        record = await db.scalar(select(Goal).where(Goal.id == record_id, Goal.user_id == user_id))
        if record is not None:
            title = await db.scalar(select(Material.title).where(Material.id == record.material_id, Material.user_id == user_id))
            item = goals._goal_item(record, title)
    elif module == 'goalTasks':
        record = await db.scalar(select(Task).join(Goal).where(Task.id == record_id, Goal.user_id == user_id))
        if record is not None:
            title = await db.scalar(select(Chapter.title).join(Material).where(Chapter.id == record.chapter_id, Material.user_id == user_id))
            item = goals._task_item(record, title)
    elif module == 'ankiCards':
        record = await db.scalar(select(AnkiCard).where(AnkiCard.id == record_id, AnkiCard.user_id == user_id))
        if record is not None:
            item = anki._to_item(record)
    else:
        record = await wrong_questions._get_wrong_question_for_response(db, record_id, user_id)
        if record is not None:
            item = wrong_questions._to_item(record)
    if item is None:
        raise HTTPException(status_code=404, detail='记录不存在或无权访问')
    return item
