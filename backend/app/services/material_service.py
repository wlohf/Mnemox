"""资料管理服务层"""
import hashlib
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

from app.models.material import Material, Chapter
from app.ai.rag_service import get_rag_service
from app.config import settings
from app.utils.paths import from_repo_relative
from app.utils.file_extract import extract_text


class MaterialService:
    """资料管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rag = get_rag_service()

    async def create_material(
        self,
        title: str,
        file_path: Optional[str] = None,
        file_type: Optional[str] = None,
        content: Optional[str] = None,
        file_hash: Optional[str] = None,
        content_hash: Optional[str] = None,
        sync_to_rag: bool = True,
        user_id: int = 1,
    ) -> Material:
        """创建新资料"""
        content_status = "pending"
        if (content is None or content.strip() == "") and file_path:
            extracted = extract_text(from_repo_relative(file_path))
            if extracted:
                content = extracted
                content_status = "extracted"
            else:
                content_status = "failed"
        elif content:
            content_status = "extracted"

        if content and not content_hash:
            content_hash = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

        material = Material(
            user_id=user_id,
            title=title,
            file_path=file_path,
            file_type=file_type,
            file_hash=file_hash,
            content_hash=content_hash,
            content=content,
            content_status=content_status,
        )

        self.db.add(material)
        await self.db.commit()
        await self.db.refresh(material)

        if sync_to_rag and settings.RAG_ENABLED and content:
            try:
                material_id_value = material.__dict__.get("id", 0)
                await self.rag.index_material(
                    material_id=int(material_id_value),
                    title=title,
                    content=content,
                    file_type=file_type,
                )
            except Exception as e:
                logger.warning("同步到 RAG 知识库失败: %s", e)

        return material

    async def get_material(self, material_id: int) -> Optional[Material]:
        """获取资料详情"""
        result = await self.db.execute(
            select(Material).where(Material.id == material_id)
        )
        return result.scalar_one_or_none()

    async def list_materials(
        self,
        skip: int = 0,
        limit: int = 100,
        user_id: Optional[int] = None,
    ) -> List[Material]:
        """获取资料列表"""
        query = select(Material)
        if user_id is not None:
            query = query.where(Material.user_id == user_id)
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def delete_material(self, material_id: int) -> bool:
        """删除资料记录及其本地文件。"""
        material = await self.get_material(material_id)
        if not material:
            return False

        abs_file_path = None
        file_path_value = material.__dict__.get("file_path")
        if file_path_value:
            abs_file_path = from_repo_relative(str(file_path_value))

        await self.db.delete(material)
        await self.db.commit()

        if settings.RAG_ENABLED:
            try:
                await self.rag.remove_material(material_id)
            except Exception as e:
                logger.warning("从 RAG 删除资料失败: %s", e)

        if abs_file_path and abs_file_path.exists():
            try:
                abs_file_path.unlink()
            except Exception as e:
                logger.warning("删除本地文件失败: %s", e)

        return True

    async def analyze_material_with_rag(
        self,
        material_id: int
    ) -> Dict[str, Any]:
        """使用 RAG 检索 + AI 分析资料"""
        if not settings.RAG_ENABLED:
            raise RuntimeError("RAG 知识库未启用")

        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")

        questions = [
            "请总结这份资料的主要内容",
            "这份资料有哪些重点知识点？",
            "请为这份资料生成学习大纲",
        ]

        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(db=self.db, scenario="chat_main")
        results = []

        for question in questions:
            chunks = await self.rag.retrieve_for_material(question, material_id)
            context = "\n\n".join(c["text"] for c in chunks) if chunks else (material.content or "")[:4000]

            prompt = f"关于《{material.title}》的以下内容：\n\n{context}\n\n问题：{question}"
            reply = await provider.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是一个专业的学习助手，请基于提供的资料内容回答问题。",
            )
            results.append({"question": question, "answer": reply})

        return {"title": material.title, "analysis": results}

    async def ask_question_about_material(
        self,
        material_id: int,
        question: str
    ) -> str:
        """向 AI 提问关于某份资料的问题"""
        if not settings.RAG_ENABLED:
            raise RuntimeError("RAG 知识库未启用")

        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")

        chunks = await self.rag.retrieve_for_material(question, material_id)
        context = "\n\n".join(c["text"] for c in chunks) if chunks else (material.content or "")[:4000]

        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(db=self.db, scenario="chat_main")
        prompt = f"关于《{material.title}》的以下内容：\n\n{context}\n\n问题：{question}"
        reply = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是一个专业的学习助手，请基于提供的资料内容回答问题。",
        )
        return reply

    async def generate_chapter_outline(
        self,
        material_id: int
    ) -> Dict[str, Any]:
        """为资料生成章节大纲"""
        if not settings.RAG_ENABLED:
            raise RuntimeError("RAG 知识库未启用")

        material = await self.get_material(material_id)
        if not material:
            raise ValueError(f"资料不存在: {material_id}")

        question = "请为这份资料生成详细的章节学习大纲"
        chunks = await self.rag.retrieve_for_material(question, material_id, top_k=12)
        context = "\n\n".join(c["text"] for c in chunks) if chunks else (material.content or "")[:4000]

        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(db=self.db, scenario="chat_main")
        prompt = f"""请为以下学习资料生成详细的章节学习大纲：

资料标题：{material.title}

资料内容片段：
{context}

请按照以下格式生成：
1. 章节标题
   - 知识点1
   - 知识点2
2. 章节标题
   - 知识点1
   ...
"""
        reply = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是一个专业的学习助手，请基于提供的资料内容生成学习大纲。",
        )
        return {"material_id": material_id, "outline": reply}


def get_material_service(db: AsyncSession) -> MaterialService:
    """获取资料服务实例"""
    return MaterialService(db)
