"""日历计划路由：支持按天读写、按区间拉取（用于本周计划）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.daily_plan import DailyPlan


router = APIRouter()


class PlanUpsertRequest(BaseModel):
    content: str = Field(default="", description="计划/记录内容（markdown 或纯文本）")


class PlanResponse(BaseModel):
    date: str
    content: str


@router.get("/{date}", response_model=PlanResponse)
async def get_plan(date: str, db: AsyncSession = Depends(get_db)):
    """
    获取某一天的计划。
    date: YYYY-MM-DD
    """

    result = await db.execute(select(DailyPlan).where(DailyPlan.date == date))
    row = result.scalar_one_or_none()
    return PlanResponse(date=date, content=row.content if row else "")


@router.put("/{date}", response_model=PlanResponse)
async def upsert_plan(date: str, body: PlanUpsertRequest, db: AsyncSession = Depends(get_db)):
    """
    新建/更新某一天的计划。
    """

    result = await db.execute(select(DailyPlan).where(DailyPlan.date == date))
    row = result.scalar_one_or_none()
    if row is None:
        row = DailyPlan(date=date, content=body.content or "")
        db.add(row)
    else:
        row.content = body.content or ""

    await db.commit()
    return PlanResponse(date=date, content=row.content)


@router.get("/", response_model=list[PlanResponse])
async def list_plans(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """
    按日期区间拉取计划（闭区间）。

    说明：date 字段为 YYYY-MM-DD 字符串，字符串比较可直接用于区间过滤。
    """

    if start > end:
        raise HTTPException(status_code=400, detail="start 不能大于 end")

    result = await db.execute(
        select(DailyPlan).where(DailyPlan.date >= start, DailyPlan.date <= end).order_by(DailyPlan.date.asc())
    )
    rows = result.scalars().all()
    return [PlanResponse(date=r.date, content=r.content) for r in rows]

