"""概念图谱服务（决策 D2）：抽取、去重、挂接与邻域查询。

降级纪律：图谱构建失败不得阻塞资料上传/分析主流程（调用方需捕获异常）。
成本纪律：资料分析已产出的 key_points 直接入图（零额外 LLM 调用）；
带关系的深抽取走独立接口，每章一次 LLM 调用。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptEdge, ConceptLink
from app.models.learner_model import UserConceptState
from app.models.material import Chapter
from app.models.question import WrongQuestion
from app.services.learner_model_service import ensure_concept_state
from app.utils.prompt_safety import wrap_untrusted_context

logger = logging.getLogger(__name__)

EDGE_TYPES = {"prerequisite_of", "related_to"}
LINK_TYPES = {"covers", "explains", "tests", "drills"}
MAX_CONCEPTS_PER_CHAPTER = 15
MAX_NAME_LENGTH = 60


def _mastery_snapshot(
    concept: Concept,
    state: UserConceptState | None,
) -> tuple[float, str, str | None]:
    """Prefer derived learner state; retain one-release legacy read fallback."""
    if state is not None:
        return float(state.mastery_estimate), "user_concept_state", state.model_version
    return float(concept.mastery or 0.0), "legacy_compatibility", None


def normalize_concept_name(name: str) -> str:
    """概念名归一化：压缩空白、去首尾标点、拉丁字符统一小写。"""
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    text = text.strip("，。；;、·:：\"'“”‘’()（）[]【】 ")
    return text.lower()[:MAX_NAME_LENGTH]


async def upsert_concept(
    db: AsyncSession,
    user_id: int,
    name: str,
    *,
    description: str | None = None,
    source: str = "extract",
) -> Concept | None:
    """按归一化名去重创建概念；名字为空返回 None。"""
    display = re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME_LENGTH]
    normalized = normalize_concept_name(display)
    if not normalized or len(normalized) < 2:
        return None

    result = await db.execute(
        select(Concept).where(Concept.user_id == user_id, Concept.name_normalized == normalized)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if description and not existing.description:
            existing.description = description[:500]
        return existing

    concept = Concept(
        user_id=user_id,
        name=display,
        name_normalized=normalized,
        description=(description or "")[:500] or None,
        source=source,
    )
    db.add(concept)
    await db.flush()
    await ensure_concept_state(db, user_id, int(concept.id))
    return concept


async def add_edge(
    db: AsyncSession,
    user_id: int,
    from_concept_id: int,
    to_concept_id: int,
    edge_type: str,
    *,
    confidence: float = 0.6,
    source: str = "extract",
) -> bool:
    """添加概念关系边；重复或非法边返回 False。"""
    if edge_type not in EDGE_TYPES or from_concept_id == to_concept_id:
        return False
    result = await db.execute(
        select(ConceptEdge.id).where(
            ConceptEdge.user_id == user_id,
            ConceptEdge.from_concept_id == from_concept_id,
            ConceptEdge.to_concept_id == to_concept_id,
            ConceptEdge.edge_type == edge_type,
        )
    )
    if result.scalar_one_or_none() is not None:
        return False
    db.add(
        ConceptEdge(
            user_id=user_id,
            from_concept_id=from_concept_id,
            to_concept_id=to_concept_id,
            edge_type=edge_type,
            confidence=max(0.0, min(1.0, float(confidence))),
            source=source,
        )
    )
    await db.flush()
    return True


async def link_concept(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    target_type: str,
    target_id: int,
    *,
    link_type: str = "covers",
) -> bool:
    """把既有实体挂接到概念；重复挂接返回 False。"""
    if link_type not in LINK_TYPES:
        return False
    result = await db.execute(
        select(ConceptLink.id).where(
            ConceptLink.user_id == user_id,
            ConceptLink.concept_id == concept_id,
            ConceptLink.target_type == target_type,
            ConceptLink.target_id == target_id,
        )
    )
    if result.scalar_one_or_none() is not None:
        return False
    db.add(
        ConceptLink(
            user_id=user_id,
            concept_id=concept_id,
            target_type=target_type,
            target_id=target_id,
            link_type=link_type,
        )
    )
    await db.flush()
    return True


async def ingest_structure_concepts(
    db: AsyncSession,
    user_id: int,
    material_id: int,
    structure_chapters: list[dict[str, Any]],
) -> int:
    """把资料分析产出的章节 key_points 直接入图（零额外 LLM 成本）。

    按章节标题匹配已入库的 Chapter 行，key_points 逐个 upsert 为概念并建立
    chapter COVERS concept 挂接。返回新建/挂接的概念数。
    """
    chapter_result = await db.execute(select(Chapter).where(Chapter.material_id == material_id))
    chapters_by_title = {str(c.title or "").strip(): c for c in chapter_result.scalars().all()}
    ingested = 0
    for item in structure_chapters or []:
        if not isinstance(item, dict):
            continue
        chapter = chapters_by_title.get(str(item.get("title") or "").strip())
        key_points = item.get("key_points") or []
        if not isinstance(key_points, list):
            continue
        for point in key_points[:MAX_CONCEPTS_PER_CHAPTER]:
            concept = await upsert_concept(db, user_id, str(point), source="structure")
            if not concept:
                continue
            if chapter is not None:
                await link_concept(db, user_id, concept.id, "chapter", int(chapter.id), link_type="covers")
            ingested += 1
    return ingested


def build_chapter_extraction_prompt(chapter_title: str, chapter_content: str) -> str:
    """构造每章一次的概念+关系抽取 prompt（内容按不可信上下文包装）。"""
    return (
        "你是学习概念抽取器。请从章节内容中提取知识点及其关系。"
        "只输出 JSON 对象，不要解释：\n"
        '{"concepts":[{"name":"概念名","description":"一句话简述"}],'
        '"edges":[{"from":"概念A","to":"概念B","type":"prerequisite_of|related_to"}]}\n'
        f"要求：concepts 最多 {MAX_CONCEPTS_PER_CHAPTER} 个；"
        "prerequisite_of 表示 from 是 to 的先修知识；关系不确定时宁缺毋滥。\n"
        + wrap_untrusted_context(
            "章节内容",
            f"章节标题：{chapter_title}\n{(chapter_content or '')[:5000]}",
            source="concept_extract",
        )
    )


def parse_extraction_response(raw: str) -> dict[str, Any]:
    """解析抽取输出；解析失败返回空结构（不抛异常）。"""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"concepts": [], "edges": []}
    if not isinstance(obj, dict):
        return {"concepts": [], "edges": []}
    concepts = obj.get("concepts") if isinstance(obj.get("concepts"), list) else []
    edges = obj.get("edges") if isinstance(obj.get("edges"), list) else []
    return {"concepts": concepts, "edges": edges}


async def extract_chapter_concepts_llm(
    db: AsyncSession,
    user_id: int,
    chapter: Chapter,
    provider: Any,
) -> dict[str, int]:
    """对单个章节做一次 LLM 概念+关系抽取并入图。"""
    prompt = build_chapter_extraction_prompt(str(chapter.title or ""), str(chapter.content or ""))
    raw = await provider.chat(
        messages=[{"role": "user", "content": prompt}],
        system_prompt="你是概念抽取器，只输出 JSON。",
        temperature=0.1,
    )
    parsed = parse_extraction_response(raw)

    name_to_id: dict[str, int] = {}
    created_concepts = 0
    for item in parsed["concepts"][:MAX_CONCEPTS_PER_CHAPTER]:
        if not isinstance(item, dict):
            continue
        concept = await upsert_concept(
            db, user_id, str(item.get("name") or ""),
            description=str(item.get("description") or "") or None,
        )
        if not concept:
            continue
        name_to_id[normalize_concept_name(concept.name)] = concept.id
        await link_concept(db, user_id, concept.id, "chapter", int(chapter.id), link_type="covers")
        created_concepts += 1

    created_edges = 0
    for edge in parsed["edges"][: MAX_CONCEPTS_PER_CHAPTER * 2]:
        if not isinstance(edge, dict):
            continue
        from_id = name_to_id.get(normalize_concept_name(str(edge.get("from") or "")))
        to_id = name_to_id.get(normalize_concept_name(str(edge.get("to") or "")))
        edge_type = str(edge.get("type") or "").strip()
        if not from_id or not to_id or edge_type not in EDGE_TYPES:
            continue
        if await add_edge(db, user_id, from_id, to_id, edge_type):
            created_edges += 1

    return {"concepts": created_concepts, "edges": created_edges}


async def backfill_wrong_question_concepts(db: AsyncSession, user_id: int) -> dict[str, int]:
    """把错题的 knowledge_point 字符串回填为概念实体 + TESTS 挂接 + concept_id 外键。"""
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.knowledge_point.is_not(None),
            WrongQuestion.concept_id.is_(None),
        )
    )
    updated = 0
    linked = 0
    for wrong in result.scalars().all():
        concept = await upsert_concept(db, user_id, str(wrong.knowledge_point or ""), source="backfill")
        if not concept:
            continue
        wrong.concept_id = concept.id
        updated += 1
        if await link_concept(db, user_id, concept.id, "wrong_question", int(wrong.id), link_type="tests"):
            linked += 1
    return {"updated_wrong_questions": updated, "created_links": linked}


async def list_concepts(db: AsyncSession, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    """概念总览：按挂接数量排序。"""
    link_counts = (
        select(ConceptLink.concept_id, func.count(ConceptLink.id).label("link_count"))
        .where(ConceptLink.user_id == user_id)
        .group_by(ConceptLink.concept_id)
        .subquery()
    )
    result = await db.execute(
        select(Concept, func.coalesce(link_counts.c.link_count, 0), UserConceptState)
        .outerjoin(link_counts, Concept.id == link_counts.c.concept_id)
        .outerjoin(
            UserConceptState,
            and_(
                UserConceptState.user_id == user_id,
                UserConceptState.concept_id == Concept.id,
            ),
        )
        .where(Concept.user_id == user_id)
        .order_by(func.coalesce(link_counts.c.link_count, 0).desc(), Concept.updated_at.desc())
        .limit(max(1, min(int(limit or 100), 500)))
    )
    concepts: list[dict[str, Any]] = []
    for concept, count, state in result.all():
        mastery, mastery_source, mastery_model_version = _mastery_snapshot(concept, state)
        concepts.append({
            "id": concept.id,
            "name": concept.name,
            "description": concept.description,
            "mastery": mastery,
            "mastery_source": mastery_source,
            "mastery_model_version": mastery_model_version,
            "source": concept.source,
            "link_count": int(count or 0),
        })
    return concepts


async def get_concept_neighborhood(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    depth: int = 1,
) -> dict[str, Any] | None:
    """概念邻域：depth（1-2）跳内的关联概念、关系边与挂接实体。"""
    center_result = await db.execute(
        select(Concept).where(Concept.id == concept_id, Concept.user_id == user_id)
    )
    center = center_result.scalar_one_or_none()
    if not center:
        return None

    depth = max(1, min(2, int(depth or 1)))
    visited = {center.id}
    frontier = {center.id}
    edges_out: list[dict[str, Any]] = []
    for _ in range(depth):
        if not frontier:
            break
        edge_result = await db.execute(
            select(ConceptEdge).where(
                ConceptEdge.user_id == user_id,
                (ConceptEdge.from_concept_id.in_(frontier)) | (ConceptEdge.to_concept_id.in_(frontier)),
            )
        )
        next_frontier: set[int] = set()
        for edge in edge_result.scalars().all():
            edges_out.append(
                {
                    "from": edge.from_concept_id,
                    "to": edge.to_concept_id,
                    "type": edge.edge_type,
                    "confidence": float(edge.confidence or 0.0),
                }
            )
            for node_id in (edge.from_concept_id, edge.to_concept_id):
                if node_id not in visited:
                    visited.add(node_id)
                    next_frontier.add(node_id)
        frontier = next_frontier

    node_result = await db.execute(
        select(Concept, UserConceptState)
        .outerjoin(
            UserConceptState,
            and_(
                UserConceptState.user_id == user_id,
                UserConceptState.concept_id == Concept.id,
            ),
        )
        .where(Concept.user_id == user_id, Concept.id.in_(visited))
    )
    nodes = []
    for concept, state in node_result.all():
        mastery, mastery_source, mastery_model_version = _mastery_snapshot(concept, state)
        nodes.append(
            {
                "id": concept.id,
                "name": concept.name,
                "mastery": mastery,
                "mastery_source": mastery_source,
                "mastery_model_version": mastery_model_version,
                "is_center": concept.id == center.id,
            }
        )

    link_result = await db.execute(
        select(ConceptLink).where(ConceptLink.user_id == user_id, ConceptLink.concept_id.in_(visited))
    )
    links = [
        {
            "concept_id": link.concept_id,
            "target_type": link.target_type,
            "target_id": link.target_id,
            "link_type": link.link_type,
        }
        for link in link_result.scalars().all()
    ]

    # 去重边（两跳时同一条边可能被访问两次）
    unique_edges = list({(e["from"], e["to"], e["type"]): e for e in edges_out}.values())
    return {"center_id": center.id, "nodes": nodes, "edges": unique_edges, "links": links}
