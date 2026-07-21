from __future__ import annotations

from sqlmodel import Session, select

from ..db import get_engine
from ..domain.models import User


def get_user_by_username(username: str) -> User | None:
    with Session(get_engine()) as session:
        return session.exec(select(User).where(User.username == username)).first()


def get_user_by_email(email: str) -> User | None:
    with Session(get_engine()) as session:
        return session.exec(select(User).where(User.email == email)).first()


def get_user_by_id(user_id: int) -> User | None:
    with Session(get_engine()) as session:
        return session.get(User, user_id)


def create_user(username: str, email: str, password_hash: str, role: str = "student") -> User:
    user = User(username=username, email=email, password_hash=password_hash, role=role)
    with Session(get_engine()) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def update_user_password(user_id: int, password_hash: str) -> None:
    from datetime import datetime

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user:
            user.password_hash = password_hash
            user.updated_at = datetime.utcnow()
            session.add(user)
            session.commit()


def delete_user(user_id: int) -> None:
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user:
            session.delete(user)
            session.commit()


def list_users(limit: int = 50, offset: int = 0) -> tuple[list[User], int]:
    with Session(get_engine()) as session:
        users = list(session.exec(select(User).offset(offset).limit(limit)).all())
        total = session.exec(select(User)).all().__len__()
        return users, total
