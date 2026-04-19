"""主动服务建议引擎（实时助教）。

基于 ASR 结果检测教师显式/隐式需求，并在合适时机投递建议。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SuggestionType(Enum):
    ON_DEMAND = "on_demand"              # 被动触发（教师明确请求）
    PROACTIVE_HINT = "proactive_hint"    # 轻量提示（不打断）
    PROACTIVE_ASSIST = "proactive_assist"  # 主动辅助
    PROACTIVE_ALERT = "proactive_alert"  # 重要提醒


class UrgencyLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Suggestion:
    id: str
    type: SuggestionType
    urgency: UrgencyLevel
    content: str
    context: Dict[str, Any]
    delivery_method: str  # audio | visual | both
    ttl_seconds: int


class ProactiveSuggestionEngine:
    """主动服务建议引擎。

    核心理念：像一位经验丰富的助教，知道什么时候该说话，什么时候该安静。
    """

    def __init__(self) -> None:
        self.asr_buffer: List[Dict[str, Any]] = []
        self.teaching_state: str = "idle"
        self.delivered_suggestions: set[str] = set()
        self.on_suggestion: Optional[Callable[[Dict[str, Any]], Any]] = None
        self.on_audio_output: Optional[Callable[[bytes], Any]] = None
        self.config = {
            "min_asr_length": 10,
            "silence_threshold_ms": 2000,
            "proactive_cooldown": 30,
            "max_suggestions_per_minute": 2,
        }

    # ── ASR 输入处理 ──

    def on_asr_result(self, text: str, is_final: bool, timestamp: float) -> Optional[Suggestion]:
        """处理 ASR 结果，检测需求信号。"""
        self.asr_buffer.append({"text": text, "is_final": is_final, "timestamp": timestamp})
        if len(self.asr_buffer) > 50:
            self.asr_buffer.pop(0)

        if self._detect_explicit_wakeup(text):
            return self._handle_explicit_request(text)

        implicit_signals = self._detect_implicit_signals(text)
        if implicit_signals:
            return self._handle_implicit_need(implicit_signals, text)

        self._update_teaching_state(text)
        return None

    # ── 信号检测 ──

    def _detect_explicit_wakeup(self, text: str) -> bool:
        text_lower = text.lower()
        patterns = [
            "助教", "小助", "ai", "系统", "请问", "问一下", "我想问",
            "help", "assistant", "question", "给我个例子", "举个例子",
            "怎么解释", "怎么讲", "how to explain", "give me an example",
            "什么是", "什么叫", "what is", "what are", "difference between",
            # 唤醒词：Hi Helix / Hey Helix + 兜底 helix
            "hi helix", "hey helix", "high helix", "hay helix", "helix",
        ]
        return any(p in text_lower for p in patterns)

    def _detect_implicit_signals(self, text: str) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        text_lower = text.lower()

        # 犹豫信号
        hesitation = ["嗯", "呃", "这个", "那个", "就是", "em", "uh"]
        h_count = sum(1 for p in hesitation if p in text_lower)
        if h_count >= 2:
            signals.append({
                "type": "hesitation",
                "confidence": min(h_count * 0.3, 0.9),
                "description": "教师可能在组织语言或思考",
            })

        # 重复信号
        if len(self.asr_buffer) >= 3:
            recent = [b["text"] for b in self.asr_buffer[-3:]]
            sim = self._text_similarity(recent)
            if sim > 0.7:
                signals.append({
                    "type": "repetition",
                    "confidence": sim,
                    "description": "教师重复讲解同一内容，可能在强调重点或遇到困难",
                })

        # 纠错信号
        correction = ["不对", "错了", "更正", "应该是", "不是", "correct", "wrong"]
        if any(p in text_lower for p in correction):
            signals.append({
                "type": "correction",
                "confidence": 0.85,
                "description": "教师在纠正，可能需要确认正确表达",
            })

        # 强调信号
        emphasis = ["注意", "重点", "关键", "记住", "important", "pay attention"]
        if any(p in text_lower for p in emphasis):
            signals.append({
                "type": "emphasis",
                "confidence": 0.8,
                "description": "教师在强调重点，可能需要补充说明",
            })

        # 时间压力
        time_pressure = ["时间有限", "简单说", "快速", "来不及", "time is limited"]
        if any(p in text_lower for p in time_pressure):
            signals.append({
                "type": "time_pressure",
                "confidence": 0.75,
                "description": "教师有时间压力，可能需要精简建议",
            })

        return signals

    def _update_teaching_state(self, text: str) -> None:
        text_lower = text.lower()
        if any(p in text_lower for p in ["开始", "今天讲", "首先", "let's start"]):
            self.teaching_state = "opening"
        elif any(p in text_lower for p in ["例子", "比如", "例如", "for example"]):
            self.teaching_state = "example"
        elif any(p in text_lower for p in ["练习", "做题", "试试", "exercise"]):
            self.teaching_state = "exercise"
        elif any(p in text_lower for p in ["总结", "归纳", "总之", "in summary"]):
            self.teaching_state = "summary"
        elif any(p in text_lower for p in ["结束", "下课", "今天就到这里", "that's all"]):
            self.teaching_state = "closing"
        else:
            self.teaching_state = "explaining"

    # ── 建议生成 ──

    def _handle_explicit_request(self, text: str) -> Suggestion:
        return Suggestion(
            id=f"explicit_{int(time.time())}",
            type=SuggestionType.ON_DEMAND,
            urgency=UrgencyLevel.HIGH,
            content="",
            context={"trigger_text": text, "asr_history": self.asr_buffer[-5:]},
            delivery_method="audio",
            ttl_seconds=60,
        )

    def _handle_implicit_need(self, signals: List[Dict[str, Any]], text: str) -> Optional[Suggestion]:
        if not self._can_proactive_suggest():
            return None

        max_confidence = max(s["confidence"] for s in signals)
        primary = signals[0]["type"]

        if primary == "hesitation" and max_confidence > 0.6:
            return Suggestion(
                id=f"hint_{int(time.time())}",
                type=SuggestionType.PROACTIVE_HINT,
                urgency=UrgencyLevel.LOW,
                content="",
                context={"signal": "hesitation", "trigger_text": text},
                delivery_method="visual",
                ttl_seconds=10,
            )
        elif primary == "repetition" and max_confidence > 0.7:
            return Suggestion(
                id=f"assist_{int(time.time())}",
                type=SuggestionType.PROACTIVE_ASSIST,
                urgency=UrgencyLevel.MEDIUM,
                content="",
                context={"signal": "repetition", "trigger_text": text},
                delivery_method="both",
                ttl_seconds=30,
            )
        elif primary == "correction":
            return Suggestion(
                id=f"alert_{int(time.time())}",
                type=SuggestionType.PROACTIVE_ALERT,
                urgency=UrgencyLevel.HIGH,
                content="",
                context={"signal": "correction", "trigger_text": text},
                delivery_method="audio",
                ttl_seconds=15,
            )
        return None

    def _can_proactive_suggest(self) -> bool:
        recent = [s for s in self.delivered_suggestions if s.startswith(("hint_", "assist_"))]
        return len(recent) < self.config["max_suggestions_per_minute"]

    # ── 建议投递 ──

    def deliver(self, suggestion: Suggestion, content: str) -> None:
        """投递建议（内容需由 LLM 提前生成）。"""
        suggestion.content = content
        if suggestion.id in self.delivered_suggestions:
            return
        self.delivered_suggestions.add(suggestion.id)

        if suggestion.type == SuggestionType.ON_DEMAND:
            self._emit_audio(suggestion)
        elif suggestion.type == SuggestionType.PROACTIVE_HINT:
            self._emit_visual(suggestion)
        elif suggestion.type == SuggestionType.PROACTIVE_ASSIST:
            if self._is_good_timing():
                self._emit_audio(suggestion)
            else:
                self._emit_visual(suggestion)
        elif suggestion.type == SuggestionType.PROACTIVE_ALERT:
            self._emit_audio(suggestion)
            self._emit_visual(suggestion)

    def _emit_visual(self, suggestion: Suggestion) -> None:
        if self.on_suggestion:
            self.on_suggestion({
                "type": suggestion.type.value,
                "urgency": suggestion.urgency.value,
                "content": suggestion.content,
                "ttl": suggestion.ttl_seconds,
            })

    def _emit_audio(self, suggestion: Suggestion) -> None:
        # 音频数据由 TTS 模块生成后通过 on_audio_output 回调投递
        logger.info("Audio suggestion queued: %s", suggestion.id)

    def _is_good_timing(self) -> bool:
        if len(self.asr_buffer) < 2:
            return False
        last = self.asr_buffer[-1]
        if time.time() - last["timestamp"] > 2:
            return True
        if any(p in last["text"] for p in [".", "?", "!", "。", "？", "！"]):
            return True
        return False

    # ── 工具 ──

    @staticmethod
    def _text_similarity(texts: List[str]) -> float:
        if len(texts) < 2:
            return 0.0
        similarities = []
        for i in range(len(texts) - 1):
            s1, s2 = texts[i].lower(), texts[i + 1].lower()
            set1, set2 = set(s1.split()), set(s2.split())
            inter = len(set1 & set2)
            union = len(set1 | set2)
            similarities.append(inter / union if union else 0.0)
        return sum(similarities) / len(similarities)
