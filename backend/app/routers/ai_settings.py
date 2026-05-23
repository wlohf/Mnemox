"""AI 提供商设置路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
import re
import json
import httpx

from app.database import get_db
from app.models.ai_settings import AIProviderSetting
from app.models.ai_routing import AIRoutingSetting
from app.config import settings
from app.auth import get_current_user
from app.models.user import User
from app.utils.secret_crypto import decrypt_secret, encrypt_secret

router = APIRouter()


# ---- Pydantic schemas ----

class ProviderOut(BaseModel):
    provider_name: str
    display_name: str
    api_key_masked: str
    base_url: str
    model: str
    available_models: List[str] = []
    is_active: bool
    enabled: bool


class ProviderUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    available_models: Optional[List[str]] = None
    enabled: Optional[bool] = None


class ProviderCreate(BaseModel):
    display_name: str
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    available_models: Optional[List[str]] = None
    enabled: Optional[bool] = True


class SetActiveRequest(BaseModel):
    provider_name: str


class TestResult(BaseModel):
    success: bool
    message: str
    capability: Optional[str] = None
    provider_name: Optional[str] = None
    model: Optional[str] = None


class ProviderConnectionRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class RoutingOut(BaseModel):
    scenario: str
    label: str
    provider_name: Optional[str] = None
    model: Optional[str] = None


class RoutingUpdate(BaseModel):
    provider_name: Optional[str] = None
    model: Optional[str] = None


class ModelSearchRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_hint: Optional[str] = None


class ModelSearchResult(BaseModel):
    provider_name: str
    models: List[str]


# ---- Helpers ----

def mask_key(key: str) -> str:
    """将 API key 脱敏显示"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def _parse_available_models(raw: str | None, fallback_model: str = "") -> List[str]:
    models: List[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                models = [str(m).strip() for m in parsed if str(m).strip()]
        except Exception:
            models = []
    if fallback_model and fallback_model not in models:
        models.insert(0, fallback_model)
    return list(dict.fromkeys(models))


def _dump_available_models(models: List[str], fallback_model: str = "") -> str:
    cleaned = [str(m).strip() for m in models if str(m).strip()]
    if fallback_model and fallback_model not in cleaned:
        cleaned.insert(0, fallback_model)
    return json.dumps(list(dict.fromkeys(cleaned)), ensure_ascii=False)


def _get_effective_values(row: AIProviderSetting) -> tuple[str, str, str]:
    env_attrs = _ENV_MAP.get(row.provider_name, (None, None, None))
    stored_key = decrypt_secret(row.api_key)
    # API keys are user-owned. Do not fall back to .env here; otherwise a key
    # cleared in the UI can reappear as "configured" and still be used by tests.
    model = row.model or ""
    base_url = row.base_url or (getattr(settings, env_attrs[2], "") if env_attrs[2] else "")
    return stored_key, base_url, model


def _merge_available_models(
    current_raw: str | None,
    discovered: List[str],
    fallback_model: str = "",
) -> List[str]:
    merged = _parse_available_models(current_raw, fallback_model)
    for model in discovered:
        model = str(model).strip()
        if model and model not in merged:
            merged.append(model)
    return merged


def _connection_value(
    saved_value: str,
    submitted_value: Optional[str],
    *,
    use_saved_for_blank: bool = True,
) -> str:
    if submitted_value is None:
        return saved_value
    submitted = submitted_value.strip()
    if not use_saved_for_blank:
        return submitted
    return submitted or saved_value


def _fallback_models_for_catalog_error(exc: Exception, model_hint: str) -> Optional[List[str]]:
    """Return the configured model when a proxy lacks a model catalog endpoint."""
    hint = (model_hint or "").strip()
    if not hint:
        return None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (404, 405, 501):
            return [hint]
    return None


def _normalize_provider_name(raw_name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw_name.strip().lower())
    name = re.sub(r"-+", "-", name).strip("-")
    return name


async def _unique_provider_name(db: AsyncSession, user_id: int, base_name: str) -> str:
    name = (base_name or "custom")[:50]
    if not name:
        name = "custom"

    result = await db.execute(
        select(AIProviderSetting.provider_name).where(AIProviderSetting.user_id == user_id)
    )
    existing = {row[0] for row in result.all()}

    if name not in existing:
        return name

    suffix = 2
    while True:
        candidate = f"{name[:46]}-{suffix}" if len(name) > 46 else f"{name}-{suffix}"
        if candidate not in existing:
            return candidate
        suffix += 1


def _to_out(row: AIProviderSetting) -> ProviderOut:
    api_key, base_url, model = _get_effective_values(row)
    available_models = _parse_available_models(row.available_models, model)
    return ProviderOut(
        provider_name=row.provider_name,
        display_name=row.display_name,
        api_key_masked=mask_key(api_key or ""),
        base_url=base_url or "",
        model=model or "",
        available_models=available_models,
        is_active=row.is_active,
        enabled=row.enabled,
    )


async def _fetch_model_catalog(
    provider_name: str,
    api_key: str,
    base_url: str,
    model_hint: str = "",
) -> List[str]:
    provider_kind = provider_name.lower()
    if provider_kind.startswith(("anthropic-", "claude-")) or provider_kind == "claude":
        provider_kind = "claude"
    elif provider_kind.startswith("gemini-") or provider_kind == "gemini":
        provider_kind = "gemini"
    else:
        provider_kind = "openai"

    timeout = httpx.Timeout(12.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if provider_kind == "claude":
                root = (base_url or "https://api.anthropic.com").rstrip("/")
                if root.endswith("/v1/messages"):
                    root = root[: -len("/messages")]
                url = f"{root}/v1/models" if not root.endswith("/v1") else f"{root}/models"
                res = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                res.raise_for_status()
                data = res.json()
                raw_items = data.get("data") or data.get("models") or []
                models = [
                    str(item.get("id") or item.get("name") or "").strip()
                    for item in raw_items
                    if isinstance(item, dict)
                ]
                return [m for m in models if m]

            if provider_kind == "gemini":
                root = (base_url or "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")
                url = root if root.endswith("/models") else f"{root}/models"
                res = await client.get(url, params={"key": api_key})
                res.raise_for_status()
                data = res.json()
                raw_items = data.get("models") or []
                models = []
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if name.startswith("models/"):
                        name = name.split("/", 1)[1]
                    supported = item.get("supportedGenerationMethods") or []
                    if not supported or "generateContent" in supported:
                        models.append(name)
                return [m for m in models if m]

            root = (base_url or "https://api.openai.com/v1").rstrip("/")
            if root.endswith("/chat/completions"):
                root = root[: -len("/chat/completions")]
            url = root if root.endswith("/models") else f"{root}/models"
            res = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            res.raise_for_status()
            data = res.json()
            raw_items = data.get("data") or data.get("models") or []
            models = [
                str(item.get("id") or item.get("name") or "").strip()
                for item in raw_items
                if isinstance(item, dict)
            ]
            if not models and model_hint:
                models = [model_hint]
            return [m for m in models if m]
    except Exception as exc:
        fallback = _fallback_models_for_catalog_error(exc, model_hint)
        if fallback:
            return fallback
        raise


# ---- Default seed data ----

DEFAULT_PROVIDERS = [
    {
        "provider_name": "deepseek",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    {
        "provider_name": "openai",
        "display_name": "ChatGPT / OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4",
    },
    {
        "provider_name": "claude",
        "display_name": "Claude",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
    },
    {
        "provider_name": "gemini",
        "display_name": "Gemini",
        "base_url": "",
        "model": "gemini-1.5-flash",
    },
    {
        "provider_name": "qwen",
        "display_name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
    },
]

DEFAULT_PROVIDER_NAMES = {p["provider_name"] for p in DEFAULT_PROVIDERS}

ROUTING_SCENARIOS = {
    "chat_main": "主对话",
    "wrong_detect": "错题检测",
    "memory_extract": "记忆提炼",
    "reflection": "学习反思",
    "material_analyze": "资料分析",
    "output_evaluate": "输出评估",
    "review": "复习评估",
    "note_metadata": "笔记元信息",
    "motivation": "今日激励",
}

# Map provider_name -> (env_key_attr, env_model_attr, env_base_url_attr)
_ENV_MAP = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"),
    "claude": ("CLAUDE_API_KEY", "CLAUDE_MODEL", "CLAUDE_BASE_URL"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", None),
    "qwen": ("QWEN_API_KEY", "QWEN_MODEL", "QWEN_BASE_URL"),
}


async def seed_user_providers(db: AsyncSession, user_id: int):
    """为新用户插入默认提供商行，并从 .env 迁移已有配置"""
    result = await db.execute(
        select(AIProviderSetting).where(AIProviderSetting.user_id == user_id)
    )
    existing = {row.provider_name for row in result.scalars().all()}

    for prov in DEFAULT_PROVIDERS:
        if prov["provider_name"] in existing:
            continue

        # 从 .env 迁移已有值
        env_attrs = _ENV_MAP.get(prov["provider_name"], (None, None, None))
        api_key = getattr(settings, env_attrs[0], "") if env_attrs[0] else ""
        model = getattr(settings, env_attrs[1], prov["model"]) if env_attrs[1] else prov["model"]
        base_url = getattr(settings, env_attrs[2], prov["base_url"]) if env_attrs[2] else prov["base_url"]

        # 如果 .env 中配置了 DEFAULT_AI_PROVIDER，标记为 active
        is_active = (prov["provider_name"] == settings.DEFAULT_AI_PROVIDER)

        row = AIProviderSetting(
            user_id=user_id,
            provider_name=prov["provider_name"],
            display_name=prov["display_name"],
            api_key=encrypt_secret(api_key) if api_key else "",
            base_url=base_url or prov["base_url"],
            model=model or prov["model"],
            available_models=_dump_available_models([model or prov["model"]], model or prov["model"]),
            is_active=is_active,
            enabled=True,
        )
        db.add(row)

    await db.commit()

    # 确保场景路由配置存在（默认跟随当前激活提供商）
    route_result = await db.execute(
        select(AIRoutingSetting).where(AIRoutingSetting.user_id == user_id)
    )
    existing_routes = {r.scenario for r in route_result.scalars().all()}
    for scenario in ROUTING_SCENARIOS.keys():
        if scenario in existing_routes:
            continue
        db.add(AIRoutingSetting(user_id=user_id, scenario=scenario, provider_name=None))
    await db.commit()
    print(f"[OK] AI 提供商默认配置已就绪 (user_id={user_id})")


# Keep backward-compatible name for startup seeding
async def seed_default_providers(db: AsyncSession):
    """Legacy startup seed - now a no-op since providers are seeded per-user."""
    pass


# ---- Endpoints ----

@router.get("/", response_model=List[ProviderOut])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有 AI 提供商（API key 脱敏）"""
    result = await db.execute(
        select(AIProviderSetting)
        .where(AIProviderSetting.user_id == current_user.id)
        .order_by(AIProviderSetting.id)
    )
    rows = result.scalars().all()
    return [_to_out(r) for r in rows]


@router.post("/", response_model=ProviderOut)
async def create_provider(
    body: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建自定义 AI 提供商（支持 OpenAI/Anthropic/Gemini）"""
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name 不能为空")

    provider_type = (body.provider_type or "openai").strip().lower()
    if provider_type == "anthropic":
        provider_type = "anthropic"
    elif provider_type not in ("openai", "claude", "gemini", "deepseek", "qwen"):
        provider_type = "openai"

    raw_name = (body.provider_name or display_name).strip()
    base_name = _normalize_provider_name(raw_name)
    if provider_type:
        base_name = f"{provider_type}-{base_name}" if base_name else provider_type
    provider_name = await _unique_provider_name(db, current_user.id, base_name)

    row = AIProviderSetting(
        user_id=current_user.id,
        provider_name=provider_name,
        display_name=display_name,
        api_key=encrypt_secret(body.api_key) if body.api_key else "",
        base_url=body.base_url or "",
        model=body.model or "",
        available_models=_dump_available_models(body.available_models or [], body.model or ""),
        is_active=False,
        enabled=body.enabled if body.enabled is not None else True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.put("/{provider_name}", response_model=ProviderOut)
async def update_provider(
    provider_name: str,
    body: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新提供商设置（部分更新，仅非 None 字段）"""
    result = await db.execute(
        select(AIProviderSetting).where(
            AIProviderSetting.provider_name == provider_name,
            AIProviderSetting.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"提供商 {provider_name} 不存在")

    if body.api_key is not None:
        row.api_key = encrypt_secret(body.api_key) if body.api_key else ""
    if body.base_url is not None:
        row.base_url = body.base_url
    if body.model is not None:
        row.model = body.model
        if row.available_models:
            row.available_models = _dump_available_models(
                _parse_available_models(row.available_models),
                body.model,
            )
    if body.available_models is not None:
        row.available_models = _dump_available_models(body.available_models, row.model or "")
    if body.enabled is not None:
        row.enabled = body.enabled

    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.post("/{provider_name}/models/search", response_model=ModelSearchResult)
async def search_provider_models(
    provider_name: str,
    body: ModelSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """使用当前或临时 API 配置查询供应商可用模型。"""
    result = await db.execute(
        select(AIProviderSetting).where(
            AIProviderSetting.provider_name == provider_name,
            AIProviderSetting.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"提供商 {provider_name} 不存在")

    saved_key, saved_base_url, saved_model = _get_effective_values(row)
    api_key = _connection_value(saved_key, body.api_key, use_saved_for_blank=False)
    base_url = _connection_value(saved_base_url, body.base_url)
    model_hint = _connection_value(saved_model, body.model_hint)

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 未配置，无法搜索模型")

    try:
        discovered = await _fetch_model_catalog(row.provider_name, api_key, base_url, model_hint)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"搜索模型失败：{str(e)}")

    models = _merge_available_models(row.available_models, discovered, model_hint)
    return ModelSearchResult(provider_name=row.provider_name, models=models)


@router.delete("/{provider_name}")
async def delete_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除自定义 AI 提供商"""
    if provider_name in DEFAULT_PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail="内置提供商不可删除")

    result = await db.execute(
        select(AIProviderSetting).where(
            AIProviderSetting.provider_name == provider_name,
            AIProviderSetting.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"提供商 {provider_name} 不存在")

    if row.is_active:
        other_result = await db.execute(
            select(AIProviderSetting)
            .where(
                AIProviderSetting.user_id == current_user.id,
                AIProviderSetting.provider_name != provider_name,
            )
            .order_by(AIProviderSetting.id)
        )
        other = other_result.scalar_one_or_none()
        if not other:
            raise HTTPException(status_code=400, detail="不能删除唯一的激活提供商")
        other.is_active = True

    routing_result = await db.execute(
        select(AIRoutingSetting).where(
            AIRoutingSetting.user_id == current_user.id,
            AIRoutingSetting.provider_name == provider_name,
        )
    )
    for routing in routing_result.scalars().all():
        routing.provider_name = None

    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/active", response_model=ProviderOut)
async def set_active_provider(
    body: SetActiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设置当前激活的提供商（单选）"""
    # 验证目标存在
    result = await db.execute(
        select(AIProviderSetting).where(
            AIProviderSetting.provider_name == body.provider_name,
            AIProviderSetting.user_id == current_user.id,
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail=f"提供商 {body.provider_name} 不存在")

    # 取消所有 active（仅当前用户的）
    all_result = await db.execute(
        select(AIProviderSetting).where(AIProviderSetting.user_id == current_user.id)
    )
    for row in all_result.scalars().all():
        row.is_active = (row.provider_name == body.provider_name)

    await db.commit()
    await db.refresh(target)
    return _to_out(target)


@router.post("/test/{provider_name}", response_model=TestResult)
async def test_provider(
    provider_name: str,
    body: Optional[ProviderConnectionRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试提供商连通性"""
    result = await db.execute(
        select(AIProviderSetting).where(
            AIProviderSetting.provider_name == provider_name,
            AIProviderSetting.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"提供商 {provider_name} 不存在")

    saved_key, saved_base_url, saved_model = _get_effective_values(row)
    api_key = _connection_value(
        saved_key,
        body.api_key if body else None,
        use_saved_for_blank=False,
    )
    base_url = _connection_value(saved_base_url, body.base_url if body else None)
    model = _connection_value(saved_model, body.model if body else None)

    if not api_key:
        return TestResult(success=False, message="API Key 未配置", capability="chat", provider_name=row.provider_name, model=model)

    try:
        from app.ai.factory import AIProviderFactory
        provider = AIProviderFactory.create_provider_from_settings(
            provider_name=row.provider_name,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        response = await provider.chat(
            messages=[{"role": "user", "content": "Hi, reply with 'ok' only."}],
            temperature=0.0,
        )
        if response:
            return TestResult(success=True, message=f"Chat 连接成功！模型回复：{response[:100]}", capability="chat", provider_name=row.provider_name, model=model)
        return TestResult(success=False, message="Chat 模型返回空响应", capability="chat", provider_name=row.provider_name, model=model)
    except Exception as e:
        return TestResult(success=False, message=f"Chat 连接失败：{str(e)}", capability="chat", provider_name=row.provider_name, model=model)


@router.get("/routing", response_model=List[RoutingOut])
async def list_routing(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读取各场景 AI 路由（provider_name 为空表示跟随全局激活）。"""
    result = await db.execute(
        select(AIRoutingSetting)
        .where(AIRoutingSetting.user_id == current_user.id)
        .order_by(AIRoutingSetting.id)
    )
    rows = {r.scenario: r for r in result.scalars().all()}

    out: List[RoutingOut] = []
    for scenario, label in ROUTING_SCENARIOS.items():
        row = rows.get(scenario)
        out.append(
            RoutingOut(
                scenario=scenario,
                label=label,
                provider_name=(row.provider_name if row else None),
                model=(row.model if row else None),
            )
        )
    return out


@router.put("/routing/{scenario}", response_model=RoutingOut)
async def update_routing(
    scenario: str,
    body: RoutingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新单个场景的 AI 路由。provider_name 为 null 表示跟随全局。"""
    if scenario not in ROUTING_SCENARIOS:
        raise HTTPException(status_code=404, detail="场景不存在")

    provider_name = (body.provider_name or "").strip().lower() or None
    model = (body.model or "").strip() or None
    if provider_name is not None:
        provider_result = await db.execute(
            select(AIProviderSetting).where(
                AIProviderSetting.provider_name == provider_name,
                AIProviderSetting.user_id == current_user.id,
            )
        )
        provider = provider_result.scalar_one_or_none()
        if not provider:
            raise HTTPException(status_code=404, detail="提供商不存在")

    result = await db.execute(
        select(AIRoutingSetting).where(
            AIRoutingSetting.scenario == scenario,
            AIRoutingSetting.user_id == current_user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        row = AIRoutingSetting(user_id=current_user.id, scenario=scenario, provider_name=provider_name, model=model)
        db.add(row)
    else:
        row.provider_name = provider_name
        row.model = model

    await db.commit()
    await db.refresh(row)
    return RoutingOut(
        scenario=row.scenario,
        label=ROUTING_SCENARIOS.get(row.scenario, row.scenario),
        provider_name=row.provider_name,
        model=row.model,
    )
