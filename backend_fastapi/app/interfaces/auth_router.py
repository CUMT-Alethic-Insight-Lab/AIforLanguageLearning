from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError

from ..application.db_student import get_profile, upsert_profile
from ..application.db_vocabulary import get_due_words
from ..domain.models import User
from ..infrastructure.db_user import (
    create_user,
    get_user_by_email,
    get_user_by_username,
)
from ..infrastructure.dependencies import get_current_user
from ..infrastructure.rbac import get_user_role, is_account_enabled
from ..infrastructure.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_AUTHENTICATION_FAILED = "Invalid username or password"
_REGISTRATION_CONFLICT = "Unable to register with provided credentials"
_INVALID_SESSION = "Invalid or expired session"
_DUMMY_PASSWORD_HASH = hash_password("HelixDummyLoginPassword1")


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refreshToken: str


class LoginUser(BaseModel):
    id: int
    username: str
    role: str = "student"


class LoginData(BaseModel):
    accessToken: str
    refreshToken: str
    expiresIn: int
    user: LoginUser


class LoginResponse(BaseModel):
    success: bool
    data: LoginData | None = None
    error: str | None = None


class UserProfile(BaseModel):
    id: int
    username: str
    email: str
    created_at: str


class MeResponse(BaseModel):
    success: bool
    data: UserProfile | None = None
    error: str | None = None


class StudentProfileResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None


class DueWordsResponse(BaseModel):
    success: bool
    data: list[dict] | None = None
    error: str | None = None


def _can_authenticate(user: User | None) -> bool:
    return user is not None and is_account_enabled(user) and get_user_role(user) is not None


def _login_data_for(user: User) -> LoginData:
    role = get_user_role(user)
    if role is None or user.id is None:
        raise ValueError("Cannot issue tokens for an invalid account")

    token_data = {"sub": user.username, "userId": user.id}
    return LoginData(
        accessToken=create_access_token(token_data),
        refreshToken=create_refresh_token(token_data),
        expiresIn=60 * 60 * 24 * 7,
        user=LoginUser(id=user.id, username=user.username, role=role.value),
    )


@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest) -> LoginResponse:
    username = (req.username or "").strip()
    email = (req.email or "").strip().lower()
    password = req.password or ""

    if not username or not email or not password:
        return LoginResponse(success=False, error="Missing required fields")

    strength = validate_password_strength(password)
    if not strength.get("valid"):
        return LoginResponse(success=False, error=str(strength.get("message")))

    username_exists = get_user_by_username(username) is not None
    email_exists = get_user_by_email(email) is not None
    if username_exists or email_exists:
        return LoginResponse(success=False, error=_REGISTRATION_CONFLICT)

    try:
        user = create_user(username, email, hash_password(password))
    except IntegrityError:
        return LoginResponse(success=False, error=_REGISTRATION_CONFLICT)
    return LoginResponse(success=True, data=_login_data_for(user))


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    username = (req.username or "").strip()
    password = req.password or ""

    if not username or not password:
        return LoginResponse(success=False, error=_AUTHENTICATION_FAILED)

    user = get_user_by_username(username)
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(password, password_hash)
    if not _can_authenticate(user) or not password_matches:
        return LoginResponse(success=False, error=_AUTHENTICATION_FAILED)

    return LoginResponse(success=True, data=_login_data_for(user))


@router.post("/refresh", response_model=LoginResponse)
async def refresh(req: RefreshRequest) -> LoginResponse:
    payload = decode_token(req.refreshToken, expected_type="refresh")
    if payload is None:
        return LoginResponse(success=False, error=_INVALID_SESSION)
    username = payload.get("sub")
    user = get_user_by_username(username) if username else None
    if not _can_authenticate(user):
        return LoginResponse(success=False, error=_INVALID_SESSION)

    return LoginResponse(success=True, data=_login_data_for(user))


@router.post("/logout")
async def logout() -> dict:
    # 当前为无状态 JWT，登出由客户端丢弃 token 实现
    return {"success": True, "message": "Logged out"}


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        success=True,
        data=UserProfile(
            id=current_user.id or 0,
            username=current_user.username,
            email=current_user.email,
            created_at=current_user.created_at.isoformat(),
        ),
    )


@router.get("/profile", response_model=StudentProfileResponse)
async def get_student_profile(
    current_user: User = Depends(get_current_user),
) -> StudentProfileResponse:
    profile = get_profile(current_user.id or 0)
    if profile is None:
        return StudentProfileResponse(success=True, data=None)
    return StudentProfileResponse(
        success=True,
        data={
            "id": profile.id,
            "user_id": profile.user_id,
            "class_id": profile.class_id,
            "level": profile.level,
            "goals": profile.goals,
            "interests": profile.interests,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        },
    )


@router.post("/profile", response_model=StudentProfileResponse)
async def update_student_profile(
    data: dict,
    current_user: User = Depends(get_current_user),
) -> StudentProfileResponse:
    profile = upsert_profile(
        current_user.id or 0,
        class_id=data.get("class_id"),
        level=data.get("level"),
        goals=data.get("goals"),
        interests=data.get("interests"),
    )
    return StudentProfileResponse(
        success=True,
        data={
            "id": profile.id,
            "user_id": profile.user_id,
            "class_id": profile.class_id,
            "level": profile.level,
            "goals": profile.goals,
            "interests": profile.interests,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        },
    )


@router.get("/vocabulary/due", response_model=DueWordsResponse)
async def due_vocabulary(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
) -> DueWordsResponse:
    words = get_due_words(current_user.id or 0, limit=limit)
    return DueWordsResponse(
        success=True,
        data=[
            {
                "id": w.id,
                "word": w.word,
                "definition": w.definition,
                "pronunciation": w.pronunciation,
                "example": w.example,
                "mastery_level": w.mastery_level,
                "next_review_at": w.next_review_at.isoformat(),
            }
            for w in words
        ],
    )
