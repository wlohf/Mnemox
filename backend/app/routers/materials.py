"""资料管理路由"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel
from pathlib import Path
import shutil
import uuid

from app.database import get_db
from app.services.material_service import get_material_service, MaterialService
from app.models.material import Material


router = APIRouter()


class MaterialResponse(BaseModel):
    """资料响应模型"""
    id: int
    title: str
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    content: Optional[str] = None
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class MaterialCreate(BaseModel):
    """创建资料请求模型"""
    title: str
    content: Optional[str] = None


class QuestionRequest(BaseModel):
    """提问请求模型"""
    question: str


@router.post("/upload", response_model=MaterialResponse)
async def upload_material(
    title: str = Form(...),
    file: UploadFile = File(...),
    sync_to_anythingllm: bool = Form(True),
    db: AsyncSession = Depends(get_db)
):
    """
    上传学习资料文件
    
    - **title**: 资料标题
    - **file**: 上传的文件
    - **sync_to_anythingllm**: 是否同步到 AnythingLLM
    """
    # 确保上传目录存在
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成唯一文件名
    file_extension = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = upload_dir / unique_filename
    
    # 保存文件
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    
    # 读取文本内容（如果是文本文件）
    content = None
    if file_extension.lower() in ['.txt', '.md']:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"读取文件内容失败: {e}")
    
    # 创建资料记录
    material_service = get_material_service(db)
    try:
        material = await material_service.create_material(
            title=title,
            file_path=str(file_path),
            file_type=file_extension.lstrip('.'),
            content=content,
            sync_to_anythingllm=sync_to_anythingllm
        )
        
        return MaterialResponse(
            id=material.id,
            title=material.title,
            file_path=material.file_path,
            file_type=material.file_type,
            content=material.content,
            created_at=material.created_at.isoformat(),
            updated_at=material.updated_at.isoformat()
        )
    except Exception as e:
        # 如果创建失败，删除已上传的文件
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"创建资料失败: {str(e)}")


@router.post("/create", response_model=MaterialResponse)
async def create_material(
    material_data: MaterialCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    创建文本资料（不上传文件）
    
    - **title**: 资料标题
    - **content**: 资料内容
    """
    material_service = get_material_service(db)
    try:
        material = await material_service.create_material(
            title=material_data.title,
            content=material_data.content,
            sync_to_anythingllm=False  # 纯文本暂不同步
        )
        
        return MaterialResponse(
            id=material.id,
            title=material.title,
            file_path=material.file_path,
            file_type=material.file_type,
            content=material.content,
            created_at=material.created_at.isoformat(),
            updated_at=material.updated_at.isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建资料失败: {str(e)}")


@router.get("/", response_model=List[MaterialResponse])
async def list_materials(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    获取资料列表
    
    - **skip**: 跳过数量
    - **limit**: 限制数量（最大100）
    """
    material_service = get_material_service(db)
    materials = await material_service.list_materials(skip=skip, limit=min(limit, 100))
    
    return [
        MaterialResponse(
            id=m.id,
            title=m.title,
            file_path=m.file_path,
            file_type=m.file_type,
            content=m.content[:200] if m.content else None,  # 列表只返回前200字符
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat()
        )
        for m in materials
    ]


@router.get("/{material_id}", response_model=MaterialResponse)
async def get_material(
    material_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    获取资料详情
    
    - **material_id**: 资料ID
    """
    material_service = get_material_service(db)
    material = await material_service.get_material(material_id)
    
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    
    return MaterialResponse(
        id=material.id,
        title=material.title,
        file_path=material.file_path,
        file_type=material.file_type,
        content=material.content,
        created_at=material.created_at.isoformat(),
        updated_at=material.updated_at.isoformat()
    )


@router.post("/{material_id}/analyze")
async def analyze_material(
    material_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    使用 AnythingLLM RAG 分析资料
    
    - **material_id**: 资料ID
    """
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
    db: AsyncSession = Depends(get_db)
):
    """
    向 AI 提问关于某份资料的问题
    
    - **material_id**: 资料ID
    - **question**: 问题内容
    """
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
    db: AsyncSession = Depends(get_db)
):
    """
    为资料生成章节学习大纲
    
    - **material_id**: 资料ID
    """
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
