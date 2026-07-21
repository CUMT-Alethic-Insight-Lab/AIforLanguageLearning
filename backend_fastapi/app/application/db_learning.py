from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, col, select

from ..db import get_engine
from ..domain.models import LearningPath, LearningRecord


def create_record(
    user_id: int,
    record_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> LearningRecord:
    record = LearningRecord(
        user_id=user_id,
        type=record_type,
        content=content,
        meta_data=metadata or {},
        created_at=datetime.now(UTC),
    )
    with Session(get_engine()) as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_records_by_user_and_type(
    user_id: int, record_type: str, limit: int = 50
) -> list[LearningRecord]:
    with Session(get_engine()) as session:
        return list(
            session.exec(
                select(LearningRecord)
                .where(LearningRecord.user_id == user_id)
                .where(LearningRecord.type == record_type)
                .order_by(col(LearningRecord.created_at).desc())
                .limit(limit)
            ).all()
        )


def create_path(user_id: int, title: str, description: str, milestones: list[Any]) -> LearningPath:
    now = datetime.now(UTC)
    path = LearningPath(
        user_id=user_id,
        title=title,
        description=description,
        milestones=milestones,
        status="active",
        progress=0,
        created_at=now,
        updated_at=now,
    )
    with Session(get_engine()) as session:
        existing_active_paths = list(
            session.exec(
                select(LearningPath)
                .where(LearningPath.user_id == user_id)
                .where(LearningPath.status == "active")
            ).all()
        )
        for existing_path in existing_active_paths:
            existing_path.status = "archived"
            existing_path.updated_at = now
            session.add(existing_path)

        session.add(path)
        session.commit()
        session.refresh(path)
        return path


def get_active_path(user_id: int) -> LearningPath | None:
    with Session(get_engine()) as session:
        return session.exec(
            select(LearningPath)
            .where(LearningPath.user_id == user_id)
            .where(LearningPath.status == "active")
            .order_by(col(LearningPath.created_at).desc())
        ).first()


def update_path_progress(path_id: int, progress: int) -> None:
    with Session(get_engine()) as session:
        path = session.get(LearningPath, path_id)
        if path:
            normalized_progress = max(0, min(int(progress), 100))
            path.progress = normalized_progress
            if normalized_progress >= 100:
                path.status = "completed"
            elif path.status == "completed":
                path.status = "active"
            path.updated_at = datetime.now(UTC)
            session.add(path)
            session.commit()
