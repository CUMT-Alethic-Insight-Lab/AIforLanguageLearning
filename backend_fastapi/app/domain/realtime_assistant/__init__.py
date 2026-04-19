"""实时助教模块（Real-Time Teaching Assistant）。

模块职责：
1. 屏幕变化检测（ScreenChangeDetector）
2. 智能触发决策（SmartTriggerEngine）
3. 主动建议引擎（ProactiveSuggestionEngine）
4. 会话管理（RealtimeAssistantSession / SessionManager）
5. WebSocket + HTTP 路由（realtime_assistant_router）

能力层调用（不重新发明轮子）：
- OCR → app.ocr.ocr_image_base64()
- LLM 多模态 → app.llm.chat_complete_multimodal()
- LLM 纯文本 → app.llm.chat_complete()
- TTS → app.tts.synthesize_tts_wav()
"""

from .manager import SessionManager
from .screen_detector import ScreenChangeDetector
from .session import RealtimeAssistantSession
from .suggestion_engine import (
    ProactiveSuggestionEngine,
    Suggestion,
    SuggestionType,
    UrgencyLevel,
)
from .trigger_engine import (
    ContextEvent,
    SmartTriggerEngine,
    TriggerDecision,
    TriggerPriority,
)

__all__ = [
    "ContextEvent",
    "ProactiveSuggestionEngine",
    "RealtimeAssistantSession",
    "ScreenChangeDetector",
    "SessionManager",
    "SmartTriggerEngine",
    "Suggestion",
    "SuggestionType",
    "TriggerDecision",
    "TriggerPriority",
    "UrgencyLevel",
]
