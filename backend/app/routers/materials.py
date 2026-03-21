"""资料管理路由"""
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List, Optional
from pydantic import BaseModel
import hashlib
import uuid

from ..database import get_db
from ..services.material_service import get_material_service
from ..ai.rag_service import get_rag_service
from ..config import settings
from ..models.material import Material
from ..models.chat import ChatProjectMaterial, ChatProject
from ..utils.paths import ensure_data_dirs, get_uploads_dir, to_repo_relative
from ..auth import get_current_user
from ..models.user import User


router = APIRouter()

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.md', '.epub'}
MAX_FILE_SIZE = 150 * 1024 * 1024  # 150MB


class MaterialResponse(BaseModel):
    """资料响应模型"""
    id: int
    title: str
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    content: Optional[str] = None
    content_status: Optional[str] = None
    created_at: str
    updated_at: str
    project_ids: Optional[List[int]] = None

    class Config:
        from_attributes = True


class MaterialUploadResponse(MaterialResponse):
    """上传资料响应模型"""
    duplicate: bool = False


class MaterialSearchResponse(BaseModel):
    """资料检索响应模型"""
    material_id: int
    title: str
    score: float
    text: str


def _build_material_response(
    material: Material,
    project_ids: Optional[List[int]] = None,
    preview: bool = False,
) -> MaterialResponse:
    material_dict = getattr(material, "__dict__", {})
    material_id = material_dict.get("id")
    if material_id is None:
        material_id = getattr(material, "id", 0)
    title = material_dict.get("title") or ""
    file_path = material_dict.get("file_path")
    file_type = material_dict.get("file_type")
    content_text = material_dict.get("content")
    content_status = material_dict.get("content_status")
    created_at = material_dict.get("created_at")
    updated_at = material_dict.get("updated_at")

    if preview and content_text is not None:
        content_text = content_text[:200]

    return MaterialResponse(
        id=int(material_id),
        title=str(title),
        file_path=str(file_path) if file_path is not None else None,
        file_type=str(file_type) if file_type is not None else None,
        content=content_text if content_text is None else str(content_text),
        content_status=str(content_status) if content_status is not None else None,
        created_at=(created_at or material.created_at).isoformat(),
        updated_at=(updated_at or material.updated_at).isoformat(),
        project_ids=project_ids or [],
    )


class MaterialCreate(BaseModel):
    """创建资料请求模型"""
    title: str
    content: Optional[str] = None


class QuestionRequest(BaseModel):
    """提问请求模型"""
    question: str


def _save_upload_with_hash(upload_file: UploadFile, abs_file_path: Path) -> str:
    """保存上传文件并返回 sha256。"""
    hasher = hashlib.sha256()
    with abs_file_path.open("wb") as buffer:
        while True:
            chunk = upload_file.file.read(1024 * 1024)
            if not chunk:
                break
            buffer.write(chunk)
            hasher.update(chunk)
    return hasher.hexdigest()


@router.post("/upload", response_model=MaterialUploadResponse)
async def upload_material(
    title: str = Form(...),
    file: UploadFile = File(...),
    sync_to_rag: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传学习资料文件

    - **title**: 资料标题
    - **file**: 上传的文件
    - **sync_to_rag**: 是否同步到 RAG 知识库
    """
    # 确保上传目录存在（项目根目录的 data/uploads）
    ensure_data_dirs()
    upload_dir = get_uploads_dir()

    # 校验扩展名白名单
    filename = file.filename or ""
    file_extension = Path(filename).suffix.lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_extension}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 生成唯一文件名
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    abs_file_path = upload_dir / unique_filename

    # 保存文件并计算 hash
    try:
        file_hash = _save_upload_with_hash(file, abs_file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")

    # 校验文件大小
    actual_size = abs_file_path.stat().st_size
    if actual_size > MAX_FILE_SIZE:
        abs_file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"文件大小 ({actual_size // 1024 // 1024}MB) 超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)",
        )

    # 在数据库里保存相对路径，便于迁移/部署
    repo_rel_path = to_repo_relative(abs_file_path)

    # 去重检查（同一用户相同文件哈希）
    from sqlalchemy import select as sa_select
    existing_result = await db.execute(
        sa_select(Material).where(
            Material.user_id == current_user.id,
            Material.file_hash == file_hash,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        if abs_file_path.exists():
            abs_file_path.unlink(missing_ok=True)

        # 获取该资料的项目关联
        assoc_result = await db.execute(
            sa_select(ChatProjectMaterial.project_id)
            .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
            .where(ChatProject.user_id == current_user.id)
            .where(ChatProjectMaterial.material_id == existing.id)
        )
        project_ids = [row[0] for row in assoc_result.all()]

        response = _build_material_response(existing, project_ids=project_ids)
        return MaterialUploadResponse(**response.model_dump(), duplicate=True)

    # 创建资料记录
    material_service = get_material_service(db)
    try:
        user_id_value: Any = getattr(current_user, "id", None)
        material = await material_service.create_material(
            title=title,
            file_path=repo_rel_path,
            file_type=file_extension.lstrip('.'),
            content=None,  # 交给 service 做统一的文件提取
            file_hash=file_hash,
            sync_to_rag=sync_to_rag,
            user_id=int(user_id_value) if user_id_value is not None else 0,
        )

        response = _build_material_response(material, project_ids=[])
        return MaterialUploadResponse(**response.model_dump(), duplicate=False)
    except Exception as e:
        # 如果创建失败，删除已上传的文件
        if abs_file_path.exists():
            abs_file_path.unlink()
        raise HTTPException(status_code=500, detail=f"创建资料失败: {str(e)}")


@router.post("/create", response_model=MaterialResponse)
async def create_material(
    material_data: MaterialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    创建文本资料（不上传文件）

    - **title**: 资料标题
    - **content**: 资料内容
    """
    material_service = get_material_service(db)
    try:
        user_id_value: Any = getattr(current_user, "id", None)
        material = await material_service.create_material(
            title=material_data.title,
            content=material_data.content,
            sync_to_rag=True,
            user_id=int(user_id_value) if user_id_value is not None else 0,
        )

        return _build_material_response(material, project_ids=[])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建资料失败: {str(e)}")


@router.get("/", response_model=List[MaterialResponse])
async def list_materials(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取资料列表

    - **skip**: 跳过数量
    - **limit**: 限制数量（最大100）
    """
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material)
        .where(Material.user_id == current_user.id)
        .offset(skip)
        .limit(min(limit, 100))
        .order_by(Material.created_at.desc())
    )
    materials = result.scalars().all()

    project_ids_map = {}
    material_ids = [m.id for m in materials]
    if material_ids:
        assoc_result = await db.execute(
            sa_select(ChatProjectMaterial.material_id, ChatProjectMaterial.project_id)
            .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
            .where(ChatProject.user_id == current_user.id)
            .where(ChatProjectMaterial.material_id.in_(material_ids))
        )
        for material_id, project_id in assoc_result.all():
            project_ids_map.setdefault(material_id, set()).add(project_id)

    return [
        _build_material_response(
            m,
            project_ids=sorted(project_ids_map.get(m.id, set())),
            preview=True,
        )
        for m in materials
    ]


@router.get("/search", response_model=List[MaterialSearchResponse])
async def search_materials(
    query: str,
    project_id: Optional[int] = None,
    top_k: int = 8,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在资料库中进行语义检索（可按项目过滤）。"""
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="检索内容不能为空")
    if not settings.RAG_ENABLED:
        return []

    material_ids: List[int] = []
    from sqlalchemy import select as sa_select

    if project_id is not None:
        proj_result = await db.execute(
            sa_select(ChatProject).where(ChatProject.id == project_id, ChatProject.user_id == current_user.id)
        )
        if not proj_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="项目不存在")
        assoc_result = await db.execute(
            sa_select(ChatProjectMaterial.material_id)
            .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
            .where(ChatProject.user_id == current_user.id)
            .where(ChatProjectMaterial.project_id == project_id)
        )
        material_ids = [row[0] for row in assoc_result.all()]
    else:
        result = await db.execute(
            sa_select(Material.id).where(Material.user_id == current_user.id)
        )
        material_ids = [row[0] for row in result.all()]

    if not material_ids:
        return []

    rag = get_rag_service()
    top_k_value = max(1, min(top_k, 20))
    chunks = await rag.retrieve(query=q, material_ids=material_ids, top_k=top_k_value)
    return [
        MaterialSearchResponse(
            material_id=chunk.get("material_id", 0),
            title=chunk.get("material_title", ""),
            score=chunk.get("score", 0),
            text=chunk.get("text", ""),
        )
        for chunk in chunks
    ]


@router.get("/{material_id}", response_model=MaterialResponse)
async def get_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取资料详情

    - **material_id**: 资料ID
    """
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = result.scalar_one_or_none()

    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    proj_result = await db.execute(
        sa_select(ChatProjectMaterial.project_id)
        .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
        .where(
            ChatProjectMaterial.material_id == material_id,
            ChatProject.user_id == current_user.id,
        )
    )
    project_ids = [row[0] for row in proj_result.all()]

    return _build_material_response(material, project_ids=project_ids)


@router.delete("/{material_id}")
async def delete_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除资料（数据库记录 + 本地上传文件）。"""
    # Verify ownership before deleting
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")

    material_service = get_material_service(db)
    deleted = await material_service.delete_material(material_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"ok": True}


@router.post("/{material_id}/analyze")
async def analyze_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    使用 RAG 知识库分析资料

    - **material_id**: 资料ID
    """
    # Verify ownership
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="资料不存在")

    material_service = get_material_service(db)
    try:
        analysis = await material_service.analyze_material_with_rag(material_id)
        return analysis
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/{material_id}/ask")
async def ask_question(
    material_id: int,
    request: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    向 AI 提问关于某份资料的问题

    - **material_id**: 资料ID
    - **question**: 问题内容
    """
    # Verify ownership
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="资料不存在")

    material_service = get_material_service(db)
    try:
        answer = await material_service.ask_question_about_material(
            material_id=material_id,
            question=request.question
        )
        return {
            "question": request.question,
            "answer": answer
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提问失败: {str(e)}")


@router.post("/{material_id}/generate-outline")
async def generate_outline(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    为资料生成章节学习大纲

    - **material_id**: 资料ID
    """
    # Verify ownership
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="资料不存在")

    material_service = get_material_service(db)
    try:
        outline = await material_service.generate_chapter_outline(material_id)
        return outline
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成大纲失败: {str(e)}")
