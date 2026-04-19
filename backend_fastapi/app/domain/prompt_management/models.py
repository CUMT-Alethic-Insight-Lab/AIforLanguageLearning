"""Prompt 资产管理模型。"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class PromptRegistry(SQLModel, table=True):
    """Prompt 模板注册表 — 支持版本管理与 A/B 分组。"""

    __tablename__ = "prompt_registry"

    id: int | None = Field(default=None, primary_key=True)
    prompt_key: str = Field(index=True, max_length=128)
    version: str = Field(default="1.0.0", max_length=32)
    owner: str = Field(default="system", max_length=64)
    ab_bucket: str = Field(default="default", max_length=32)

    # 内容
    system_prompt: str = Field(default="")
    user_template: str = Field(default="")
    variables: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # 元数据
    description: str = Field(default="", max_length=512)
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scene_type: str | None = Field(default=None, max_length=32)  # chat/vocab/essay/scenario_expansion
    model_hint: str | None = Field(default=None, max_length=64)
    temperature: float | None = Field(default=None)
    max_tokens: int | None = Field(default=None)

    # 质量指标（可选回填）
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # 状态
    is_published: bool = Field(default=False)
    is_deprecated: bool = Field(default=False)

    created_at: _dt.datetime = Field(default_factory=_dt.datetime.utcnow)
    updated_at: _dt.datetime = Field(default_factory=_dt.datetime.utcnow)
