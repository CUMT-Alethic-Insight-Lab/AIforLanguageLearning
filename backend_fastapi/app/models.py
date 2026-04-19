from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class PublicVocabEntry(SQLModel, table=True):
    __tablename__ = "public_vocab_entries"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    term: str = Field(index=True, unique=True, max_length=256)
    definition: str = Field(default="")
    lang: str = Field(default="en", max_length=16)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserVocabQuery(SQLModel, table=True):
    __tablename__ = "user_vocab_queries"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    session_id: str = Field(default="", index=True, max_length=128)
    conversation_id: str = Field(default="", index=True, max_length=128)
    term: str = Field(index=True, max_length=256)
    source: str = Field(default="manual", max_length=32)
    result: str = Field(default="")
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationEvent(SQLModel, table=True):
    __tablename__ = "conversation_events"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_conversation_seq"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    session_id: str = Field(default="", index=True, max_length=128)
    conversation_id: str = Field(default="", index=True, max_length=128)

    seq: int = Field(index=True)
    type: str = Field(max_length=64)
    ts: int = Field(index=True)
    request_id: str = Field(default="", max_length=128)
    final: bool = Field(default=False)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow)


class EssaySubmission(SQLModel, table=True):
    __tablename__ = "essay_submissions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    session_id: str = Field(default="", index=True, max_length=128)
    conversation_id: str = Field(default="", index=True, max_length=128)
    request_id: str = Field(default="", max_length=128)

    ocr_text: str = Field(default="")
    language: str = Field(default="", max_length=32)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class EssayResult(SQLModel, table=True):
    __tablename__ = "essay_results"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="essay_submissions.id", index=True)

    score: int | None = Field(default=None)
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow)
