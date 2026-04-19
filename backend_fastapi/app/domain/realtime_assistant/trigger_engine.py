"""智能触发决策引擎（实时助教 L4）。

基于事件缓冲区做优先级决策，决定是否调用 Kimi API。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TriggerPriority(Enum):
    HIGH = "high"      # 立即触发
    MEDIUM = "medium"  # 延迟触发
    LOW = "low"        # 本地规则兜底
    IGNORE = "ignore"  # 忽略


@dataclass
class ContextEvent:
    timestamp: float
    event_type: str  # lasso | page_change | voice_pause | voice_active | scroll
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerDecision:
    priority: TriggerPriority
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)
    vlm_request: Dict[str, Any] | None = None


class SmartTriggerEngine:
    """智能触发决策引擎。

    决策逻辑：
    1. 高优先级: 框选 + 语音停顿 → 教师正在讲解重点，立即触发 VLM
    2. 中优先级: 翻页后停留 > 3s → 进入新页面，延迟触发 VLM
    3. 低优先级: 仅翻页 / 仅语音停顿 → 本地规则兜底
    4. 忽略: 快速翻页、随机晃动、UI 操作
    """

    def __init__(
        self,
        cooldown_seconds: float = 3.0,
        buffer_window_seconds: float = 5.0,
        page_stay_threshold: float = 3.0,
    ) -> None:
        self.event_buffer: List[ContextEvent] = []
        self.last_trigger_time: float = 0.0
        self.cooldown_seconds = cooldown_seconds
        self.buffer_window_seconds = buffer_window_seconds
        self.page_stay_threshold = page_stay_threshold

    def on_event(self, event: ContextEvent) -> Optional[TriggerDecision]:
        """处理事件，返回触发决策（若为 HIGH 则直接返回请求）。"""
        if time.time() - self.last_trigger_time < self.cooldown_seconds:
            return None

        self.event_buffer.append(event)
        self._clean_old_events()

        decision = self._make_decision()
        if decision.priority == TriggerPriority.HIGH:
            self.last_trigger_time = time.time()
            decision.vlm_request = self._build_vlm_request(decision)
            return decision
        elif decision.priority == TriggerPriority.MEDIUM:
            # 延迟触发由调用方处理（如启动定时器）
            return decision

        return None

    def _make_decision(self) -> TriggerDecision:
        now = time.time()
        has_lasso = any(e.event_type == "lasso" for e in self.event_buffer)
        has_voice_pause = any(e.event_type == "voice_pause" for e in self.event_buffer)
        has_page_change = any(e.event_type == "page_change" for e in self.event_buffer)
        has_scroll = any(e.event_type == "scroll" for e in self.event_buffer)

        # 高优先级: 框选 + 语音停顿 = 教师正在讲解重点
        if has_lasso and has_voice_pause:
            return TriggerDecision(
                priority=TriggerPriority.HIGH,
                reason="教师框选了内容并停顿，可能正在讲解重点",
                context=self._extract_context(),
            )

        # 中优先级: 翻页后停留
        if has_page_change:
            page_event = next(e for e in self.event_buffer if e.event_type == "page_change")
            time_since_page = now - page_event.timestamp
            if time_since_page > self.page_stay_threshold:
                return TriggerDecision(
                    priority=TriggerPriority.MEDIUM,
                    reason="翻页后停留，可能正在讲解新内容",
                    context=self._extract_context(),
                )

        # 低优先级: 仅语音停顿
        if has_voice_pause and not has_lasso and not has_page_change:
            return TriggerDecision(
                priority=TriggerPriority.LOW,
                reason="语音停顿，可能完成了一段讲解",
                context=self._extract_context(),
            )

        # 忽略: 仅滚动/UI操作
        if has_scroll and not has_lasso and not has_voice_pause and not has_page_change:
            return TriggerDecision(
                priority=TriggerPriority.IGNORE,
                reason="仅滚动浏览，无教学意图",
            )

        return TriggerDecision(
            priority=TriggerPriority.IGNORE,
            reason="无意义事件",
        )

    def _extract_context(self) -> Dict[str, Any]:
        """提取最近的上下文信息。"""
        recent_asr = ""
        for e in reversed(self.event_buffer):
            if e.event_type == "voice_pause" and e.data.get("asr_text"):
                recent_asr = e.data["asr_text"]
                break

        lasso_region = None
        for e in reversed(self.event_buffer):
            if e.event_type == "lasso":
                lasso_region = e.data.get("region")
                break

        return {
            "recent_asr_text": recent_asr,
            "lasso_region": lasso_region,
            "event_count": len(self.event_buffer),
            "buffer_span_seconds": (
                self.event_buffer[-1].timestamp - self.event_buffer[0].timestamp
                if len(self.event_buffer) >= 2 else 0.0
            ),
        }

    def _build_vlm_request(self, decision: TriggerDecision) -> Dict[str, Any]:
        """构建 Kimi API / VLM 请求（占位，实际调用由上层完成）。"""
        context = decision.context
        return {
            "model": "kimi-k2.5",
            "messages": [
                {
                    "role": "system",
                    "content": "你是一位英语教学助教，基于教师的课件和框选行为提供实时建议。",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"""
教师在讲解课件时框选了以下区域（高亮部分）。
上下文: {context.get('recent_asr_text', '无语音输入')}

请分析:
1. 框选内容的教学重点
2. 学生可能的疑问点
3. 补充讲解建议
4. 相关例句或拓展知识
                            """.strip(),
                        }
                    ],
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500,
        }

    def _clean_old_events(self) -> None:
        cutoff = time.time() - self.buffer_window_seconds
        self.event_buffer = [e for e in self.event_buffer if e.timestamp > cutoff]
