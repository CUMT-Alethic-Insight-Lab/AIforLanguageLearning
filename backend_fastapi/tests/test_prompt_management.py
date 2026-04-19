"""Prompt 资产管理测试。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.prompt_management.models import PromptRegistry
from app.domain.prompt_management.service import PromptManager, get_published_prompt


@pytest.fixture
def test_engine(tmp_path):
    db_path = tmp_path / "test_prompt.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


def test_create_and_get_prompt(test_engine) -> None:
    record = PromptManager.create_prompt({
        "prompt_key": "essay_grading",
        "system_prompt": "你是一位英语教师。",
        "user_template": "请批改：{{essay}}",
        "variables": ["essay"],
        "scene_type": "essay",
        "is_published": True,
    })
    assert record.id is not None
    assert record.version == "1.0.0"

    fetched = get_published_prompt("essay_grading")
    assert fetched is not None
    assert fetched.system_prompt == "你是一位英语教师。"


def test_get_prompt_not_found(test_engine) -> None:
    result = get_published_prompt("non_existent")
    assert result is None


def test_list_prompts_filter(test_engine) -> None:
    PromptManager.create_prompt({
        "prompt_key": "chat_greeting",
        "system_prompt": "Hi",
        "scene_type": "chat",
        "tags": ["greeting"],
        "is_published": True,
    })
    results = PromptManager.list_prompts(scene_type="chat", published_only=True)
    assert len(results) >= 1
    assert results[0].scene_type == "chat"


def test_publish_and_deprecate(test_engine) -> None:
    record = PromptManager.create_prompt({
        "prompt_key": "test_lifecycle",
        "system_prompt": "test",
    })
    assert record.is_published is False

    ok = PromptManager.publish_prompt(record.id)
    assert ok is True

    ok = PromptManager.deprecate_prompt(record.id)
    assert ok is True

    fetched = get_published_prompt("test_lifecycle")
    assert fetched is None  # deprecated 后不可见
