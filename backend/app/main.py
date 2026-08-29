"""FastAPI 应用入口"""
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import init_db, close_db, _is_sqlite
from app.middleware.security import RateLimitMiddleware, RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.frontend_static import register_frontend_static
from app.utils.paths import get_project_root, get_uploads_dir, ensure_data_dirs


def create_projection_outbox_worker(session_factory):
    """Build the application-local consumer from environment-backed settings."""
    from app.services.projection_outbox_worker import (
        ProjectionOutboxWorker,
        default_worker_id,
    )

    return ProjectionOutboxWorker(
        session_factory,
        worker_id=default_worker_id(settings.OUTBOX_WORKER_ID),
        batch_size=settings.OUTBOX_WORKER_BATCH_SIZE,
        max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
        retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        poll_interval_seconds=settings.OUTBOX_WORKER_POLL_INTERVAL_SECONDS,
        heartbeat_enabled=True,
        heartbeat_interval_seconds=settings.OUTBOX_WORKER_HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_ttl_seconds=settings.OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS,
        alert_backlog_count_threshold=settings.OUTBOX_ALERT_BACKLOG_COUNT_THRESHOLD,
        alert_backlog_age_seconds=settings.OUTBOX_ALERT_BACKLOG_AGE_SECONDS,
        alert_terminal_failure_threshold=settings.OUTBOX_ALERT_TERMINAL_FAILURE_THRESHOLD,
        alert_stale_processing_threshold=settings.OUTBOX_ALERT_STALE_PROCESSING_THRESHOLD,
    )


def _outbox_worker_allowed() -> bool:
    """SQLite keeps request-time consumption as its single-consumer path."""
    return bool(settings.OUTBOX_WORKER_ENABLED and not _is_sqlite())


def _agent_runtime_worker_allowed() -> bool:
    """The server scheduler is a PostgreSQL production capability.

    Desktop/SQLite retains request-time Coach evaluation, avoiding a hidden
    background writer in the local single-consumer mode.
    """
    return bool(settings.AGENT_RUNTIME_SCHEDULER_ENABLED and not _is_sqlite())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    ensure_data_dirs()
    logger.info("数据库初始化完成")

    from app.database import async_session_maker

    outbox_worker = None
    agent_runtime_worker = None
    app.state.projection_outbox_worker = None
    app.state.agent_runtime_worker = None

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
            from app.models.retrieval import RetrievalProjection
            from app.services.retrieval_projection_service import RetrievalProjectionService
            from sqlalchemy import select, func

            rag = get_rag_service()
            await rag.initialize()

            # Recover missing/stale manifests and interrupted deletes without
            # making startup depend on embeddings or a healthy vector store.
            status = await rag.get_status()
            async with async_session_maker() as check_session:
                material_count = int(
                    await check_session.scalar(
                        select(func.count()).select_from(Material).where(Material.content.is_not(None))
                    )
                    or 0
                )
                active_projection_count = int(
                    await check_session.scalar(
                        select(func.count()).select_from(RetrievalProjection).where(
                            RetrievalProjection.source_type == "material",
                            RetrievalProjection.status.in_(("ready", "degraded")),
                        )
                    )
                    or 0
                )
                recovery_count = int(
                    await check_session.scalar(
                        select(func.count()).select_from(RetrievalProjection).where(
                            RetrievalProjection.status.in_(("pending", "indexing", "failed", "deleting"))
                        )
                    )
                    or 0
                )
            if (
                (status.get("total_chunks", 0) == 0 and material_count > 0)
                or active_projection_count < material_count
                or recovery_count > 0
            ):
                import asyncio

                async def _bg_index():
                    try:
                        async with async_session_maker() as session:
                            service = RetrievalProjectionService(session, rag=rag)
                            delete_result = await session.execute(
                                select(RetrievalProjection).where(
                                    RetrievalProjection.last_operation == "forget",
                                    RetrievalProjection.status.in_(("failed", "deleting")),
                                )
                            )
                            pending_deletes = [
                                (int(row.user_id), int(row.source_id))
                                for row in delete_result.scalars().all()
                            ]
                            for owner_id, source_id in pending_deletes:
                                await service.forget(owner_id, source_id)

                            total = material_count
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
                                    projection = await service.ingest(
                                        mat,
                                        user_id=getattr(mat, "user_id", None),
                                        operation="rebuild",
                                    )
                                    if projection.get("status") == "ready":
                                        indexed += 1
                                    elif projection.get("status") == "failed":
                                        failed += 1
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

    try:
        # Start the PostgreSQL worker only after startup maintenance and RAG
        # initialization have completed. The surrounding finally still closes
        # the DB if setup fails after this point.
        if _outbox_worker_allowed():
            outbox_worker = create_projection_outbox_worker(async_session_maker)
            app.state.projection_outbox_worker = outbox_worker
            outbox_worker.start()
            logger.info("projection outbox worker started worker_id=%s", outbox_worker.worker_id)
        if _agent_runtime_worker_allowed():
            from app.services.agent_runtime_worker import AgentRuntimeWorker

            agent_runtime_worker = AgentRuntimeWorker(
                async_session_maker,
                poll_interval_seconds=settings.AGENT_RUNTIME_POLL_INTERVAL_SECONDS,
                batch_size=settings.AGENT_RUNTIME_BATCH_SIZE,
            )
            app.state.agent_runtime_worker = agent_runtime_worker
            agent_runtime_worker.start()
            logger.info("agent runtime worker started")
        yield
    finally:
        if agent_runtime_worker is not None:
            try:
                await agent_runtime_worker.stop()
                logger.info("agent runtime worker stopped")
            except Exception as exc:
                logger.warning("agent runtime worker shutdown failed: %s", exc, exc_info=settings.DEBUG)
        if outbox_worker is not None:
            try:
                await outbox_worker.stop()
                logger.info("projection outbox worker stopped worker_id=%s", outbox_worker.worker_id)
            except Exception as exc:
                logger.warning("projection outbox worker shutdown failed: %s", exc, exc_info=settings.DEBUG)
        # 关闭时清理资源
        await close_db()
        logger.info("应用关闭，数据库连接已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Mnemox API",
    description="AI 驱动的个性化学习教练 API",
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
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


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
        "message": "Mnemox API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Return a cheap public liveness check without queue telemetry."""
    worker = getattr(app.state, "projection_outbox_worker", None)
    worker_enabled = _outbox_worker_allowed()
    worker_running = bool(worker is not None and worker.snapshot().get("running"))
    runtime_worker = getattr(app.state, "agent_runtime_worker", None)
    runtime_enabled = _agent_runtime_worker_allowed()
    runtime_running = bool(runtime_worker is not None and runtime_worker.snapshot().get("running"))
    runtime_snapshot = runtime_worker.health_snapshot() if runtime_worker is not None else {}
    return {
        "status": "ok" if (not worker_enabled or worker_running) and (not runtime_enabled or runtime_running) else "degraded",
        "projection_outbox_worker": {
            "enabled": worker_enabled,
            "running": worker_running,
            **(
                {"disabled_reason": "sqlite_single_consumer"}
                if worker is None and _is_sqlite() and settings.OUTBOX_WORKER_ENABLED
                else {}
            ),
        },
        "agent_runtime_worker": {
            "enabled": runtime_enabled,
            "running": runtime_running,
            **(
                {
                    key: runtime_snapshot.get(key)
                    for key in ("started_at", "last_run_at", "last_success_at", "last_error_at", "cycles", "nudges_created", "failed_users", "poll_interval_seconds")
                    if key in runtime_snapshot
                }
            ),
            **({"disabled_reason": "sqlite_request_time_coach"} if runtime_worker is None and _is_sqlite() else {}),
        },
    }


# 引入路由
from app.routers import materials, pomodoro, rag, plans, ai_settings, chat, conversations, chat_projects, wrong_questions, review, goals, study_sessions, memory, notes, learning, images, obsidian_import, auth, motivation, profile, prompt_templates, analytics, interventions, anki, system, agent, agent_memory, coach, concepts, learner_model, outbox_operations

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
app.include_router(agent_memory.router, prefix="/api/agent/memory", tags=["Agent 记忆"])
app.include_router(coach.router, prefix="/api/coach", tags=["自主 Coach"])
app.include_router(profile.router, prefix="/api/profile", tags=["用户画像"])
app.include_router(prompt_templates.router, prefix="/api/prompts", tags=["Prompt 模板"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["数据分析"])
app.include_router(anki.router, prefix="/api/anki", tags=["Anki记忆卡"])
app.include_router(system.router, prefix="/api/system", tags=["系统"])
app.include_router(concepts.router, prefix="/api/concepts", tags=["概念图谱"])
app.include_router(learner_model.router, prefix="/api/learner-model", tags=["学习者模型"])
app.include_router(outbox_operations.router, prefix="/internal/outbox")

ensure_data_dirs()


async def _is_upload_owned_by_user(session, user_id: int, relative_path) -> bool:
    """上传文件归属校验：图片按用户目录隔离，资料文件绑定 Material 归属。

    - images/{user_id}/...：目录名必须等于当前用户 id。
    - images/{filename}：早期 Obsidian 附件无归属元数据，保持旧行为（仅登录可见）。
    - 其余文件：必须能在当前用户的 Material.file_path 中按文件名匹配到。
    """
    from sqlalchemy import select

    from app.models.material import Material

    parts = relative_path.parts
    if parts and parts[0] == "images":
        if len(parts) >= 3:
            return parts[1] == str(user_id)
        return True

    filename = relative_path.name
    if not filename:
        return False
    result = await session.execute(
        select(Material.id)
        .where(
            Material.user_id == user_id,
            Material.file_path.ilike(f"%{filename}"),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


@app.get("/api/uploads/{file_path:path}")
async def get_uploaded_file(file_path: str, request: Request):
    """Serve uploaded files only to their owner (authenticated + ownership bound)."""
    from urllib.parse import unquote

    from fastapi import HTTPException, status

    from app.auth import get_user_from_token
    from app.database import async_session_maker

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME, "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    uploads_root = get_uploads_dir().resolve()
    target = (uploads_root / unquote(file_path)).resolve()
    try:
        relative = target.relative_to(uploads_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    async with async_session_maker() as session:
        user = await get_user_from_token(token, session)
        owned = await _is_upload_owned_by_user(session, int(user.id), relative)

    if not owned:
        # 与不存在同样返回 404，避免泄露他人文件是否存在
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(target, headers={"Cache-Control": "private, no-store"})


def _resolve_frontend_dist_dir():
    configured = (settings.FRONTEND_DIST_DIR or "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (get_project_root() / configured_path).resolve()
    return (get_project_root() / "frontend" / "dist").resolve()


if settings.SERVE_FRONTEND:
    register_frontend_static(app, _resolve_frontend_dist_dir())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
