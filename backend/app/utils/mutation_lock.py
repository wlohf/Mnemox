"""Serialize a user's short domain mutations on SQLite and PostgreSQL alike."""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User


async def lock_user_mutation(db: AsyncSession, user_id: int) -> None:
    # An UPDATE opens SQLite's real write transaction; PostgreSQL locks one user
    # row. Keep this transaction short and never perform external I/O under it.
    await db.execute(update(User).where(User.id == user_id).values(id=User.id)
                     .execution_options(synchronize_session=False))
