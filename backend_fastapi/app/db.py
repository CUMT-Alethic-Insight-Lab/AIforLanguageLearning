from __future__ import annotations

from typing import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from . import models as _app_models  # noqa: F401

# Import domain models to ensure all tables are registered in SQLModel metadata
from .domain import models as _domain_models  # noqa: F401
from .domain.analytics import models as _analytics_models  # noqa: F401
from .domain.classroom import models as _classroom_models  # noqa: F401
from .domain.prompt_management import models as _prompt_models  # noqa: F401
from .settings import settings

_engine = None
_async_engine = None


def _create_sqlite_engine(database_url: str):
    connect_args = {"check_same_thread": False}

    if database_url.endswith(":memory:"):
        return create_engine(database_url, connect_args=connect_args, poolclass=StaticPool)

    return create_engine(database_url, connect_args=connect_args)


def _to_async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("sqlite"):
        return url
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = _create_sqlite_engine(settings.database_url)
    return _engine


def get_async_engine():
    global _async_engine
    if _async_engine is None:
        url = _to_async_url(settings.database_url)
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            _async_engine = create_async_engine(
                url, connect_args=connect_args, poolclass=StaticPool
            )
        else:
            _async_engine = create_async_engine(
                url,
                echo=False,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,
            )
    return _async_engine


def override_engine_for_tests(engine) -> None:
    global _engine
    _engine = engine


def override_async_engine_for_tests(engine) -> None:
    global _async_engine
    _async_engine = engine


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _seed_admin_user()


def _seed_admin_user() -> None:
    if not bool(settings.seed_admin_enabled):
        return

    username = str(settings.seed_admin_username or "").strip()
    email = str(settings.seed_admin_email or "").strip()
    password = str(settings.seed_admin_password or "")
    if not username or not email or not password:
        return

    from .domain.models import User
    from .infrastructure.security import hash_password, validate_password_strength

    if not validate_password_strength(password).get("valid"):
        return

    with Session(get_engine()) as session:
        existing_username = session.exec(select(User).where(User.username == username)).first()
        existing_email = session.exec(select(User).where(User.email == email)).first()
        if existing_username is not None or existing_email is not None:
            return
        session.add(
            User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role="admin",
            )
        )
        session.commit()


async def init_db_async() -> None:
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


AsyncSessionLocal = None


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        AsyncSessionLocal = sessionmaker(
            get_async_engine(), class_=AsyncSession, expire_on_commit=False
        )
    async with AsyncSessionLocal() as session:
        yield session
