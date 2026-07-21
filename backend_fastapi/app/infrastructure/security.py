from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..settings import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days
TokenType = Literal["access", "refresh"]
_VALID_ROLES = frozenset({"student", "teacher", "admin"})


def _get_secret() -> str:
    return settings.jwt_secret


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except (TypeError, ValueError):
        return False


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


def _create_token(data: dict, token_type: TokenType, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    to_encode.update(
        {
            "exp": now + expires_delta,
            "iat": now,
            "token_type": token_type,
        }
    )
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    return _create_token(
        data,
        "access",
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    return _create_token(
        data,
        "refresh",
        expires_delta or timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES),
    )


def _claims_match_current_account(payload: dict) -> bool:
    username = payload.get("sub")
    if not isinstance(username, str) or not username.strip():
        return False

    user_id = payload.get("userId")
    if user_id is not None and (
        isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
    ):
        return False

    claimed_role = payload.get("role")
    if claimed_role is not None and (
        not isinstance(claimed_role, str) or claimed_role not in _VALID_ROLES
    ):
        return False

    # Token verification is an authentication boundary. Resolve the account here so
    # WebSocket and HTTP callers share the same subject/role checks.
    from .db_user import get_user_by_username

    user = get_user_by_username(username)
    if user is None or user.id is None:
        return False
    if user_id is not None and user.id != user_id:
        return False

    current_role = str(user.role or "")
    if current_role not in _VALID_ROLES:
        return False
    if claimed_role is not None and current_role != claimed_role:
        return False

    if getattr(user, "is_active", True) is False:
        return False
    account_status = getattr(user, "status", None)
    if account_status is not None and str(account_status).lower() not in {"active", "enabled"}:
        return False
    return True


def decode_token(token: str, expected_type: TokenType = "access") -> dict | None:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("token_type") != expected_type:
        return None
    if not _claims_match_current_account(payload):
        return None
    return payload
