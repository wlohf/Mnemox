"""资料管理服务层"""
from typing import Optional, List, Dict, Any
from pathlib import Path
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.material import Material, Chapter
from app.ai.anythingllm_provider import get_anythingllm_provider
from app.config import settings


class MaterialService:
    """资料管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.anythingllm = None
        
        # 如果启用了 AnythingLLM，初始化提供商
        if settings.ANYTHINGLLM_ENABLED:
            self.anythingllm = get_anythingllm_provider()
    
    async def create_material(
        self,
        title: str,
        file_path: Optional[str] = None,
        file_type: Optional[str] = None,
        content: Optional[str] = None,
        sync_to_anythingllm: bool = True
    ) -> Material:
        """
        创建新资料
        
        Args:
            title: 资料标题
            file_path: 文件路径
            file_type: 文件类型
            content: 文本内容
            sync_to_anythingllm: 是否同步到 AnythingLLM
        
        Returns:
            创建的资料对象
        """
        # 创建数据库记录
        material = Material(
            title=title,
            file_path=file_path,
            file_type=file_type,
            content=content
        )
        
        self.db.add(material)
        await self.db.commit()
        await self.db.refresh(material)
        
        # 如果启用了 AnythingLLM 并且需要同步
        if sync_to_anythingllm and self.anythingllm and file_path:
            try:
                await self._sync_to_anythingllm(material)
            except Exception as e:
                print(f"同步到 AnythingLLM 失败: {e}")
                # 不影响主流程，继续返回
        
        return material
    
    async def _sync_to_anythingllm(self, material: Material) -> None:
        """
        将资料同步到 AnythingLLM
        
        Args:
            material: 资料对象
        """
        if not self.anythingllm or not material.file_path:
            return
        
        # 检查服务是否在线
        online = await self.anythingllm.check_online()
        if not online:
            raise RuntimeError("AnythingLLM 服务未启动")
        
        # 确保工作空间存在
        workspace = await self.anythingllm.ensure_workspace()
        workspace_slug = workspace.get("slug", settings.ANYTHINGLLM_WORKSPACE)
        
        # 准备元数据
        metadata = {
            "title": material.title,
            "docSource": "StudyAssistant上传",
            "description": f"学习资料ID: {material.id}"
        }
        
        # 上传文档
        result = await self.anythingllm.upload_document(
            file_path=material.file_path,
            folder_name="study-materials",
            workspace_slugs=[workspace_slug],
            metadata=metadata
        )
        
        print(f"资料 '{material.title}' 已同步到 AnythingLLM: {result}")
    
    async def get_material(self, material_id: int) -> Optional[Material]:
        """
        获取资料详情
        
        Args:
            material_id: 资料ID
        
        Returns:
            资料对象，如果不存在返回 None
        """
        result = await self.db.execute(
            select(Material).where(Material.id == material_id)
        )
        return result.scalar_one_or_none()
    
    async def list_materials(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[Material]:
        """
        获取资料列表
        
        Args:
            skip: 跳过数量
            limit: 限制数量
        
        Returns:
            资料列表
        """
        result = await self.db.execute(
            select(Material).offset(skip).limit(limit)
        )
        return list(result.scalars().all())
    
    async def analyze_material_with_rag(
        self,
        material_id: int
    ) -> Dict[str, Any]:
        """
        使用 AnythingLLM RAG 分析资料
        
        Args:
            material_id: 资料ID
        
        Returns:
            分析结果
        """
        if not self.anythingllm:
            raise RuntimeError("AnythingLLM 未启用")
        
        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")
        
        # 使用 RAG 分析
        analysis = await self.anythingllm.analyze_document(
            material_title=material.title,
            material_content=material.content or ""
        )
        
        return analysis
    
    async def ask_question_about_material(
        self,
        material_id: int,
        question: str
    ) -> str:
        """
        向 AI 提问关于某份资料的问题
        
        Args:
            material_id: 资料ID
            question: 问题
        
        Returns:
            AI 回答
        """
        if not self.anythingllm:
            raise RuntimeError("AnythingLLM 未启用")
        
        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")
        
        # 构建带上下文的问题
        query = f"关于《{material.title}》：{question}"
        
        # 调用 AnythingLLM
        response = await self.anythingllm.chat(query, mode="query")
        
        return response.get("textResponse", "")
    
    async def generate_chapter_outline(
        self,
        material_id: int
    ) -> List[Dict[str, Any]]:
        """
        为资料生成章节大纲
        
        Args:
            material_id: 资料ID
        
        Returns:
            章节大纲列表
        """
        if not self.anythingllm:
            raise RuntimeError("AnythingLLM 未启用")
        
        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")
        
        # 请求 AI 生成大纲
        prompt = f"""请为以下学习资料生成详细的章节学习大纲：

资料标题：{material.title}

请按照以下格式生成：
1. 章节标题
   - 知识点1
   - 知识点2
2. 章节标题
   - 知识点1
   ...
"""
        
        response = await self.anythingllm.chat(prompt, mode="query")
        
        # 返回原始响应
        # TODO: 可以进一步解析响应并自动创建 Chapter 记录
        return {
            "material_id": material_id,
            "outline": response.get("textResponse", "")
        }


def get_material_service(db: AsyncSession) -> MaterialService:
    """获取资料服务实例"""
    return MaterialService(db)
