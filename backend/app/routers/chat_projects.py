"""对话项目管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel, Field
from typing import Optional, List

from app.database import get_db
from app.models.chat import ChatProject, ChatProjectMaterial, ChatConversation
from app.models.material import Material
from app.ai.rag_service import get_rag_service
from app.config import settings
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


async def _ensure_user_material(db: AsyncSession, material_id: int, user_id: int) -> None:
    result = await db.execute(
        select(Material.id).where(Material.id == material_id, Material.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="资料不存在")


async def _ensure_user_materials(db: AsyncSession, material_ids: List[int], user_id: int) -> None:
    unique_ids = {mid for mid in material_ids if mid is not None}
    if not unique_ids:
        return
    result = await db.execute(
        select(Material.id).where(Material.id.in_(unique_ids), Material.user_id == user_id)
    )
    found_ids = {row[0] for row in result.all()}
    if found_ids != unique_ids:
        raise HTTPException(status_code=404, detail="资料不存在")


async def _reindex_material_for_projects(db: AsyncSession, material_id: int, user_id: int) -> None:
    if not settings.RAG_ENABLED:
        return
    result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == user_id)
    )
    material = result.scalar_one_or_none()
    if not material or not material.content:
        return

    assoc_result = await db.execute(
        select(ChatProjectMaterial.project_id)
        .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
        .where(ChatProject.user_id == user_id)
        .where(ChatProjectMaterial.material_id == material_id)
    )
    project_ids = [row[0] for row in assoc_result.all()]

    rag = get_rag_service()
    await rag.index_material(
        material_id=material.id,
        title=material.title,
        content=material.content,
        file_type=material.file_type,
        project_ids=project_ids,
        user_id=user_id,
    )


# ---- Schemas ----

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    default_instructions: Optional[str] = Field(None, max_length=2000)
    color: Optional[str] = "#1890ff"


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    default_instructions: Optional[str] = Field(None, max_length=2000)
    color: Optional[str] = None
    is_archived: Optional[bool] = None


class MaterialAssociate(BaseModel):
    material_id: int


class MaterialBatchUpdate(BaseModel):
    add_material_ids: List[int] = []
    remove_material_ids: List[int] = []


class MaterialArchiveResponse(BaseModel):
    project_id: int
    project_name: str
    added_count: int
    total_unassigned: int


# ---- Endpoints ----

@router.get("")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有项目"""
    # Single query with conversation count via outerjoin + group_by
    from sqlalchemy import literal_column
    stmt = (
        select(
            ChatProject,
            func.count(ChatConversation.id).label("conv_count"),
        )
        .outerjoin(
            ChatConversation,
            (ChatConversation.project_id == ChatProject.id)
            & (ChatConversation.user_id == current_user.id),
        )
        .where(
            ChatProject.is_archived == False,
            ChatProject.user_id == current_user.id,
        )
        .group_by(ChatProject.id)
        .order_by(desc(ChatProject.updated_at))
    )
    result = await db.execute(stmt)
    rows = result.all()

    out = []
    for row in rows:
        p = row[0]
        conv_count = row[1] or 0
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "default_instructions": p.default_instructions,
            "color": p.color,
            "is_archived": p.is_archived,
            "conversation_count": conv_count,
            "created_at": str(p.created_at or ""),
            "updated_at": str(p.updated_at or ""),
        })

    return out


@router.post("/materials/archive-unassigned", response_model=MaterialArchiveResponse)
async def archive_unassigned_materials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将未归属任何项目的资料批量归档到默认项目（未分类）。"""
    # Ensure default project exists
    result = await db.execute(
        select(ChatProject).where(
            ChatProject.user_id == current_user.id,
            ChatProject.name == "未分类",
            ChatProject.is_archived == False,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        project = ChatProject(
            user_id=current_user.id,
            name="未分类",
            description="系统默认分类",
            color="#bfbfbf",
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)

    # All materials for current user
    mat_result = await db.execute(
        select(Material.id).where(Material.user_id == current_user.id)
    )
    all_material_ids = [row[0] for row in mat_result.all()]
    if not all_material_ids:
        return {
            "project_id": project.id,
            "project_name": project.name,
            "added_count": 0,
            "total_unassigned": 0,
        }

    # All material ids already associated to any project of current user
    assoc_result = await db.execute(
        select(ChatProjectMaterial.material_id)
        .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
        .where(ChatProject.user_id == current_user.id)
    )
    assigned_ids = {row[0] for row in assoc_result.all()}

    unassigned_ids = [mid for mid in all_material_ids if mid not in assigned_ids]
    if not unassigned_ids:
        return {
            "project_id": project.id,
            "project_name": project.name,
            "added_count": 0,
            "total_unassigned": 0,
        }

    for mid in unassigned_ids:
        db.add(ChatProjectMaterial(project_id=project.id, material_id=mid))
    await db.flush()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "added_count": len(unassigned_ids),
        "total_unassigned": len(unassigned_ids),
    }


@router.post("")
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建项目"""
    project = ChatProject(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        default_instructions=body.default_instructions,
        color=body.color or "#1890ff",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "default_instructions": project.default_instructions,
        "color": project.color,
        "is_archived": project.is_archived,
        "conversation_count": 0,
        "created_at": str(project.created_at or ""),
        "updated_at": str(project.updated_at or ""),
    }


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目详情"""
    result = await db.execute(
        select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    count_result = await db.execute(
        select(func.count(ChatConversation.id)).where(
            ChatConversation.project_id == project.id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv_count = count_result.scalar() or 0

    # 获取关联的资料 ID
    mat_result = await db.execute(
        select(ChatProjectMaterial.material_id)
        .join(Material, ChatProjectMaterial.material_id == Material.id)
        .where(
            ChatProjectMaterial.project_id == project.id,
            Material.user_id == current_user.id,
        )
    )
    material_ids = [row[0] for row in mat_result.all()]

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "default_instructions": project.default_instructions,
        "color": project.color,
        "is_archived": project.is_archived,
        "conversation_count": conv_count,
        "material_ids": material_ids,
        "created_at": str(project.created_at or ""),
        "updated_at": str(project.updated_at or ""),
    }


@router.put("/{project_id}")
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新项目"""
    result = await db.execute(
        select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.default_instructions is not None:
        project.default_instructions = body.default_instructions
    if body.color is not None:
        project.color = body.color
    if body.is_archived is not None:
        project.is_archived = body.is_archived

    await db.flush()
    await db.refresh(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "default_instructions": project.default_instructions,
        "color": project.color,
        "is_archived": project.is_archived,
        "created_at": str(project.created_at or ""),
        "updated_at": str(project.updated_at or ""),
    }


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除项目（对话变为无项目）"""
    result = await db.execute(
        select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 将该项目下的对话设为无项目
    conv_result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.project_id == project_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    for conv in conv_result.scalars().all():
        conv.project_id = None

    await db.delete(project)
    return {"ok": True}


@router.post("/{project_id}/materials")
async def add_material(
    project_id: int,
    body: MaterialAssociate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """关联资料到项目"""
    # 检查项目存在且属于当前用户
    result = await db.execute(
        select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    await _ensure_user_material(db, body.material_id, current_user.id)

    # 检查是否已关联
    existing = await db.execute(
        select(ChatProjectMaterial).where(
            ChatProjectMaterial.project_id == project_id,
            ChatProjectMaterial.material_id == body.material_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"ok": True, "message": "已关联"}

    assoc = ChatProjectMaterial(project_id=project_id, material_id=body.material_id)
    db.add(assoc)
    await db.flush()
    await _reindex_material_for_projects(db, body.material_id, current_user.id)
    return {"ok": True}


@router.delete("/{project_id}/materials/{material_id}")
async def remove_material(
    project_id: int,
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除项目的资料关联"""
    # Verify project and material belong to current user
    proj_result = await db.execute(
        select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
    )
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    await _ensure_user_material(db, material_id, current_user.id)

    material_result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    if not material_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="资料不存在")

    result = await db.execute(
        select(ChatProjectMaterial).where(
            ChatProjectMaterial.project_id == project_id,
            ChatProjectMaterial.material_id == material_id,
        )
    )
    assoc = result.scalar_one_or_none()
    if not assoc:
        raise HTTPException(status_code=404, detail="关联不存在")

    await db.delete(assoc)
    await db.flush()
    await _reindex_material_for_projects(db, material_id, current_user.id)
    return {"ok": True}


@router.put("/{project_id}/materials")
async def batch_update_materials(
    project_id: int,
    body: MaterialBatchUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量更新项目资料关联"""
    # 验证项目归属
    result = await db.execute(
        select(ChatProject).where(
            ChatProject.id == project_id,
            ChatProject.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    await _ensure_user_materials(
        db,
        body.add_material_ids + body.remove_material_ids,
        current_user.id,
    )

    added = 0
    removed = 0
    impacted_ids = sorted(set(body.add_material_ids) | set(body.remove_material_ids))

    # 移除关联
    if body.remove_material_ids:
        for mid in body.remove_material_ids:
            result = await db.execute(
                select(ChatProjectMaterial).where(
                    ChatProjectMaterial.project_id == project_id,
                    ChatProjectMaterial.material_id == mid,
                )
            )
            assoc = result.scalar_one_or_none()
            if assoc:
                await db.delete(assoc)
                removed += 1

    # 添加关联（跳过已存在）
    if body.add_material_ids:
        for mid in body.add_material_ids:
            existing = await db.execute(
                select(ChatProjectMaterial).where(
                    ChatProjectMaterial.project_id == project_id,
                    ChatProjectMaterial.material_id == mid,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(ChatProjectMaterial(project_id=project_id, material_id=mid))
                added += 1

    await db.flush()
    for mid in impacted_ids:
        await _reindex_material_for_projects(db, mid, current_user.id)
    return {
        "ok": True,
        "added": added,
        "removed": removed,
    }
