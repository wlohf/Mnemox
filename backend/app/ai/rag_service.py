"""RAG 服务：基于 LlamaIndex + ChromaDB 的本地向量检索。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from app.config import settings
from app.utils.paths import get_chromadb_dir, get_data_dir


def _get_rag_settings_path():
    return get_data_dir() / "rag_settings.json"


def load_rag_settings() -> Dict[str, str]:
    """从 data/rag_settings.json 读取 RAG embedding 配置，不存在则返回空 dict。"""
    path = _get_rag_settings_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("读取 RAG 配置文件失败: %s", e)
    return {}


def save_rag_settings(data: Dict[str, str]) -> None:
    """将 RAG embedding 配置写入 data/rag_settings.json。"""
    path = _get_rag_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class RAGService:
    """单例 RAG 服务，封装 LlamaIndex + ChromaDB。"""

    def __init__(self) -> None:
        self._initialized = False
        self._chroma_client = None
        self._collection = None
        self._embed_model = None
        self._splitter = None
        self._current_api_key: str = ""
        self._current_base_url: str = ""
        self._current_model: str = ""
        self._last_error: str = ""
        self._last_retrieval_status: Dict[str, Any] = {"ok": True, "mode": "not_run", "message": "尚未检索"}
        self._last_retrieval_status_by_user: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 解析配置（JSON 文件 > config.py 默认值）
    # ------------------------------------------------------------------

    def _resolve_config(self) -> Dict[str, Any]:
        """合并 JSON 文件与 config.py 的配置，JSON 优先。"""
        file_cfg = load_rag_settings()
        api_key = file_cfg.get("api_key") or settings.OPENAI_API_KEY
        base_url = file_cfg.get("base_url") or settings.OPENAI_BASE_URL
        model = file_cfg.get("model") or settings.RAG_EMBEDDING_MODEL
        chunk_size = file_cfg.get("chunk_size") or settings.RAG_CHUNK_SIZE
        chunk_overlap = file_cfg.get("chunk_overlap") or settings.RAG_CHUNK_OVERLAP
        top_k = file_cfg.get("top_k") or settings.RAG_TOP_K
        similarity_threshold = file_cfg.get("similarity_threshold") or settings.RAG_SIMILARITY_THRESHOLD
        embedding_enabled = bool(api_key)
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "chunk_size": int(chunk_size),
            "chunk_overlap": int(chunk_overlap),
            "top_k": int(top_k),
            "similarity_threshold": float(similarity_threshold),
            "embedding_enabled": embedding_enabled,
        }

    def _set_retrieval_status(self, status: Dict[str, Any], user_id: Optional[int] = None) -> None:
        safe_status = dict(status)
        self._last_retrieval_status = safe_status
        if user_id is not None:
            self._last_retrieval_status_by_user[str(user_id)] = safe_status

    def _get_retrieval_status(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        if user_id is not None:
            return self._last_retrieval_status_by_user.get(str(user_id), {"ok": True, "mode": "not_run", "message": "尚未检索"})
        return self._last_retrieval_status

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    _init_lock: asyncio.Lock = None  # type: ignore[assignment]

    async def initialize(self) -> None:
        """创建 ChromaDB PersistentClient、Embedding 模型、文本分割器。"""
        if self._initialized:
            return

        if RAGService._init_lock is None:
            RAGService._init_lock = asyncio.Lock()

        async with RAGService._init_lock:
            if self._initialized:
                return

            cfg = self._resolve_config()

            def _init():
                import chromadb
                from llama_index.core.node_parser import SentenceSplitter

                chroma_path = str(get_chromadb_dir())
                self._chroma_client = chromadb.PersistentClient(path=chroma_path)
                self._collection = self._chroma_client.get_or_create_collection(
                    name=settings.RAG_COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )

                self._embed_model = None
                if cfg["embedding_enabled"]:
                    from llama_index.embeddings.openai import OpenAIEmbedding

                    api_base = cfg["base_url"] if cfg["base_url"] != "https://api.openai.com/v1" else None
                    self._embed_model = OpenAIEmbedding(
                        model_name=cfg["model"],
                        api_key=cfg["api_key"],
                        api_base=api_base,
                    )
                self._splitter = SentenceSplitter(
                    chunk_size=cfg["chunk_size"],
                    chunk_overlap=cfg["chunk_overlap"],
                )

            await asyncio.to_thread(_init)
            self._current_api_key = cfg["api_key"]
            self._current_base_url = cfg["base_url"]
            self._current_model = cfg["model"]
            self._chunk_size = cfg["chunk_size"]
            self._chunk_overlap = cfg["chunk_overlap"]
            self._top_k = cfg["top_k"]
            self._similarity_threshold = cfg["similarity_threshold"]
            self._embedding_enabled = cfg["embedding_enabled"]
            self._initialized = True
            if self._embedding_enabled:
                logger.info("RAG 服务初始化完成")
            else:
                logger.info("RAG 服务初始化完成，但未配置 embedding API Key；后台向量索引将跳过")

    # ------------------------------------------------------------------
    # 重新初始化（热更新配置，无需重启）
    # ------------------------------------------------------------------

    async def reinitialize(
        self,
        api_key: str,
        base_url: str,
        model: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> None:
        """使用新的 embedding 配置重建模型，不影响 ChromaDB 数据。"""
        new_chunk_size = chunk_size or getattr(self, '_chunk_size', settings.RAG_CHUNK_SIZE)
        new_chunk_overlap = chunk_overlap or getattr(self, '_chunk_overlap', settings.RAG_CHUNK_OVERLAP)
        rebuild_splitter = (
            new_chunk_size != getattr(self, '_chunk_size', None)
            or new_chunk_overlap != getattr(self, '_chunk_overlap', None)
            or self._splitter is None
        )

        def _reinit():
            self._embed_model = None
            if api_key:
                from llama_index.embeddings.openai import OpenAIEmbedding

                api_base = base_url if base_url != "https://api.openai.com/v1" else None
                self._embed_model = OpenAIEmbedding(
                    model_name=model,
                    api_key=api_key,
                    api_base=api_base,
                )

            # 确保 ChromaDB client 和 collection 存在
            if self._chroma_client is None:
                import chromadb
                chroma_path = str(get_chromadb_dir())
                self._chroma_client = chromadb.PersistentClient(path=chroma_path)
            if self._collection is None:
                self._collection = self._chroma_client.get_or_create_collection(
                    name=settings.RAG_COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            if rebuild_splitter or self._splitter is None:
                from llama_index.core.node_parser import SentenceSplitter
                self._splitter = SentenceSplitter(
                    chunk_size=new_chunk_size,
                    chunk_overlap=new_chunk_overlap,
                )

        await asyncio.to_thread(_reinit)
        self._current_api_key = api_key
        self._current_base_url = base_url
        self._current_model = model
        self._chunk_size = new_chunk_size
        self._chunk_overlap = new_chunk_overlap
        self._top_k = top_k if top_k is not None else getattr(self, '_top_k', settings.RAG_TOP_K)
        self._similarity_threshold = (
            similarity_threshold if similarity_threshold is not None
            else getattr(self, '_similarity_threshold', settings.RAG_SIMILARITY_THRESHOLD)
        )
        self._embedding_enabled = bool(api_key)
        self._initialized = True
        self._set_retrieval_status(
            {"ok": bool(api_key), "mode": "not_run", "message": "RAG 配置已更新，尚未检索" if api_key else "未配置 embedding API Key，将使用普通资料上下文 fallback"}
        )
        logger.info("RAG 服务重新初始化完成 (model=%s, embedding_enabled=%s)", model, bool(api_key))

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    async def index_material(
        self,
        material_id: int,
        title: str,
        content: str,
        file_type: Optional[str] = None,
        project_ids: Optional[List[int]] = None,
        user_id: Optional[int] = None,
    ) -> int:
        """将资料内容切片并嵌入 ChromaDB，返回 chunk 数量。"""
        if not self._initialized or not content:
            return 0
        if self._embed_model is None:
            logger.info("RAG 索引跳过资料 id=%s：未配置 embedding API Key", material_id)
            return 0

        # 先删除当前用户该资料的旧 chunk，避免误删其他用户同 id/历史数据
        await self.remove_material(material_id, user_id=user_id)

        def _index():
            from llama_index.core import Document

            doc = Document(text=content, metadata={"material_id": str(material_id), "title": title, "file_type": file_type or ""})
            nodes = self._splitter.get_nodes_from_documents([doc])
            if not nodes:
                return 0

            documents = [n.get_content() for n in nodes]
            embeddings = self._embed_model.get_text_embedding_batch(documents)

            normalized_project_ids = project_ids or [0]
            for project_id in normalized_project_ids:
                ids = [f"mat{material_id}_p{project_id}_chunk{i}" for i in range(len(nodes))]
                metadatas = [
                    {
                        "material_id": str(material_id),
                        "title": title,
                        "file_type": file_type or "",
                        "chunk_index": i,
                        "project_id": str(project_id),
                        "user_id": str(user_id or 0),
                    }
                    for i in range(len(nodes))
                ]

                self._collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
            return len(nodes)

        try:
            count = await asyncio.to_thread(_index)
        except Exception as exc:
            self._last_error = str(exc)[:500]
            logger.warning("资料 '%s' (id=%d) 索引失败，已跳过向量索引: %s", title, material_id, exc)
            return 0
        self._last_error = ""
        logger.info("资料 '%s' (id=%d) 索引完成，共 %d 个 chunk", title, material_id, count)
        return count

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def remove_material(self, material_id: int, user_id: Optional[int] = None) -> None:
        """删除指定资料的 chunk；传入 user_id 时仅删除该用户的数据。"""
        if not self._initialized:
            return

        def _remove():
            filters = [{"material_id": str(material_id)}]
            if user_id is not None:
                filters.append({"user_id": str(user_id)})
            where_filter = {"$and": filters} if len(filters) > 1 else filters[0]
            try:
                self._collection.delete(where=where_filter)
            except Exception as e:
                logger.warning("删除资料 chunk 失败 (material_id=%s): %s", material_id, e)

        await asyncio.to_thread(_remove)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        material_ids: Optional[List[int]] = None,
        project_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索，返回 [{text, score, material_id, material_title}]。"""
        if not self._initialized:
            self._set_retrieval_status({"ok": False, "mode": "fallback", "message": "RAG 服务未初始化，已回退到普通资料上下文"}, user_id)
            return []

        k = top_k or getattr(self, '_top_k', settings.RAG_TOP_K)
        threshold = getattr(self, '_similarity_threshold', settings.RAG_SIMILARITY_THRESHOLD)

        if self._embed_model is None:
            logger.info("RAG 检索跳过：未配置 embedding API Key")
            self._set_retrieval_status({"ok": False, "mode": "fallback", "message": "未配置 embedding API Key，已回退到普通资料上下文"}, user_id)
            return []

        def _retrieve():
            query_embedding = self._embed_model.get_text_embedding(query)

            filters = []
            if user_id is not None:
                filters.append({"user_id": str(user_id)})
            if material_ids:
                str_ids = [str(mid) for mid in material_ids]
                if len(str_ids) == 1:
                    filters.append({"material_id": str_ids[0]})
                else:
                    filters.append({"material_id": {"$in": str_ids}})
            elif project_id is not None:
                filters.append({"project_id": str(project_id)})

            if len(filters) > 1:
                where_filter = {"$and": filters}
            elif filters:
                where_filter = filters[0]
            else:
                where_filter = None

            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            items = []
            if results and results["documents"] and results["documents"][0]:
                docs = results["documents"][0]
                metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
                dists = results["distances"][0] if results["distances"] else [1.0] * len(docs)

                for doc, meta, dist in zip(docs, metas, dists):
                    # ChromaDB cosine distance: 0 = identical, 2 = opposite
                    score = 1.0 - dist / 2.0
                    if score < threshold:
                        continue
                    items.append({
                        "text": doc,
                        "score": round(score, 4),
                        "material_id": int(meta.get("material_id", 0)),
                        "material_title": meta.get("title", ""),
                    })
            return items

        try:
            items = await asyncio.to_thread(_retrieve)
            self._last_error = ""
            if items:
                self._set_retrieval_status({"ok": True, "mode": "rag", "message": f"RAG 检索命中 {len(items)} 个片段"}, user_id)
            else:
                self._set_retrieval_status({"ok": False, "mode": "fallback", "message": "RAG 未命中相关片段，已回退到普通资料上下文"}, user_id)
            return items
        except Exception as exc:
            self._last_error = str(exc)[:500]
            self._set_retrieval_status({"ok": False, "mode": "fallback", "message": f"RAG 检索失败，已回退到普通资料上下文: {self._last_error}"}, user_id)
            logger.warning("RAG 检索失败，已返回空结果: %s", exc)
            return []

    async def retrieve_for_material(
        self,
        query: str,
        material_id: int,
        top_k: int = 8,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """针对单份资料的检索。"""
        return await self.retrieve(query, top_k=top_k, material_ids=[material_id], user_id=user_id)

    # ------------------------------------------------------------------
    # 状态 / 统计
    # ------------------------------------------------------------------

    async def get_status(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """返回 RAG 服务健康信息。

        user_id 仅用于读取该用户最近一次检索状态，避免多用户页面互相显示状态。
        """
        retrieval_status = self._get_retrieval_status(user_id)
        if not self._initialized:
            return {
                "enabled": settings.RAG_ENABLED,
                "initialized": False,
                "total_chunks": 0,
                "embedding_enabled": False,
                "last_error": self._last_error,
                "last_retrieval_status": retrieval_status,
                "fallback_active": retrieval_status.get("mode") == "fallback",
                "message": "RAG 服务未初始化，将使用普通资料上下文 fallback",
            }

        def _status():
            count = self._collection.count()
            return count

        total = await asyncio.to_thread(_status)
        retrieval_status = self._get_retrieval_status(user_id)
        return {
            "enabled": settings.RAG_ENABLED,
            "initialized": True,
            "total_chunks": total,
            "embedding_model": self._current_model or settings.RAG_EMBEDDING_MODEL,
            "chunk_size": getattr(self, '_chunk_size', settings.RAG_CHUNK_SIZE),
            "chunk_overlap": getattr(self, '_chunk_overlap', settings.RAG_CHUNK_OVERLAP),
            "top_k": getattr(self, '_top_k', settings.RAG_TOP_K),
            "similarity_threshold": getattr(self, '_similarity_threshold', settings.RAG_SIMILARITY_THRESHOLD),
            "embedding_enabled": self._embed_model is not None,
            "last_error": self._last_error,
            "last_retrieval_status": retrieval_status,
            "fallback_active": retrieval_status.get("mode") == "fallback" or self._embed_model is None,
            "message": (
                "未配置 embedding API Key，将使用普通资料上下文 fallback"
                if self._embed_model is None
                else "RAG 服务运行正常" if not self._last_error
                else f"RAG embedding 最近一次调用失败: {self._last_error}"
            ),
        }

    async def get_material_chunk_count(self, material_id: int) -> int:
        """返回某份资料的 chunk 数。"""
        if not self._initialized:
            return 0

        def _count():
            try:
                results = self._collection.get(
                    where={"material_id": str(material_id)},
                    include=[],
                )
                return len(results["ids"]) if results and results["ids"] else 0
            except Exception as e:
                logger.warning("获取资料 chunk 数量失败 (material_id=%s): %s", material_id, e)
                return 0

        return await asyncio.to_thread(_count)


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_rag_instance: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """获取 RAG 服务单例。"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGService()
    return _rag_instance
