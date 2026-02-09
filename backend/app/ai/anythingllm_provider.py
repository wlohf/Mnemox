"""AnythingLLM RAG 提供商"""
import httpx
from typing import List, Dict, Optional, Any
import asyncio
from pathlib import Path
import json


class AnythingLLMProvider:
    """AnythingLLM RAG 系统集成"""
    
    def __init__(
        self, 
        base_url: str = "http://localhost:3001",
        api_key: Optional[str] = None,
        default_workspace: str = "study-materials",
        collector_url: str = "http://localhost:8888"
    ):
        """
        初始化 AnythingLLM 提供商
        
        Args:
            base_url: AnythingLLM 服务器地址
            api_key: API 密钥 (如果需要)
            default_workspace: 默认工作空间名称
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.default_workspace = default_workspace
        self.collector_url = collector_url.rstrip('/')
        self.headers = {}
        
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
    
    async def check_online(self) -> bool:
        """检查 AnythingLLM 服务是否在线"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/ping")
                return response.status_code == 200
        except Exception as e:
            print(f"AnythingLLM 服务检查失败: {e}")
            return False
    
    async def check_collector_online(self) -> bool:
        """检查文档处理服务是否在线"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.collector_url}/ping")
                return response.status_code == 200
        except Exception as e:
            print(f"文档处理服务检查失败: {e}")
            return False
    
    async def create_workspace(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        创建工作空间
        
        Args:
            name: 工作空间名称，如果为 None 则使用默认名称
        
        Returns:
            工作空间信息
        """
        workspace_name = name or self.default_workspace
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/workspace/new",
                json={"name": workspace_name},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_workspace(self, slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取工作空间信息
        
        Args:
            slug: 工作空间 slug，如果为 None 则使用默认工作空间
        
        Returns:
            工作空间信息，如果不存在返回 None
        """
        workspace_slug = slug or self.default_workspace
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/workspace/{workspace_slug}",
                    headers=self.headers
                )
                if response.status_code == 200:
                    return response.json().get("workspace")
                return None
        except Exception as e:
            print(f"获取工作空间失败: {e}")
            return None
    
    async def ensure_workspace(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        确保工作空间存在，如果不存在则创建
        
        Args:
            name: 工作空间名称
        
        Returns:
            工作空间信息
        """
        workspace_name = name or self.default_workspace
        workspace_slug = workspace_name.lower().replace(" ", "-")
        
        # 先尝试获取
        workspace = await self.get_workspace(workspace_slug)
        if workspace:
            return workspace
        
        # 不存在则创建
        result = await self.create_workspace(workspace_name)
        return result.get("workspace", {})
    
    async def upload_document(
        self, 
        file_path: str,
        folder_name: str = "study-materials",
        workspace_slugs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        上传文档到 AnythingLLM
        
        Args:
            file_path: 文件路径
            folder_name: 目标文件夹名称
            workspace_slugs: 要嵌入的工作空间列表
            metadata: 文档元数据 (title, docAuthor, description, docSource)
        
        Returns:
            上传结果
        """
        # 确保文档处理服务在线
        collector_online = await self.check_collector_online()
        if not collector_online:
            raise RuntimeError("文档处理服务未启动，请先启动 collector 服务")
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 准备上传数据
        files = {
            "file": (file_path_obj.name, open(file_path_obj, "rb"))
        }
        
        data = {}
        if workspace_slugs:
            data["addToWorkspaces"] = ",".join(workspace_slugs)
        
        if metadata:
            data["metadata"] = json.dumps(metadata)
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/document/upload/{folder_name}",
                    files=files,
                    data=data,
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        finally:
            # 关闭文件
            if files["file"][1]:
                files["file"][1].close()
    
    async def chat(
        self,
        message: str,
        workspace_slug: Optional[str] = None,
        mode: str = "query"  # query 或 chat
    ) -> Dict[str, Any]:
        """
        与工作空间中的文档进行对话
        
        Args:
            message: 用户消息
            workspace_slug: 工作空间 slug
            mode: 对话模式，query (RAG查询) 或 chat (普通对话)
        
        Returns:
            AI 响应
        """
        workspace = workspace_slug or self.default_workspace
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/workspace/{workspace}/chat",
                json={
                    "message": message,
                    "mode": mode
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_documents(
        self,
        workspace_slug: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取工作空间中的文档列表
        
        Args:
            workspace_slug: 工作空间 slug
        
        Returns:
            文档列表
        """
        workspace = workspace_slug or self.default_workspace
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/workspace/{workspace}/documents",
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            return data.get("documents", [])
    
    async def analyze_document(
        self,
        material_title: str,
        material_content: str,
        questions: List[str] = None
    ) -> Dict[str, Any]:
        """
        使用 AnythingLLM 分析文档内容
        
        Args:
            material_title: 资料标题
            material_content: 资料内容
            questions: 要问的问题列表
        
        Returns:
            分析结果
        """
        if questions is None:
            questions = [
                "请总结这份资料的主要内容",
                "这份资料有哪些重点知识点？",
                "请为这份资料生成学习大纲"
            ]
        
        results = []
        for question in questions:
            # 构建查询，包含文档上下文
            query = f"关于《{material_title}》：{question}"
            response = await self.chat(query, mode="query")
            results.append({
                "question": question,
                "answer": response.get("textResponse", "")
            })
        
        return {
            "title": material_title,
            "analysis": results
        }
    
    async def generate_study_questions(
        self,
        material_title: str,
        chapter_content: str,
        num_questions: int = 5
    ) -> List[Dict[str, Any]]:
        """
        基于章节内容生成学习问题
        
        Args:
            material_title: 资料标题
            chapter_content: 章节内容
            num_questions: 生成问题数量
        
        Returns:
            问题列表
        """
        prompt = f"""基于以下学习资料生成 {num_questions} 个学习问题：

资料：《{material_title}》

内容：
{chapter_content[:1000]}  # 限制长度

请生成选择题和简答题，包含答案和解析。"""
        
        response = await self.chat(prompt, mode="chat")
        
        # 这里需要解析 AI 的响应来提取问题
        # 简单起见，返回原始响应
        return {
            "raw_response": response.get("textResponse", ""),
            "questions": []  # TODO: 解析具体问题
        }


# 全局实例
_anythingllm_instance: Optional[AnythingLLMProvider] = None


def get_anythingllm_provider() -> AnythingLLMProvider:
    """获取 AnythingLLM 提供商实例（单例）"""
    global _anythingllm_instance
    
    if _anythingllm_instance is None:
        from app.config import settings
        _anythingllm_instance = AnythingLLMProvider(
            base_url=getattr(settings, "ANYTHINGLLM_BASE_URL", "http://localhost:3001"),
            api_key=getattr(settings, "ANYTHINGLLM_API_KEY", None),
            default_workspace=getattr(settings, "ANYTHINGLLM_WORKSPACE", "study-materials"),
            collector_url=getattr(settings, "ANYTHINGLLM_COLLECTOR_URL", "http://localhost:8888")
        )
    
    return _anythingllm_instance
