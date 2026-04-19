from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=128)
    email: str = Field(index=True, unique=True, max_length=256)
    password_hash: str = Field(default="", max_length=256)
    role: str = Field(default="student", max_length=32)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StudentProfile(SQLModel, table=True):
    __tablename__ = "students"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    class_id: str | None = Field(default=None, index=True, max_length=64)
    level: str = Field(default="beginner", max_length=32)
    goals: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    interests: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class VocabularyItem(SQLModel, table=True):
    __tablename__ = "vocabulary"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    word: str = Field(index=True, max_length=256)
    definition: str = Field(default="")
    pronunciation: str = Field(default="")
    example: str = Field(default="")
    mastery_level: int = Field(default=0)
    next_review_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LearningRecord(SQLModel, table=True):
    __tablename__ = "learning_records"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    type: str = Field(max_length=32)  # vocabulary, essay, dialogue, analysis
    content: str = Field(default="")
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LearningPath(SQLModel, table=True):
    __tablename__ = "learning_paths"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    title: str = Field(max_length=256)
    description: str = Field(default="")
    milestones: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="active", max_length=32)  # active, completed, archived
    progress: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
