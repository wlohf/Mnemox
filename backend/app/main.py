"""FastAPI 应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    print("✅ 数据库初始化完成")
    yield
    # 关闭时清理资源
    await close_db()
    print("👋 应用关闭，数据库连接已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="学习助手 API",
    description="基于认知科学学习方法的智能学习助手系统",
    version="1.0.0",
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


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "学习助手 API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


# 引入路由
from app.routers import materials

app.include_router(materials.router, prefix="/api/materials", tags=["资料管理"])
# TODO: 引入其他路由
# from app.routers import goals, study, review, pomodoro
# app.include_router(goals.router, prefix="/api/goals", tags=["学习目标"])
# app.include_router(study.router, prefix="/api/study", tags=["学习会话"])
# app.include_router(review.router, prefix="/api/review", tags=["复习"])
# app.include_router(pomodoro.router, prefix="/api/pomodoro", tags=["番茄钟"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
