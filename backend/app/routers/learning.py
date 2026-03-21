"""学习驾驶舱 / 掌握度地图 / 输出评估"""
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule, Question, WrongQuestion, QuizRecord
from app.models.pomodoro import Pomodoro
from app.models.material import Chapter, Material
from app.models.progress import MaterialProfile, OutputEvaluation
from app.ai.factory import AIProviderFactory
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


class OutputEvaluateRequest(BaseModel):
    task_id: int
    output_text: str
    rubric: Optional[str] = None
    mark_task_completed: bool = False


class MaterialClassificationRequest(BaseModel):
    is_textbook: bool


class GenerateTasksRequest(BaseModel):
    material_id: int
    question_types: Optional[List[str]] = None
    days: int = 7


class AdaptiveReplanRequest(BaseModel):
    days: int = 7
    focus_mode: str = "balanced"  # balanced | weak_first | output_first


def _heuristic_profile(material: Material) -> Dict[str, Any]:
    title = (material.title or "").lower()
    content = (material.content or "")
    hit_words = ["教材", "课本", "chapter", "章节", "习题", "例题", "高等数学", "微积分"]
    score = 0.0
    for w in hit_words:
        if w in title or w in content[:2000].lower():
            score += 0.1
    score = max(0.0, min(0.95, score))
    is_textbook = score >= 0.35

    return {
        "is_textbook": is_textbook,
        "confidence": round(score, 2),
        "chapters": [],
    }


def _safe_parse_json_list(raw: str) -> List[dict]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("chapters"), list):
            return obj.get("chapters")
        if isinstance(obj, list):
            return obj
    except Exception:
        return []
    return []


async def _upsert_material_profile(
    material_id: int,
    is_textbook: bool,
    confidence: float,
    structure_obj: Dict[str, Any],
    source: str,
    db: AsyncSession,
) -> MaterialProfile:
    result = await db.execute(
        select(MaterialProfile).where(MaterialProfile.material_id == material_id)
    )
    row = result.scalar_one_or_none()
    payload = json.dumps(structure_obj, ensure_ascii=False)
    if not row:
        row = MaterialProfile(
            material_id=material_id,
            is_textbook=is_textbook,
            confidence=max(0.0, min(1.0, float(confidence))),
            source=source,
            structure_json=payload,
        )
        db.add(row)
    else:
        row.is_textbook = is_textbook
        row.confidence = max(0.0, min(1.0, float(confidence)))
        row.source = source
        row.structure_json = payload
    await db.flush()
    await db.refresh(row)
    return row


async def _sync_chapters_from_structure(material_id: int, chapters: List[dict], db: AsyncSession) -> int:
    created = 0
    if not chapters:
        return created

    existing_result = await db.execute(
        select(Chapter).where(Chapter.material_id == material_id)
    )
    existing = existing_result.scalars().all()
    existing_titles = {((c.title or "").strip()): c for c in existing}

    for idx, ch in enumerate(chapters):
        title = str(ch.get("title", "")).strip()
        if not title:
            continue
        key_points = ch.get("key_points", [])
        q_types = ch.get("question_types", [])
        content = ""
        if isinstance(key_points, list) and key_points:
            content += "知识点:\n" + "\n".join([f"- {str(x)}" for x in key_points[:12]])
        if isinstance(q_types, list) and q_types:
            content += "\n\n题型:\n" + "\n".join([f"- {str(x)}" for x in q_types[:12]])

        if title in existing_titles:
            item = existing_titles[title]
            if content:
                item.content = content
            if item.order_index is None:
                item.order_index = idx
        else:
            db.add(
                Chapter(
                    material_id=material_id,
                    title=title,
                    content=content or None,
                    order_index=idx,
                    mastery_level=0.0,
                )
            )
            created += 1
    await db.flush()
    return created


async def _auto_create_goal_and_tasks(material_id: int, db: AsyncSession, user_id: int = None) -> tuple:
    """Auto-create one Goal per material + one Task per chapter (type='learn'), skipping duplicates.
    Returns (goal_id, created_task_count).
    """
    mat_result = await db.execute(select(Material).where(Material.id == material_id))
    material = mat_result.scalar_one_or_none()
    if not material:
        return (None, 0)

    # Check for existing active goal for this material
    goal_query = select(Goal).where(Goal.material_id == material_id, Goal.status == "active")
    if user_id:
        goal_query = goal_query.where(Goal.user_id == user_id)
    goal_result = await db.execute(goal_query)
    goal = goal_result.scalar_one_or_none()
    if not goal:
        goal = Goal(
            material_id=material_id,
            title=f"学习目标：{material.title}",
            description="由学习流程自动生成",
            target_level="80%",
            status="active",
        )
        if user_id:
            goal.user_id = user_id
        db.add(goal)
        await db.flush()
        await db.refresh(goal)

    # Get chapters for this material
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.material_id == material_id).order_by(Chapter.order_index)
    )
    chapters = chapter_result.scalars().all()

    # Get existing task titles for this goal to skip duplicates
    task_result = await db.execute(select(Task).where(Task.goal_id == goal.id))
    existing_tasks = task_result.scalars().all()
    existing_chapter_ids = {t.chapter_id for t in existing_tasks if t.chapter_id is not None}

    created = 0
    today = date.today()
    for idx, ch in enumerate(chapters):
        if ch.id in existing_chapter_ids:
            continue
        task = Task(
            goal_id=goal.id,
            chapter_id=ch.id,
            title=f"学习：{ch.title}",
            description=f"学习《{material.title}》中的「{ch.title}」章节",
            task_type="learn",
            status="pending",
            planned_date=today.fromordinal(today.toordinal() + idx),
        )
        db.add(task)
        created += 1

    if created:
        await db.flush()

    return (goal.id, created)


def _safe_parse_json(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def _fallback_eval(output_text: str) -> dict:
    length = len((output_text or "").strip())
    score = 35
    if length > 120:
        score += 20
    if length > 300:
        score += 20
    if re.search(r"\n\s*[-*]\s+", output_text or ""):
        score += 10
    if re.search(r"(总结|因此|所以|结论)", output_text or ""):
        score += 10
    score = max(0, min(100, score))
    verdict = "通过" if score >= 80 else ("接近通过" if score >= 65 else "需改进")
    return {
        "score": score,
        "strengths": ["内容基本完整" if length > 120 else "已经开始输出"],
        "gaps": ["结构还可更清晰", "建议补充关键术语和例子"] if score < 80 else ["可补充更多案例增强说服力"],
        "next_actions": ["按小标题重写一版", "补充1-2个具体例子", "对照资料修正术语"],
        "verdict": verdict,
    }


@router.get("/dashboard")
async def get_learning_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    now = datetime.now()

    task_result = await db.execute(
        select(Task).join(Goal, Task.goal_id == Goal.id).where(Goal.user_id == current_user.id)
    )
    tasks = task_result.scalars().all()

    today_tasks = [t for t in tasks if t.planned_date == today]
    pending_today = [t for t in today_tasks if t.status in ("pending", "in_progress")]
    completed_today = [
        t for t in tasks
        if t.completed_at is not None and t.completed_at.date() == today
    ]

    review_result = await db.execute(
        select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id)
    )
    reviews = review_result.scalars().all()
    due_reviews = [r for r in reviews if r.scheduled_date and r.scheduled_date <= now and r.status == "pending"]

    # 只查询今天的番茄钟记录，避免加载全部历史
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    pomodoro_result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.ended_at >= today_start,
            Pomodoro.ended_at <= today_end,
            Pomodoro.completed == True
        )
    )
    today_pomodoros = pomodoro_result.scalars().all()
    today_minutes = sum(int(p.duration or 0) for p in today_pomodoros)

    # 推荐动作（简单策略）
    actions = []
    for r in due_reviews[:3]:
        actions.append({"type": "review", "title": "完成到期复习任务", "item_id": r.id})
    for t in pending_today[:3]:
        actions.append({"type": "task", "title": t.title, "item_id": t.id})

    return {
        "today": str(today),
        "today_task_count": len(today_tasks),
        "today_pending_count": len(pending_today),
        "today_completed_count": len(completed_today),
        "due_review_count": len(due_reviews),
        "today_pomodoro_count": len(today_pomodoros),
        "today_study_minutes": today_minutes,
        "recommended_actions": actions,
        "today_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "task_type": t.task_type,
                "status": t.status,
            }
            for t in today_tasks
        ],
    }


class BatchStartLearningRequest(BaseModel):
    material_ids: List[int]


@router.post("/materials/batch-start-learning")
async def batch_start_learning_pipeline(
    body: BatchStartLearningRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch learning pipeline: analyze multiple materials and auto-create goals/tasks for each."""
    if not body.material_ids:
        raise HTTPException(status_code=400, detail="material_ids 不能为空")
    if len(body.material_ids) > 20:
        raise HTTPException(status_code=400, detail="单次批量学习最多 20 份资料")

    results = []
    total_tasks = 0

    for mid in body.material_ids:
        # Verify ownership
        mat_result = await db.execute(
            select(Material).where(Material.id == mid, Material.user_id == current_user.id)
        )
        material = mat_result.scalar_one_or_none()
        if not material:
            results.append({
                "material_id": mid,
                "material_title": None,
                "error": "资料不存在或无权访问",
                "goal_id": None,
                "auto_created_tasks": 0,
                "tasks": [],
            })
            continue

        try:
            analysis = await analyze_material_for_progress(mid, db, current_user)

            tasks_out = []
            if analysis.get("goal_id"):
                task_result = await db.execute(
                    select(Task).where(Task.goal_id == analysis["goal_id"]).order_by(Task.planned_date)
                )
                tasks = task_result.scalars().all()
                tasks_out = [
                    {
                        "id": t.id,
                        "title": t.title,
                        "task_type": t.task_type,
                        "status": t.status,
                        "planned_date": t.planned_date.isoformat() if t.planned_date else None,
                    }
                    for t in tasks
                ]

            auto_created = int(analysis.get("auto_created_tasks", 0))
            total_tasks += auto_created
            results.append({
                "material_id": mid,
                "material_title": material.title,
                "goal_id": analysis.get("goal_id"),
                "auto_created_tasks": auto_created,
                "tasks": tasks_out,
            })
        except Exception as e:
            results.append({
                "material_id": mid,
                "material_title": material.title,
                "error": str(e),
                "goal_id": None,
                "auto_created_tasks": 0,
                "tasks": [],
            })

    await db.commit()

    return {
        "results": results,
        "total_tasks": total_tasks,
    }


@router.post("/materials/{material_id}/analyze")
async def analyze_material_for_progress(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat_result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = mat_result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    fallback = _heuristic_profile(material)
    is_textbook = bool(fallback["is_textbook"])
    confidence = float(fallback["confidence"])
    chapters: List[dict] = []

    prompt = (
        "你是学习资料结构化助手。请判断资料是否教材型，并提取章节学习地图。"
        "只输出 JSON："
        "{\"is_textbook\":true/false,\"confidence\":0~1,\"chapters\":[{\"title\":\"...\",\"key_points\":[...],\"question_types\":[...]}]}\n"
        "要求：chapters 最多 20 条，key_points 和 question_types 各最多 8 条。\n"
        f"标题：{material.title}\n"
        f"内容片段：{(material.content or '')[:6000]}"
    )

    try:
        provider = await AIProviderFactory.create_provider(db=db, scenario="material_analyze")
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是结构化分析器，只输出 JSON。",
            temperature=0.1,
        )
        obj = _safe_parse_json(raw) or {}
        is_textbook = bool(obj.get("is_textbook", is_textbook))
        confidence = float(obj.get("confidence", confidence) or confidence)
        chapters = _safe_parse_json_list(raw)
    except Exception:
        chapters = []

    structure_obj = {
        "material_id": material_id,
        "is_textbook": is_textbook,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "chapters": chapters,
    }

    profile = await _upsert_material_profile(
        material_id=material_id,
        is_textbook=is_textbook,
        confidence=confidence,
        structure_obj=structure_obj,
        source="ai",
        db=db,
    )

    created_chapters = 0
    if is_textbook and chapters:
        created_chapters = await _sync_chapters_from_structure(material_id, chapters, db)

    # Auto-create goal and tasks for the material
    goal_id, auto_tasks = await _auto_create_goal_and_tasks(material_id, db, user_id=current_user.id)

    return {
        "material_id": material_id,
        "is_textbook": bool(profile.is_textbook),
        "confidence": float(profile.confidence or 0.0),
        "created_chapters": created_chapters,
        "chapter_count": len(chapters),
        "goal_id": goal_id,
        "auto_created_tasks": auto_tasks,
    }


@router.post("/materials/{material_id}/start-learning")
async def start_learning_pipeline(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Composite pipeline: analyze material + auto-create goals/tasks.
    Returns summary with goal_id and task list.
    """
    # Run analysis (which also auto-creates goals/tasks)
    analysis = await analyze_material_for_progress(material_id, db, current_user)

    # Fetch created tasks for this material's goal
    tasks_out = []
    if analysis.get("goal_id"):
        task_result = await db.execute(
            select(Task).where(Task.goal_id == analysis["goal_id"]).order_by(Task.planned_date)
        )
        tasks = task_result.scalars().all()
        tasks_out = [
            {
                "id": t.id,
                "title": t.title,
                "task_type": t.task_type,
                "status": t.status,
                "planned_date": t.planned_date.isoformat() if t.planned_date else None,
            }
            for t in tasks
        ]

    return {
        **analysis,
        "tasks": tasks_out,
    }


@router.put("/materials/{material_id}/classification")
async def set_material_classification(
    material_id: int,
    body: MaterialClassificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat_result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = mat_result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    existing_result = await db.execute(
        select(MaterialProfile).where(MaterialProfile.material_id == material_id)
    )
    existing = existing_result.scalar_one_or_none()
    structure_obj = {}
    if existing and existing.structure_json:
        try:
            structure_obj = json.loads(existing.structure_json)
        except Exception:
            structure_obj = {}

    profile = await _upsert_material_profile(
        material_id=material_id,
        is_textbook=bool(body.is_textbook),
        confidence=1.0,
        structure_obj=structure_obj,
        source="manual",
        db=db,
    )

    return {
        "material_id": material_id,
        "is_textbook": bool(profile.is_textbook),
        "confidence": float(profile.confidence or 0.0),
        "source": profile.source,
    }


@router.get("/mastery-map")
async def get_mastery_map(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat_result = await db.execute(
        select(Material).where(Material.user_id == current_user.id)
    )
    materials = mat_result.scalars().all()

    chapter_result = await db.execute(
        select(Chapter).join(Material, Chapter.material_id == Material.id).where(Material.user_id == current_user.id)
    )
    chapters = chapter_result.scalars().all()

    by_material = {}
    for m in materials:
        by_material[m.id] = {
            "material_id": m.id,
            "material_title": m.title,
            "average_mastery": 0.0,
            "chapter_count": 0,
            "chapters": [],
        }

    for ch in chapters:
        item = by_material.get(ch.material_id)
        if not item:
            continue
        level = float(ch.mastery_level or 0.0)
        band = "weak" if level < 50 else ("medium" if level < 80 else "strong")
        item["chapters"].append(
            {
                "chapter_id": ch.id,
                "chapter_title": ch.title,
                "mastery_level": level,
                "band": band,
            }
        )

    result = []
    weak_points = []
    for _, item in by_material.items():
        if not item["chapters"]:
            continue
        levels = [c["mastery_level"] for c in item["chapters"]]
        item["average_mastery"] = round(sum(levels) / len(levels), 1)
        item["chapter_count"] = len(item["chapters"])
        result.append(item)

        for c in item["chapters"]:
            if c["mastery_level"] < 50:
                weak_points.append(
                    {
                        "material_title": item["material_title"],
                        "chapter_title": c["chapter_title"],
                        "mastery_level": c["mastery_level"],
                    }
                )

    weak_points.sort(key=lambda x: x["mastery_level"])

    return {
        "materials": result,
        "weak_points": weak_points[:20],
    }


@router.get("/progress-engine")
async def get_progress_engine(
    include_non_textbook: bool = Query(False),
    w_chapter: float = Query(0.4, ge=0.0, le=1.0),
    w_quiz: float = Query(0.25, ge=0.0, le=1.0),
    w_wrong: float = Query(0.2, ge=0.0, le=1.0),
    w_output: float = Query(0.15, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat_result = await db.execute(
        select(Material).where(Material.user_id == current_user.id)
    )
    materials = mat_result.scalars().all()

    profile_result = await db.execute(
        select(MaterialProfile).where(MaterialProfile.material_id.in_([m.id for m in materials]))
    )
    profiles = profile_result.scalars().all()
    profile_map = {p.material_id: p for p in profiles}

    chapter_result = await db.execute(
        select(Chapter).join(Material, Chapter.material_id == Material.id).where(Material.user_id == current_user.id)
    )
    chapters = chapter_result.scalars().all()
    chapter_by_material: Dict[int, List[Chapter]] = {}
    for ch in chapters:
        chapter_by_material.setdefault(ch.material_id, []).append(ch)

    question_result = await db.execute(
        select(Question).where(Question.user_id == current_user.id)
    )
    questions = question_result.scalars().all()
    goal_result = await db.execute(
        select(Goal).where(Goal.user_id == current_user.id)
    )
    goals = goal_result.scalars().all()
    goal_ids = [g.id for g in goals]
    task_result = await db.execute(
        select(Task).where(Task.goal_id.in_(goal_ids)) if goal_ids else select(Task).where(False)
    )
    tasks = task_result.scalars().all()
    # 只查询当前用户相关的答题记录（通过 question_id 关联）
    question_ids = {q.id for q in questions}
    quiz_result = await db.execute(
        select(QuizRecord).where(QuizRecord.question_id.in_(question_ids)) if question_ids else select(QuizRecord).where(False)
    )
    wrong_result = await db.execute(
        select(WrongQuestion).where(WrongQuestion.user_id == current_user.id)
    )
    wrongs = wrong_result.scalars().all()
    # 只查询当前用户相关的输出评估（通过 task_id 关联）
    task_ids = {t.id for t in tasks}
    eval_result = await db.execute(
        select(OutputEvaluation).where(OutputEvaluation.task_id.in_(task_ids)) if task_ids else select(OutputEvaluation).where(False)
    )
    evaluations = eval_result.scalars().all()

    q_map = {q.id: q for q in questions}
    goal_material_map = {
        g.id: int(g.material_id)
        for g in goals
        if g.material_id is not None
    }
    tasks_by_material: Dict[int, List[Task]] = {}
    for t in tasks:
        mid = goal_material_map.get(int(t.goal_id or -1))
        if mid is None:
            continue
        tasks_by_material.setdefault(mid, []).append(t)

    materials_out = []
    weighted_sum = 0.0
    total_weight = 0.0

    for m in materials:
        profile = profile_map.get(m.id)
        if profile:
            is_textbook = bool(profile.is_textbook)
            confidence_value = float(profile.confidence or 0.0)
        else:
            heuristic = _heuristic_profile(m)
            is_textbook = bool(heuristic["is_textbook"])
            confidence_value = float(heuristic["confidence"])
        if not include_non_textbook and not is_textbook:
            continue

        m_chapters = chapter_by_material.get(m.id, [])
        chapter_levels = [float(c.mastery_level or 0.0) for c in m_chapters]
        chapter_progress = round(sum(chapter_levels) / len(chapter_levels), 1) if chapter_levels else 0.0
        chapter_completion = round(
            (sum(1 for lv in chapter_levels if lv >= 80) / len(chapter_levels) * 100), 1
        ) if chapter_levels else 0.0

        m_chapter_ids = {c.id for c in m_chapters}
        m_questions = [q for q in questions if q.chapter_id in m_chapter_ids]
        m_question_ids = {q.id for q in m_questions}
        m_quiz = [r for r in quiz_records if r.question_id in m_question_ids]
        correct_rate = 0.0
        if m_quiz:
            correct_rate = round(sum(1 for r in m_quiz if r.is_correct) / len(m_quiz) * 100, 1)

        # 题型掌握覆盖：按章节题型计算掌握得分后取平均
        question_type_coverage = 0.0
        if m_questions:
            quiz_by_qid: Dict[int, List[QuizRecord]] = {}
            for r in m_quiz:
                quiz_by_qid.setdefault(int(r.question_id), []).append(r)

            chapter_type_scores: List[float] = []
            for ch in m_chapters:
                ch_questions = [q for q in m_questions if int(q.chapter_id) == int(ch.id)]
                if not ch_questions:
                    continue
                types = sorted({str(q.question_type or "unknown") for q in ch_questions})
                type_scores: List[float] = []
                for qt in types:
                    q_ids = [int(q.id) for q in ch_questions if str(q.question_type or "unknown") == qt]
                    recs = [rec for qid in q_ids for rec in quiz_by_qid.get(qid, [])]
                    attempts = len(recs)
                    accuracy = (sum(1 for rec in recs if rec.is_correct) / attempts) if attempts > 0 else 0.0

                    type_wrongs = [
                        w for w in wrongs
                        if q_map.get(w.question_id)
                        and int(q_map[w.question_id].chapter_id) == int(ch.id)
                        and str(q_map[w.question_id].question_type or "unknown") == qt
                    ]
                    if type_wrongs:
                        mastered_ratio = sum(1 for w in type_wrongs if w.mastery_status == "mastered") / len(type_wrongs)
                    else:
                        mastered_ratio = 1.0

                    attempt_factor = min(1.0, attempts / 3.0)
                    type_score = (
                        accuracy * 100 * 0.6
                        + attempt_factor * 100 * 0.2
                        + mastered_ratio * 100 * 0.2
                    )
                    type_scores.append(type_score)

                if type_scores:
                    chapter_type_scores.append(sum(type_scores) / len(type_scores))

            if chapter_type_scores:
                question_type_coverage = round(sum(chapter_type_scores) / len(chapter_type_scores), 1)

        m_wrongs = [w for w in wrongs if q_map.get(w.question_id) and q_map[w.question_id].chapter_id in m_chapter_ids]
        wrong_fix_rate = 100.0
        if m_wrongs:
            wrong_fix_rate = round(sum(1 for w in m_wrongs if w.mastery_status == "mastered") / len(m_wrongs) * 100, 1)

        m_evals = [e for e in evaluations if int(e.material_id or -1) == m.id]
        output_score = round(sum(int(e.score or 0) for e in m_evals) / len(m_evals), 1) if m_evals else 0.0

        m_tasks = tasks_by_material.get(m.id, [])
        task_completion_rate = 0.0
        task_type_coverage = 0.0
        task_execution_quality = 0.0
        if m_tasks:
            completed_tasks = [t for t in m_tasks if t.status == "completed"]
            task_completion_rate = round(len(completed_tasks) / len(m_tasks) * 100, 1)

            active_task_types = {str(t.task_type or "learn") for t in m_tasks}
            completed_task_types = {str(t.task_type or "learn") for t in completed_tasks}
            if active_task_types:
                task_type_coverage = round(len(completed_task_types) / len(active_task_types) * 100, 1)

            task_execution_quality = round(task_completion_rate * 0.7 + task_type_coverage * 0.3, 1)

        # 综合评分：任务计划 + 题型掌握驱动（支持前端可配置权重）
        chapter_metric = round(chapter_progress * 0.7 + chapter_completion * 0.3, 1)
        quiz_metric = round(correct_rate * 0.6 + question_type_coverage * 0.4, 1)
        wrong_metric = round(wrong_fix_rate * 0.7 + task_execution_quality * 0.3, 1)
        metrics = [
            (chapter_metric, w_chapter),
            (quiz_metric, w_quiz if (m_quiz or m_questions) else 0.0),
            (wrong_metric, w_wrong if (m_wrongs or m_tasks) else 0.0),
            (output_score, w_output if m_evals else 0.0),
        ]
        active_weight = sum(w for _, w in metrics if w > 0)
        if active_weight <= 0:
            overall = chapter_progress
        else:
            overall = round(sum(v * (w / active_weight) for v, w in metrics if w > 0), 1)

        structure = {}
        if profile and profile.structure_json:
            try:
                structure = json.loads(profile.structure_json)
            except Exception:
                structure = {}

        chapter_items = [
            {
                "chapter_id": c.id,
                "chapter_title": c.title,
                "mastery_level": float(c.mastery_level or 0.0),
            }
            for c in sorted(m_chapters, key=lambda x: int(x.order_index or 0))
        ]

        item_weight = max(1, len(m_chapters))
        weighted_sum += overall * item_weight
        total_weight += item_weight

        materials_out.append(
            {
                "material_id": m.id,
                "title": m.title,
                "is_textbook": is_textbook,
                "profile_source": profile.source if profile else None,
                "textbook_confidence": confidence_value,
                "chapter_count": len(m_chapters),
                "chapter_progress": chapter_progress,
                "chapter_completion": chapter_completion,
                "practice_correct_rate": correct_rate,
                "question_type_coverage": question_type_coverage,
                "wrong_fix_rate": wrong_fix_rate,
                "task_completion_rate": task_completion_rate,
                "task_type_coverage": task_type_coverage,
                "task_execution_quality": task_execution_quality,
                "output_quality": output_score,
                "overall_progress": overall,
                "chapter_items": chapter_items,
                "structure": structure,
            }
        )

    materials_out.sort(key=lambda x: x["overall_progress"])
    total_progress = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0.0

    return {
        "total_progress": total_progress,
        "material_count": len(materials_out),
        "weights": {
            "chapter": w_chapter,
            "quiz": w_quiz,
            "wrong": w_wrong,
            "output": w_output,
        },
        "materials": materials_out,
    }


@router.get("/progress-engine/materials/{material_id}/plan")
async def get_material_learning_plan(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat_result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = mat_result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.material_id == material_id)
    )
    chapters = chapter_result.scalars().all()

    question_result = await db.execute(
        select(Question).where(Question.user_id == current_user.id)
    )
    questions = question_result.scalars().all()
    wrong_result = await db.execute(
        select(WrongQuestion).where(WrongQuestion.user_id == current_user.id)
    )
    wrongs = wrong_result.scalars().all()
    q_map = {q.id: q for q in questions}

    # 章节学习路径：从低掌握到高掌握
    chapter_path = []
    for ch in chapters:
        ch_questions = [q for q in questions if q.chapter_id == ch.id]
        q_types = sorted({str(q.question_type or "unknown") for q in ch_questions})
        ch_wrongs = [w for w in wrongs if q_map.get(w.question_id) and q_map[w.question_id].chapter_id == ch.id]
        chapter_path.append(
            {
                "chapter_id": ch.id,
                "chapter_title": ch.title,
                "mastery_level": float(ch.mastery_level or 0.0),
                "question_count": len(ch_questions),
                "question_types": q_types,
                "wrong_count": len(ch_wrongs),
                "priority": "high" if float(ch.mastery_level or 0.0) < 50 else ("medium" if float(ch.mastery_level or 0.0) < 80 else "low"),
            }
        )
    chapter_path.sort(key=lambda x: (x["mastery_level"], -x["wrong_count"]))

    # 题型训练包：按错题与题型聚合
    type_stats: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        if q.chapter_id not in {c.id for c in chapters}:
            continue
        t = str(q.question_type or "unknown")
        stat = type_stats.setdefault(t, {"question_type": t, "total": 0, "wrong": 0, "chapters": set()})
        stat["total"] += 1
        stat["chapters"].add(q.chapter_id)

    wrong_q_ids = {w.question_id for w in wrongs}
    for q in questions:
        if q.id in wrong_q_ids and q.chapter_id in {c.id for c in chapters}:
            t = str(q.question_type or "unknown")
            if t in type_stats:
                type_stats[t]["wrong"] += 1

    training_pack = []
    for _, stat in type_stats.items():
        total = int(stat["total"] or 0)
        wrong = int(stat["wrong"] or 0)
        difficulty = "high" if wrong >= max(2, int(total * 0.3)) else ("medium" if wrong > 0 else "low")
        training_pack.append(
            {
                "question_type": stat["question_type"],
                "total": total,
                "wrong": wrong,
                "difficulty": difficulty,
                "suggest_count": 10 if difficulty == "high" else (6 if difficulty == "medium" else 3),
            }
        )

    training_pack.sort(key=lambda x: (x["wrong"], x["total"]), reverse=True)

    return {
        "material_id": material_id,
        "material_title": material.title,
        "chapter_path": chapter_path,
        "training_pack": training_pack,
    }


async def _ensure_goal_for_material(material_id: int, db: AsyncSession, user_id: int = None) -> Goal:
    goal_query = select(Goal).where(Goal.material_id == material_id, Goal.status == "active")
    if user_id:
        goal_query = goal_query.where(Goal.user_id == user_id)
    goal_result = await db.execute(goal_query)
    goal = goal_result.scalar_one_or_none()
    if goal:
        return goal

    mat_result = await db.execute(select(Material).where(Material.id == material_id))
    material = mat_result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    goal = Goal(
        material_id=material_id,
        title=f"学习目标：{material.title}",
        description="由进度引擎自动生成",
        target_level="80%",
        status="active",
    )
    if user_id:
        goal.user_id = user_id
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    return goal


@router.post("/progress-engine/materials/{material_id}/generate-training-tasks")
async def generate_training_tasks(
    material_id: int,
    body: Optional[GenerateTasksRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan = await get_material_learning_plan(material_id, db, current_user)
    goal = await _ensure_goal_for_material(material_id, db, user_id=current_user.id)

    selected_types = set((body.question_types if body and body.question_types else []))
    created = 0
    for pack in plan["training_pack"]:
        q_type = str(pack.get("question_type", "unknown"))
        if selected_types and q_type not in selected_types:
            continue
        title = f"题型训练：{q_type}（{pack.get('suggest_count', 5)}题）"
        task = Task(
            goal_id=goal.id,
            title=title,
            description=f"建议训练数量：{pack.get('suggest_count', 5)}；当前错题：{pack.get('wrong', 0)}",
            task_type="practice",
            status="pending",
            planned_date=date.today(),
        )
        db.add(task)
        created += 1

    await db.flush()
    return {
        "material_id": material_id,
        "goal_id": goal.id,
        "created_task_count": created,
    }


@router.post("/progress-engine/materials/{material_id}/generate-7day-plan")
async def generate_7day_plan(
    material_id: int,
    days: int = Query(7, ge=3, le=14),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan = await get_material_learning_plan(material_id, db, current_user)
    goal = await _ensure_goal_for_material(material_id, db, user_id=current_user.id)

    chapter_path = plan["chapter_path"]
    if not chapter_path:
        return {
            "material_id": material_id,
            "goal_id": goal.id,
            "created_task_count": 0,
            "detail": "无章节数据可排期",
        }

    created = 0
    today = date.today()
    for i in range(days):
        target = chapter_path[i % len(chapter_path)]
        title = f"第{i+1}天：学习 {target['chapter_title']}"
        desc = f"掌握度 {int(target['mastery_level'])}%；建议先处理该章节高频错题"
        db.add(
            Task(
                goal_id=goal.id,
                chapter_id=target["chapter_id"],
                title=title,
                description=desc,
                task_type="learn",
                planned_date=today.fromordinal(today.toordinal() + i),
                status="pending",
            )
        )
        created += 1

    await db.flush()
    return {
        "material_id": material_id,
        "goal_id": goal.id,
        "created_task_count": created,
        "days": days,
    }


@router.post("/progress-engine/materials/{material_id}/adaptive-replan")
async def adaptive_replan(
    material_id: int,
    body: AdaptiveReplanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据近期学习表现动态重排任务优先级与日期。"""
    days = max(3, min(14, int(body.days or 7)))
    focus_mode = body.focus_mode if body.focus_mode in ("balanced", "weak_first", "output_first") else "balanced"

    goal = await _ensure_goal_for_material(material_id, db, user_id=current_user.id)

    # 当前资料的章节与薄弱度
    chapter_result = await db.execute(select(Chapter).where(Chapter.material_id == material_id))
    chapters = chapter_result.scalars().all()
    chapter_ids = {c.id for c in chapters}
    chapter_level = {c.id: float(c.mastery_level or 0.0) for c in chapters}

    # 统计错题压力（按章节）
    q_result = await db.execute(
        select(Question).where(Question.user_id == current_user.id)
    )
    questions = q_result.scalars().all()
    q_map = {q.id: q for q in questions}
    wrong_result = await db.execute(
        select(WrongQuestion).where(WrongQuestion.user_id == current_user.id)
    )
    wrongs = wrong_result.scalars().all()
    wrong_pressure: Dict[int, int] = {cid: 0 for cid in chapter_ids}
    for w in wrongs:
        q = q_map.get(w.question_id)
        if not q or q.chapter_id not in chapter_ids:
            continue
        wrong_pressure[q.chapter_id] = wrong_pressure.get(q.chapter_id, 0) + int(w.wrong_count or 1)

    # 拉取目标下待执行任务
    task_result = await db.execute(select(Task).where(Task.goal_id == goal.id))
    tasks = task_result.scalars().all()
    candidates = [t for t in tasks if t.status in ("pending", "in_progress")]

    if not candidates:
        return {
            "material_id": material_id,
            "goal_id": goal.id,
            "rescheduled": 0,
            "detail": "无可重排任务",
        }

    def task_priority(t: Task) -> float:
        base = 50.0
        if t.task_type == "review":
            base += 8
        if t.task_type == "practice":
            base += 10
        if t.task_type == "summarize":
            base += 6

        cid = int(t.chapter_id) if t.chapter_id is not None else None
        if cid and cid in chapter_level:
            weak_score = 100.0 - chapter_level[cid]
            base += weak_score * 0.35
            base += float(wrong_pressure.get(cid, 0)) * 1.2

        if focus_mode == "weak_first":
            base += 12 if cid and chapter_level.get(cid, 100.0) < 60 else 0
        elif focus_mode == "output_first":
            base += 12 if t.task_type == "summarize" else 0

        if t.status == "in_progress":
            base += 5
        return base

    candidates.sort(key=task_priority, reverse=True)

    # 只重排前 N 天可承载任务（每天最多2个）
    capacity = days * 2
    chosen = candidates[:capacity]
    today = date.today()

    for idx, t in enumerate(chosen):
        day_offset = idx // 2
        t.planned_date = today.fromordinal(today.toordinal() + day_offset)

    await db.flush()

    preview = [
        {
            "task_id": t.id,
            "title": t.title,
            "task_type": t.task_type,
            "planned_date": t.planned_date.isoformat() if t.planned_date else None,
            "priority": round(task_priority(t), 1),
        }
        for t in chosen[:10]
    ]

    return {
        "material_id": material_id,
        "goal_id": goal.id,
        "focus_mode": focus_mode,
        "rescheduled": len(chosen),
        "days": days,
        "preview": preview,
    }


@router.post("/evaluate-output")
async def evaluate_output(
    body: OutputEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.output_text.strip():
        raise HTTPException(status_code=400, detail="output_text 不能为空")

    # Verify task belongs to a goal owned by the current user
    task_result = await db.execute(select(Task).where(Task.id == body.task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.goal_id:
        goal_result = await db.execute(
            select(Goal).where(Goal.id == task.goal_id, Goal.user_id == current_user.id)
        )
        if not goal_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="任务不存在")

    prompt = (
        "请你作为学习教练评估用户的学习产出。"
        "只返回 JSON："
        "{\"score\":0-100,\"strengths\":[...],\"gaps\":[...],\"next_actions\":[...],\"verdict\":\"通过|接近通过|需改进\"}\n"
        "要求：strengths/gaps/next_actions 各给 2-4 条，简短可执行。\n"
        f"任务标题：{task.title}\n"
        f"任务类型：{task.task_type or 'learn'}\n"
        f"评估标准：{body.rubric or '准确性、结构清晰、覆盖关键点、可复述性'}\n"
        f"用户产出：{body.output_text[:5000]}"
    )

    result_obj = None
    try:
        provider = await AIProviderFactory.create_provider(db=db, scenario="output_evaluate")
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是严格的学习评估器，只返回 JSON。",
            temperature=0.2,
        )
        result_obj = _safe_parse_json(raw)
    except Exception:
        result_obj = None

    if not result_obj:
        result_obj = _fallback_eval(body.output_text)

    score = int(result_obj.get("score", 0))
    score = max(0, min(100, score))
    strengths = result_obj.get("strengths", [])
    gaps = result_obj.get("gaps", [])
    next_actions = result_obj.get("next_actions", [])
    verdict = str(result_obj.get("verdict", "需改进"))

    if body.mark_task_completed and score >= 80:
        task.status = "completed"
        task.completed_at = datetime.now()
    # 关联 material_id 以支持进度引擎汇总
    material_id = None
    if task.goal_id:
        from app.models.goal import Goal

        goal_result = await db.execute(select(Goal).where(Goal.id == task.goal_id))
        goal = goal_result.scalar_one_or_none()
        material_id = int(goal.material_id) if goal and goal.material_id is not None else None

    db.add(
        OutputEvaluation(
            task_id=task.id,
            material_id=material_id,
            score=score,
            verdict=verdict,
            strengths=json.dumps(strengths, ensure_ascii=False),
            gaps=json.dumps(gaps, ensure_ascii=False),
            next_actions=json.dumps(next_actions, ensure_ascii=False),
        )
    )
    await db.flush()

    return {
        "task_id": task.id,
        "task_title": task.title,
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "next_actions": next_actions,
        "verdict": verdict,
    }
