from __future__ import annotations

import re
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..settings import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days


def _get_secret() -> str:
    # 优先使用旧后端兼容的 JWT_SECRET 环境变量逻辑，但统一从 settings 读取
    # 如果 settings 未配置 jwt_secret，回退到一个默认密钥（仅开发环境）
    return getattr(settings, "jwt_secret", "change-me-in-production")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def validate_password_strength(password: str) -> dict[str, str | bool]:
    if len(password) < 8:
        return {"valid": False, "message": "Password must be at least 8 characters long"}
    if not re.search(r"[a-z]", password):
        return {"valid": False, "message": "Password must contain at least one lowercase letter"}
    if not re.search(r"[A-Z]", password):
        return {"valid": False, "message": "Password must contain at least one uppercase letter"}
    if not re.search(r"[0-9]", password):
        return {"valid": False, "message": "Password must contain at least one number"}
    return {"valid": True}


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None
