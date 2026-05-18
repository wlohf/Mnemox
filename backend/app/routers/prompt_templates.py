"""用户自定义 Prompt 模板路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Dict, Optional

from ..database import get_db
from ..auth import get_current_user
from ..models.user import User
from ..models.prompt_template import PromptTemplate, MODE_KEYS
from ..ai.prompts import (
    REVIEW_PROMPT, EXPLAIN_PROMPT, FEYNMAN_PROMPT, SOCRATIC_PROMPT,
    QUIZ_PROMPT, ERROR_ANALYSIS_PROMPT, SUMMARY_PROMPT, OKR_DECOMPOSE_PROMPT,
)

router = APIRouter()

# 默认 prompt 映射（mode_key -> 默认内容）
DEFAULT_PROMPTS: Dict[str, str] = {
    "coach": """你是用户的专属 AI 学习教练 Mnemox。你了解用户的学习历史、薄弱点、学习习惯和当前计划。

核心原则：学习方法要融入系统流程，而不是让用户手动切换孤立模式。
- 普通提问：先给清晰、简洁的回答；如果问题涉及理解、推理或知识关联，再自然附上 1 个引导式追问。
- 知识关联学习：使用苏格拉底式追问帮助用户说出自己的理解、比较概念关系、发现模糊点；不要为了提问而提问。
- 每日复盘/总结：使用费曼学习法，引导用户用自己的话复述今天所学，找出“讲不顺”的地方，并把它转成明天的最小补缺口。
- 用户状态不好：先共情，再把任务降到一个可完成的最小行动。

你的风格：
- 像朋友一样交流，不说教，不啰嗦
- 适时鼓励，但要具体、真诚
- 能回答时就回答；需要训练理解时才追问
- 结尾优先给下一步行动，而不是要求用户选择模式

变量：{user_message}""",
    "feynman":   FEYNMAN_PROMPT,
    "socratic":  SOCRATIC_PROMPT,
    "review":    REVIEW_PROMPT,
    "quiz":      QUIZ_PROMPT,
    "error":     ERROR_ANALYSIS_PROMPT,
    "summary":   SUMMARY_PROMPT,
    "explain":   EXPLAIN_PROMPT,
    "distracted_care": """用户刚才在学习时状态不好，提前放弃了番茄钟。

请以关心的语气询问用户当前状态，不要评判，不要说教。
可以问：今天发生什么了吗？或者只是有点累？

如果用户分享了原因，给予情绪支持，并根据情况提供 1-2 个小建议（比如换个学习方式、休息一下等）。
记住：目标是让用户感到被理解，而不是被督促。""",
    "okr":       OKR_DECOMPOSE_PROMPT,
}


class PromptUpdateRequest(BaseModel):
    content: str


class PromptItem(BaseModel):
    mode_key: str
    name: str
    content: str
    is_custom: bool
    updated_at: Optional[str] = None


async def get_user_prompt(db: AsyncSession, user_id: int, mode_key: str) -> str:
    """获取用户的 prompt（优先自定义，fallback 到默认）"""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.user_id == user_id,
            PromptTemplate.mode_key == mode_key,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return str(row.content)
    return DEFAULT_PROMPTS.get(mode_key, "")


@router.get("", response_model=list[PromptItem])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PromptItem]:
    """获取所有模式的 prompt（含自定义标记）"""
    user_id = int(current_user.id)  # type: ignore[arg-type]
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.user_id == user_id)
    )
    custom_rows = {str(row.mode_key): str(row.content) for row in result.scalars().all()}
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.user_id == user_id)
    )
    custom_time_rows = {
        str(row.mode_key): (row.updated_at.isoformat() if row.updated_at else None)
        for row in result.scalars().all()
    }

    items: list[PromptItem] = []
    for mode_key, name in MODE_KEYS.items():
        is_custom = mode_key in custom_rows
        content = custom_rows[mode_key] if is_custom else DEFAULT_PROMPTS.get(mode_key, "")
        items.append(PromptItem(
            mode_key=mode_key,
            name=name,
            content=content,
            is_custom=is_custom,
            updated_at=custom_time_rows.get(mode_key),
        ))
    return items


@router.put("/{mode_key}")
async def update_prompt(
    mode_key: str,
    body: PromptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """保存用户自定义 prompt"""
    if mode_key not in MODE_KEYS:
        raise HTTPException(status_code=404, detail=f"未知模式：{mode_key}")
    user_id = int(current_user.id)  # type: ignore[arg-type]
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.user_id == user_id,
            PromptTemplate.mode_key == mode_key,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = PromptTemplate(user_id=user_id, mode_key=mode_key, content=body.content)
        db.add(row)
    else:
        row.content = body.content
    await db.commit()
    return {"ok": True, "mode_key": mode_key}


@router.delete("/{mode_key}")
async def reset_prompt(
    mode_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """恢复默认 prompt（删除用户自定义）"""
    if mode_key not in MODE_KEYS:
        raise HTTPException(status_code=404, detail=f"未知模式：{mode_key}")
    user_id = int(current_user.id)  # type: ignore[arg-type]
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.user_id == user_id,
            PromptTemplate.mode_key == mode_key,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"ok": True, "mode_key": mode_key, "content": DEFAULT_PROMPTS.get(mode_key, "")}
