"""Password hashing (bcrypt) and JWT access tokens; FastAPI auth dependencies. Pattern from the earlier project
(backend/api/deps.py: OAuth2 bearer, roles admin/operator/viewer, ?token= for <img> and WebSocket)."""
from __future__ import annotations

import datetime as dt
import hmac
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import User

ROLES = ("admin", "operator", "viewer")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
PASSWORD_CHANGE_REQUIRED = HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
# Reachable while a password change is pending (default admin before first use).
PASSWORD_CHANGE_PATHS = ("/api/v1/auth/me", "/api/v1/auth/change-password")


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    return jwt.encode({"sub": username, "role": role, "exp": exp}, settings.SECRET_KEY, algorithm="HS256")


async def user_from_token(token: Optional[str], db: AsyncSession) -> User:
    if not settings.AUTH_ENABLED:
        return User(id=0, username="anonymous", role="admin", is_active=True, password_hash="")
    if not token:
        raise UNAUTHORIZED
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise UNAUTHORIZED from None
    user = (await db.execute(select(User).where(User.username == payload.get("sub")))).scalars().first()
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return user


async def current_user(request: Request, token: Optional[str] = Depends(oauth2),
                       q_token: Optional[str] = Query(None, alias="token"), db: AsyncSession = Depends(get_db)) -> User:
    user = await user_from_token(token or q_token, db)
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise PASSWORD_CHANGE_REQUIRED
    return user


def require(*roles: str):
    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role {user.role!r} not allowed")
        return user
    return dep


any_role = require(*ROLES)
operator = require("admin", "operator")
admin = require("admin")


async def ingest_key(x_ingest_key: str = Header("")) -> None:
    if not settings.INGEST_KEY or not hmac.compare_digest(x_ingest_key, settings.INGEST_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid ingest key")
