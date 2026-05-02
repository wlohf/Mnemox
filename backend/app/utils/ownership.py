"""Reusable ownership guards for user-scoped resources."""
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

ModelT = TypeVar("ModelT")


async def get_owned_row(
    db: AsyncSession,
    model: type[ModelT],
    row_id: Any,
    user_id: int,
    *,
    not_found_detail: str = "资源不存在",
    id_attr: str = "id",
    user_attr: str = "user_id",
) -> ModelT:
    """Return a row only when it belongs to the current user, otherwise 404."""
    id_column: ColumnElement[bool] = getattr(model, id_attr) == row_id
    user_column: ColumnElement[bool] = getattr(model, user_attr) == user_id
    result = await db.execute(select(model).where(id_column, user_column))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row
