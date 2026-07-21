"""Role-Based Access Control (RBAC) implementation.

Provides role definitions and permission decorators for FastAPI routes.
"""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, status


class Role(str, Enum):
    """User roles in the system."""

    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


# Role hierarchy (higher = more permissions)
ROLE_HIERARCHY = {
    Role.STUDENT: 1,
    Role.TEACHER: 2,
    Role.ADMIN: 3,
}

# Default permissions for each role
ROLE_PERMISSIONS = {
    Role.STUDENT: [
        "read:own_profile",
        "update:own_profile",
        "read:own_courses",
        "submit:homework",
    ],
    Role.TEACHER: [
        "read:own_profile",
        "update:own_profile",
        "read:own_courses",
        "create:course",
        "update:own_course",
        "delete:own_course",
        "grade:homework",
        "read:student_data",
    ],
    Role.ADMIN: ["*"],
}


def get_user_role(user: Any) -> Role | None:
    """Extract role from user data."""
    role_str = getattr(user, "role", None)
    try:
        return Role(role_str)
    except (TypeError, ValueError):
        return None


def is_account_enabled(user: Any) -> bool:
    """Fail closed for disabled accounts when the backing model exposes status fields."""
    if getattr(user, "is_active", True) is False:
        return False
    account_status = getattr(user, "status", None)
    if account_status is None:
        return True
    return str(account_status).lower() in {"active", "enabled"}


def has_permission(user: Any, required_permission: str) -> bool:
    """Check if user has a specific permission."""
    if not is_account_enabled(user):
        return False
    role = get_user_role(user)
    if role == Role.ADMIN:
        return True
    permissions = ROLE_PERMISSIONS.get(role, [])
    return required_permission in permissions or "*" in permissions


def has_role(user: Any, required_role: Role) -> bool:
    """Check if user has at least the required role level."""
    if not is_account_enabled(user):
        return False
    user_role = get_user_role(user)
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    return user_level >= required_level


def require_role(required_role: Role) -> Callable[..., Any]:
    """Decorator to require a minimum role for a route."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user = kwargs.get("current_user")
            if not current_user:
                for arg in args:
                    if hasattr(arg, "username"):
                        current_user = arg
                        break
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            if not has_role(current_user, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(required_permission: str) -> Callable[..., Any]:
    """Decorator to require a specific permission for a route."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user = kwargs.get("current_user")
            if not current_user:
                for arg in args:
                    if hasattr(arg, "username"):
                        current_user = arg
                        break
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            if not has_permission(current_user, required_permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
