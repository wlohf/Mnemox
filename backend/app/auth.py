"""认证工具：密码哈希、JWT 生成与验证、FastAPI 依赖"""
from datetime import datetime, timedelta
import os
from typing import Optional
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS))
    token_version = int(to_encode.pop("token_version", 0))
    to_encode.update({"exp": expire, "jti": uuid4().hex, "tv": token_version})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def is_secure_cookie_environment() -> bool:
    return settings.ENVIRONMENT.lower() in {"prod", "production"} or bool(os.environ.get("DB_PASSWORD"))


async def get_user_from_token(token: str, db: AsyncSession) -> User:
    """Decode a JWT token and return the active user it represents."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except (InvalidTokenError, ValueError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    try:
        token_version = int(payload.get("tv", -1))
    except (TypeError, ValueError):
        raise credentials_exception
    if token_version != int(getattr(user, "token_version", 0) or 0):
        raise credentials_exception
    return user


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Bearer remains supported for API/CLI clients. The browser uses a
    # HttpOnly cookie so its durable session token is not readable by XSS.
    candidate = token or request.cookies.get(settings.AUTH_COOKIE_NAME, "")
    return await get_user_from_token(candidate, db)
