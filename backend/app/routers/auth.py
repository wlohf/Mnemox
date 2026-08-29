"""认证路由：注册、登录、获取当前用户"""
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_current_user, hash_password, is_secure_cookie_environment, verify_password
from app.config import settings
from app.database import get_db
from app.models.user import User

router = APIRouter()

_USERNAME_RE = re.compile(r'^[\w\u4e00-\u9fff]+$')
_failed_logins: dict[str, deque[float]] = defaultdict(deque)


def _login_key(username: str) -> str:
    return username.strip().casefold()


def _prune_login_attempts(key: str, now: float) -> deque[float]:
    attempts = _failed_logins[key]
    while attempts and now - attempts[0] >= settings.AUTH_ACCOUNT_WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        _failed_logins.pop(key, None)
        return deque()
    return attempts


def _ensure_login_not_throttled(username: str, user: User | None = None) -> None:
    attempts = _prune_login_attempts(_login_key(username), time.monotonic())
    if len(attempts) >= settings.AUTH_ACCOUNT_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(settings.AUTH_ACCOUNT_WINDOW_SECONDS)})
    now = datetime.utcnow()
    locked_until = getattr(user, "login_locked_until", None) if user else None
    if locked_until and locked_until > now:
        remaining = max(1, int((locked_until - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试",
            headers={"Retry-After": str(remaining)},
        )


def _record_failed_login(username: str) -> None:
    key = _login_key(username)
    now = time.monotonic()
    attempts = _prune_login_attempts(key, now)
    if key not in _failed_logins:
        _failed_logins[key] = attempts
    attempts.append(now)


def _clear_failed_logins(username: str) -> None:
    _failed_logins.pop(_login_key(username), None)


async def _record_account_login_failure(db: AsyncSession, user: User) -> None:
    """Persist an account lock so failures cannot be spread across workers."""
    now = datetime.utcnow()
    window_started = user.login_failed_window_started_at
    if not window_started or now - window_started >= timedelta(seconds=settings.AUTH_ACCOUNT_WINDOW_SECONDS):
        user.failed_login_count = 0
        user.login_failed_window_started_at = now
        user.login_locked_until = None
    user.failed_login_count = int(user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.AUTH_ACCOUNT_MAX_FAILURES:
        user.login_locked_until = now + timedelta(seconds=settings.AUTH_ACCOUNT_WINDOW_SECONDS)
    # The dependency rolls back on the 401 exception, so persist failure
    # state before raising it.
    await db.commit()


def _clear_account_login_failures(user: User) -> None:
    user.failed_login_count = 0
    user.login_failed_window_started_at = None
    user.login_locked_until = None


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure_cookie_environment(),
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    created_at: str


@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    username = body.username.strip()
    if len(username) < 2 or len(username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度需在 2-50 之间")
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="用户名仅允许字母、数字、下划线和中文")
    if len(body.password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=400, detail=f"密码长度不能小于 {settings.AUTH_PASSWORD_MIN_LENGTH} 位")
    if username.casefold() in body.password.casefold():
        raise HTTPException(status_code=400, detail="密码不能包含用户名")

    result = await db.execute(
        select(User).where(or_(User.username == username, User.email == body.email.lower()))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="注册信息无法使用，请检查后重试")

    user = User(
        username=username,
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Seed default AI providers for the new user
    try:
        from app.routers.ai_settings import seed_user_providers
        await seed_user_providers(db, user.id)
    except Exception:
        pass

    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=str(user.created_at or ""),
    )


@router.post("/login", response_model=TokenResponse)
async def login(response: Response, form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.username == form.username).with_for_update()
    )
    user = result.scalar_one_or_none()
    _ensure_login_not_throttled(form.username, user)
    if not user or not verify_password(form.password, user.hashed_password):
        if user:
            await _record_account_login_failure(db, user)
        else:
            _record_failed_login(form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _clear_failed_logins(form.username)
    _clear_account_login_failures(user)
    token = create_access_token(data={"sub": str(user.id), "token_version": int(user.token_version or 0)})
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalidate all current access tokens for this account and clear cookie."""
    current_user.token_version = int(current_user.token_version or 0) + 1
    await db.commit()
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        created_at=str(current_user.created_at or ""),
    )
