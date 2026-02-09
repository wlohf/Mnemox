"""AnythingLLM 集成诊断路由（用于确认是否“连上”）。"""

from fastapi import APIRouter

from app.config import settings
from app.ai.anythingllm_provider import get_anythingllm_provider


router = APIRouter()


@router.get("/health")
async def rag_health():
    """
    检查 AnythingLLM 服务、collector 服务、workspace 是否可用。

    返回的数据用于前端展示连接状态与排错。
    """

    if not settings.ANYTHINGLLM_ENABLED:
        return {
            "enabled": False,
            "base_url": settings.ANYTHINGLLM_BASE_URL,
            "collector_url": settings.ANYTHINGLLM_COLLECTOR_URL,
            "workspace": settings.ANYTHINGLLM_WORKSPACE,
            "anythingllm_online": False,
            "collector_online": False,
            "workspace_ok": False,
            "message": "ANYTHINGLLM_ENABLED=false（当前未启用）",
        }

    provider = get_anythingllm_provider()
    anythingllm_online = await provider.check_online()
    collector_online = await provider.check_collector_online()

    workspace_ok = False
    workspace = None
    workspace_error = None
    if anythingllm_online:
        try:
            workspace = await provider.ensure_workspace(settings.ANYTHINGLLM_WORKSPACE)
            workspace_ok = bool(workspace)
        except Exception as e:
            workspace_error = str(e)

    return {
        "enabled": True,
        "base_url": settings.ANYTHINGLLM_BASE_URL,
        "collector_url": settings.ANYTHINGLLM_COLLECTOR_URL,
        "workspace": settings.ANYTHINGLLM_WORKSPACE,
        "anythingllm_online": anythingllm_online,
        "collector_online": collector_online,
        "workspace_ok": workspace_ok,
        "workspace_info": workspace,
        "workspace_error": workspace_error,
    }

