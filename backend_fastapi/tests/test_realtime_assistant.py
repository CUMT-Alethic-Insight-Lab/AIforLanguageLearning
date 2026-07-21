"""实时助教基础设施测试。"""

from __future__ import annotations

import time

import pytest

from app.domain.realtime_assistant import (
    ProactiveSuggestionEngine,
    RealtimeAssistantSession,
    ScreenChangeDetector,
    SessionManager,
    SmartTriggerEngine,
    TriggerPriority,
)
from app.domain.realtime_assistant.trigger_engine import ContextEvent


# ── Screen Detector ──


def test_screen_change_detector_initial() -> None:
    detector = ScreenChangeDetector()
    result = detector.detect_change(b"fake_image_data")
    assert result.changed is True
    assert result.change_type == "initial"


def test_screen_change_detector_cooldown() -> None:
    detector = ScreenChangeDetector(cooldown_seconds=10.0)
    detector.detect_change(b"fake1")
    result = detector.detect_change(b"fake2")
    # 当 Pillow 不可用时，第二次调用可能返回 initial（因为无法处理图像）
    # 或 cooldown（冷却时间内）；两种情况都合法
    assert result.change_type in ("cooldown", "initial")


# ── Trigger Engine ──


def test_smart_trigger_high_priority() -> None:
    engine = SmartTriggerEngine()
    engine.on_event(ContextEvent(timestamp=time.time(), event_type="lasso", data={"region": [0, 0, 100, 100]}))
    decision = engine.on_event(ContextEvent(timestamp=time.time(), event_type="voice_pause", data={"asr_text": "这个语法点"}))
    assert decision is not None
    assert decision.priority == TriggerPriority.HIGH
    assert decision.vlm_request is not None


def test_smart_trigger_ignore() -> None:
    engine = SmartTriggerEngine()
    decision = engine.on_event(ContextEvent(timestamp=time.time(), event_type="scroll", data={"direction": "down"}))
    assert decision is None or decision.priority == TriggerPriority.IGNORE


# ── Suggestion Engine ──


def test_proactive_suggestion_explicit_wakeup() -> None:
    engine = ProactiveSuggestionEngine()
    suggestion = engine.on_asr_result("助教，给我举个例子", True, time.time())
    assert suggestion is not None
    assert suggestion.type.value == "on_demand"


def test_proactive_suggestion_implicit_hesitation() -> None:
    engine = ProactiveSuggestionEngine()
    suggestion = engine.on_asr_result("嗯...这个语法点呢...就是...", True, time.time())
    assert suggestion is not None
    assert suggestion.type.value == "proactive_hint"


def test_proactive_suggestion_no_signal() -> None:
    engine = ProactiveSuggestionEngine()
    suggestion = engine.on_asr_result("Today we will learn about past tense.", True, time.time())
    assert suggestion is None


# ── Session ──


def test_session_context_management() -> None:
    session = RealtimeAssistantSession(user_id=42, username="teacher_a")
    session.context.append("user", "hello")
    session.context.append("assistant", "hi")
    history = session.context.to_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    session.close()


def test_session_text_similarity() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    assert session._text_similarity("hello world", "hello world") == 1.0
    assert session._text_similarity("hello world", "foo bar") == 0.0
    session.close()


def test_session_build_user_prompt() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    p = session._build_user_prompt("讲解内容", None)
    assert "讲解内容" in p
    p2 = session._build_user_prompt("test", {"x1": 0, "y1": 0, "x2": 100, "y2": 100})
    assert "框选" in p2
    session.close()


@pytest.mark.asyncio
async def test_session_on_screen_frame_invalid_base64() -> None:
    """非法 base64 应被捕获，不抛异常。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    result = await session.on_screen_frame("!!!not_valid_base64!!!")
    assert result is None
    session.close()


@pytest.mark.asyncio
async def test_session_on_asr_result_empty() -> None:
    """空文本应直接返回 None。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    result = await session.on_asr_result("", True)
    assert result is None
    session.close()


@pytest.mark.asyncio
async def test_session_explicit_request() -> None:
    """显式请求在冷却期内应返回 None（首次触发后进入冷却）。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    session.config.cooldown_seconds = 10.0
    # 设置 last_trigger_time 为现在，模拟刚触发过的状态
    session._last_trigger_time = time.time()
    # 由于有 cooldown，请求应该返回 None
    result = await session.on_explicit_request("测试请求", None)
    assert result is None
    session.close()


# ── Session Manager ──


def test_manager_create_and_remove() -> None:
    mgr = SessionManager()
    s = mgr.create_session(1, "alice")
    assert s.user_id == 1
    assert mgr.get_session(1) is s
    mgr.remove_session(1)
    assert mgr.get_session(1) is None


def test_manager_replace_old_session() -> None:
    mgr = SessionManager()
    s1 = mgr.create_session(1, "alice")
    s2 = mgr.create_session(1, "bob")
    assert mgr.get_session(1) is s2
    mgr.remove_session(1)


def test_manager_cleanup_stale() -> None:
    mgr = SessionManager(session_ttl_seconds=0.1)
    mgr.create_session(1, "alice")
    time.sleep(0.15)
    count = mgr.cleanup_stale()
    assert count == 1
    assert mgr.get_session(1) is None


def test_manager_stats() -> None:
    mgr = SessionManager()
    mgr.create_session(1, "alice")
    stats = mgr.get_stats()
    assert stats["active_sessions"] == 1
    assert len(stats["sessions"]) == 1
    mgr.remove_session(1)


# ── Wake Word Detection ──


def test_wake_word_exact() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    assert session._detect_wake_word("Hi Helix") is True
    assert session._detect_wake_word("hey helix") is True
    session.close()


def test_wake_word_phonetic_fallback() -> None:
    """音似容错：high helix / hay helix / hi heliks 等。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    assert session._detect_wake_word("high helix") is True
    assert session._detect_wake_word("hay helix") is True
    assert session._detect_wake_word("hi heliks") is True
    session.close()


def test_wake_word_helix_only() -> None:
    """兜底：只要包含 helix 就唤醒（避免 ASR 漏前半部分）。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    assert session._detect_wake_word("helix") is True
    assert session._detect_wake_word("what is helix") is True
    session.close()


def test_wake_word_negative() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    assert session._detect_wake_word("hello world") is False
    assert session._detect_wake_word("highlight the text") is False
    session.close()


# ── LLM Decision Extraction ──


def test_extract_decision_valid_json() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    d = session._extract_rta_decision(
        '{"should_intervene": true, "content": "建议", "use_tts": true, "urgency": "high"}'
    )
    assert d["should_intervene"] is True
    assert d["content"] == "建议"
    assert d["use_tts"] is True
    assert d["urgency"] == "high"
    session.close()


def test_extract_decision_no_intervene() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    d = session._extract_rta_decision(
        '{"should_intervene": false, "content": "", "use_tts": false}'
    )
    assert d["should_intervene"] is False
    assert d["content"] == ""
    assert d["use_tts"] is False
    session.close()


def test_extract_decision_markdown_block() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    d = session._extract_rta_decision(
        '```json\n{"should_intervene": true, "content": "测试", "use_tts": false}\n```'
    )
    assert d["should_intervene"] is True
    assert d["content"] == "测试"
    session.close()


def test_extract_decision_fallback_chinese() -> None:
    """非 JSON 但含中文建议时，兜底推断为 should_intervene=true。"""
    session = RealtimeAssistantSession(user_id=1, username="test")
    d = session._extract_rta_decision("这个单词的意思是苹果，常用于日常对话中描述水果。")
    assert d["should_intervene"] is True
    assert "苹果" in d["content"]
    session.close()


def test_extract_decision_empty() -> None:
    session = RealtimeAssistantSession(user_id=1, username="test")
    d = session._extract_rta_decision("")
    assert d["should_intervene"] is False
    session.close()
