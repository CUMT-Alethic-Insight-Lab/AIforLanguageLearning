from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from ..db import get_engine
from ..domain.models import StudentProfile


def get_profile(user_id: int) -> StudentProfile | None:
    with Session(get_engine()) as session:
        return session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()


def upsert_profile(
    user_id: int,
    class_id: str | None = None,
    level: str | None = None,
    goals: list[str] | None = None,
    interests: list[str] | None = None,
) -> StudentProfile:
    with Session(get_engine()) as session:
        existing = session.exec(
            select(StudentProfile).where(StudentProfile.user_id == user_id)
        ).first()
        now = datetime.utcnow()
        if existing:
            if class_id is not None:
                existing.class_id = class_id
            if level is not None:
                existing.level = level
            if goals is not None:
                existing.goals = goals
            if interests is not None:
                existing.interests = interests
            existing.updated_at = now
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        profile = StudentProfile(
            user_id=user_id,
            class_id=class_id,
            level=level or "beginner",
            goals=goals or [],
            interests=interests or [],
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile
