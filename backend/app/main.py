"""FastAPI 应用入口"""
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import init_db, close_db
from app.utils.paths import get_uploads_dir, ensure_data_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    ensure_data_dirs()
    logger.info("数据库初始化完成")

    from app.database import async_session_maker

    # Decay stale episodic memories
    try:
        from app.services.memory_service import decay_episodic_memories
        async with async_session_maker() as session:
            decayed = await decay_episodic_memories(session)
            if decayed > 0:
                await session.commit()
                logger.info("已衰减 %d 条过期 episodic 记忆", decayed)
    except Exception as e:
        logger.warning("记忆衰减失败: %s", e)

    # 初始化 RAG 服务
    if settings.RAG_ENABLED:
        try:
            from app.ai.rag_service import get_rag_service
            from app.models.material import Material
            from sqlalchemy import select, func

            rag = get_rag_service()
            await rag.initialize()

            # 自动索引：ChromaDB 为空时，后台异步索引所有已有资料（不阻塞启动）
            status = await rag.get_status()
            if status.get("total_chunks", 0) == 0:
                import asyncio

                async def _bg_index():
                    try:
                        async with async_session_maker() as session:
                            count_result = await session.execute(
                                select(func.count()).select_from(Material).where(Material.content.is_not(None))
                            )
                            total = count_result.scalar() or 0
                            if total == 0:
                                return
                            logger.info("RAG 后台索引开始：发现 %d 份已有资料需要索引", total)
                            result = await session.execute(
                                select(Material).where(Material.content.is_not(None))
                            )
                            indexed = 0
                            failed = 0
                            for mat in result.scalars().all():
                                try:
                                    await rag.index_material(
                                        material_id=mat.id,
                                        title=mat.title,
                                        content=mat.content,
                                        file_type=mat.file_type,
                                        user_id=getattr(mat, "user_id", None),
                                    )
                                    indexed += 1
                                except Exception as item_error:
                                    failed += 1
                                    logger.warning(
                                        "RAG 后台索引跳过资料 id=%s title=%r：%s",
                                        mat.id,
                                        mat.title,
                                        item_error,
                                        exc_info=settings.DEBUG,
                                    )
                            if failed:
                                logger.warning("RAG 后台索引完成：成功 %d 份，失败 %d 份", indexed, failed)
                            else:
                                logger.info("RAG 后台索引完成：成功索引 %d 份资料", indexed)
                    except Exception as e:
                        logger.warning("RAG 后台索引任务异常（不影响主流程）: %s", e, exc_info=settings.DEBUG)

                asyncio.create_task(_bg_index())
        except Exception as e:
            logger.warning("RAG 服务初始化失败（不影响主流程）: %s", e)

    yield
    # 关闭时清理资源
    await close_db()
    logger.info("应用关闭，数据库连接已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="学习助手 API",
    description="基于认知科学学习方法的智能学习助手系统",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic 422 验证错误 → 用户友好的中文提示
_FIELD_LABELS = {
    "username": "用户名",
    "email": "邮箱",
    "password": "密码",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = err.get("loc", [])
        field = loc[-1] if loc else ""
        label = _FIELD_LABELS.get(field, field)
        msg = err.get("msg", "")
        # Translate common Pydantic messages
        if "missing" in msg.lower():
            msg = "此字段为必填项"
        elif "not a valid email" in msg.lower() or "email" in msg.lower():
            msg = "请输入有效的邮箱地址"
        elif "at least" in msg.lower():
            msg = msg.replace("ensure this value has at least", "长度不能少于").replace("characters", "个字符")
        errors.append(f"{label}：{msg}" if label else msg)
    detail = "；".join(errors) if errors else "请求参数校验失败"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "学习助手 API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


# 引入路由
from app.routers import materials, pomodoro, rag, plans, ai_settings, chat, conversations, chat_projects, wrong_questions, review, goals, study_sessions, memory, notes, learning, images, obsidian_import, auth, motivation, profile, prompt_templates, analytics, interventions, anki, system, agent

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])

app.include_router(materials.router, prefix="/api/materials", tags=["资料管理"])
app.include_router(pomodoro.router, prefix="/api/pomodoro", tags=["番茄钟"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG 知识库"])
app.include_router(plans.router, prefix="/api/plans", tags=["日历/计划"])
app.include_router(ai_settings.router, prefix="/api/ai-settings", tags=["AI 设置"])
app.include_router(chat.router, prefix="/api/chat", tags=["AI 对话"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["对话管理"])
app.include_router(chat_projects.router, prefix="/api/chat-projects", tags=["对话项目"])
app.include_router(wrong_questions.router, prefix="/api/wrong-questions", tags=["错题本/复习"])
app.include_router(review.router, prefix="/api/review", tags=["复习计划"])
app.include_router(goals.router, prefix="/api/goals", tags=["目标/任务"])
app.include_router(study_sessions.router, prefix="/api/study-sessions", tags=["学习会话"])
app.include_router(memory.router, prefix="/api/memory", tags=["AI记忆"])
app.include_router(notes.router, prefix="/api/notes", tags=["笔记"])
app.include_router(learning.router, prefix="/api/learning", tags=["学习驾驶舱"])
app.include_router(images.router, prefix="/api/images", tags=["图片上传"])
app.include_router(obsidian_import.router, prefix="/api/obsidian", tags=["Obsidian 导入"])
app.include_router(motivation.router, prefix="/api/motivation", tags=["今日激励"])
app.include_router(interventions.router, prefix="/api/interventions", tags=["主动干预"])
app.include_router(agent.router, prefix="/api/agent", tags=["自主学习 Agent"])
app.include_router(profile.router, prefix="/api/profile", tags=["用户画像"])
app.include_router(prompt_templates.router, prefix="/api/prompts", tags=["Prompt 模板"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["数据分析"])
app.include_router(anki.router, prefix="/api/anki", tags=["Anki记忆卡"])
app.include_router(system.router, prefix="/api/system", tags=["系统"])

# Mount static files for uploaded images (must be after all include_router calls).
# StaticFiles checks the directory at import time, so create it for fresh clones too.
ensure_data_dirs()
app.mount("/api/uploads", StaticFiles(directory=str(get_uploads_dir())), name="uploads")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
