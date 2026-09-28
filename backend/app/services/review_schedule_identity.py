"""Concurrent creation preserves an existing schedule's learned state."""
from sqlalchemy import select
from app.models.question import ReviewSchedule
from app.utils.dialect import conflict_insert


async def ensure_review_schedule(db, *, user_id: int, item_type: str, item_id: int, **defaults):
    result = await db.execute(conflict_insert(db, ReviewSchedule).values(
        user_id=user_id, item_type=item_type, item_id=item_id, **defaults,
    ).on_conflict_do_nothing(index_elements=["user_id", "item_type", "item_id"])
      .returning(ReviewSchedule.id))
    created = result.scalar_one_or_none() is not None
    row = await db.scalar(select(ReviewSchedule).where(
        ReviewSchedule.user_id == user_id, ReviewSchedule.item_type == item_type, ReviewSchedule.item_id == item_id,
    ).execution_options(populate_existing=True))
    return row, created
