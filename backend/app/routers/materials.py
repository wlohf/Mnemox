"""资料管理路由"""
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy import or_
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
from ..utils.ownership import get_owned_row


router = APIRouter()

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.md'}
ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
}
MAX_FILE_SIZE = max(1, int(settings.MATERIAL_UPLOAD_MAX_MB)) * 1024 * 1024


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

    model_config = {"from_attributes": True}


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


def _format_size_limit(max_size: int) -> str:
    if max_size >= 1024 * 1024:
        return f"{max_size // 1024 // 1024}MB"
    if max_size >= 1024:
        return f"{max_size // 1024}KB"
    return f"{max_size}B"


def _save_upload_with_hash(upload_file: UploadFile, abs_file_path: Path, max_size: int) -> tuple[str, int]:
    """保存上传文件并返回 (sha256, bytes_written)，边写入边限制大小。"""
    hasher = hashlib.sha256()
    total = 0
    try:
        with abs_file_path.open("wb") as buffer:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件大小超过限制 ({_format_size_limit(max_size)})",
                    )
                buffer.write(chunk)
                hasher.update(chunk)
    except Exception:
        abs_file_path.unlink(missing_ok=True)
        raise
    return hasher.hexdigest(), total


def _keyword_score(material: Material, query: str) -> float:
    q = query.lower()
    title = str(getattr(material, "title", "") or "")
    content = str(getattr(material, "content", "") or "")
    score = 0.0
    if q and q in title.lower():
        score += 0.35
    if q and q in content.lower():
        score += 0.55
    if q:
        tokens = [t for t in q.split() if t]
        if tokens:
            haystack = f"{title}\n{content}".lower()
            score += min(0.1, 0.02 * sum(1 for t in tokens if t in haystack))
    return round(min(score or 0.35, 0.99), 4)


def _keyword_snippet(material: Material, query: str, length: int = 360) -> str:
    content = str(getattr(material, "content", "") or "")
    if not content:
        return ""
    lower = content.lower()
    q = query.lower()
    idx = lower.find(q) if q else -1
    if idx < 0:
        idx = 0
    start = max(0, idx - length // 3)
    end = min(len(content), start + length)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet += "..."
    return snippet


async def _keyword_search_materials(
    db: AsyncSession,
    user_id: int,
    material_ids: List[int],
    query: str,
    limit: int,
) -> List[MaterialSearchResponse]:
    if not material_ids:
        return []
    like = f"%{query}%"
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Material)
        .where(Material.user_id == user_id, Material.id.in_(material_ids))
        .where(or_(Material.title.ilike(like), Material.content.ilike(like)))
        .order_by(Material.updated_at.desc(), Material.id.desc())
        .limit(limit)
    )
    return [
        MaterialSearchResponse(
            material_id=int(material.id),
            title=str(material.title or ""),
            score=_keyword_score(material, query),
            text=_keyword_snippet(material, query),
        )
        for material in result.scalars().all()
    ]


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

    # 校验扩展名白名单；只使用后端生成文件名，不信任用户原始文件名。
    original_name = Path(file.filename or "").name
    file_extension = Path(original_name).suffix.lower()
    if not file_extension or file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_extension or 'unknown'}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    allowed_types = ALLOWED_CONTENT_TYPES.get(file_extension, set())
    if content_type and content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="上传内容类型与文件扩展名不匹配")

    # 生成唯一文件名
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    abs_file_path = upload_dir / unique_filename

    # 保存文件并计算 hash（边写入边限制大小，避免超大文件先完整落盘）
    try:
        file_hash, _actual_size = _save_upload_with_hash(file, abs_file_path, MAX_FILE_SIZE)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")

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
    chunks = []
    if settings.RAG_ENABLED:
        chunks = await rag.retrieve(query=q, material_ids=material_ids, top_k=top_k_value, user_id=current_user.id)
    if chunks:
        return [
            MaterialSearchResponse(
                material_id=chunk.get("material_id", 0),
                title=chunk.get("material_title", ""),
                score=chunk.get("score", 0),
                text=chunk.get("text", ""),
            )
            for chunk in chunks
        ]
    return await _keyword_search_materials(db, int(current_user.id), material_ids, q, top_k_value)


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
    material = await get_owned_row(
        db,
        Material,
        material_id,
        int(current_user.id),
        not_found_detail="资料不存在",
    )

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
    await get_owned_row(db, Material, material_id, int(current_user.id), not_found_detail="资料不存在")

    material_service = get_material_service(db)
    deleted = await material_service.delete_material(material_id, user_id=current_user.id)
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
    await get_owned_row(db, Material, material_id, int(current_user.id), not_found_detail="资料不存在")

    material_service = get_material_service(db)
    try:
        analysis = await material_service.analyze_material_with_rag(
            material_id,
            user_id=current_user.id,
        )
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
    await get_owned_row(db, Material, material_id, int(current_user.id), not_found_detail="资料不存在")

    material_service = get_material_service(db)
    try:
        answer = await material_service.ask_question_about_material(
            material_id=material_id,
            question=request.question,
            user_id=current_user.id,
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
    await get_owned_row(db, Material, material_id, int(current_user.id), not_found_detail="资料不存在")

    material_service = get_material_service(db)
    try:
        outline = await material_service.generate_chapter_outline(
            material_id,
            user_id=current_user.id,
        )
        return outline
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成大纲失败: {str(e)}")
