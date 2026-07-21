"""实时助教会话 — 完整业务链路内聚实现。

一条会话 = 一位教师 + 一个 WebSocket 连接 + 完整的感知-决策-行动闭环。
所有能力层调用（OCR/LLM/TTS）在此组装，不向下层泄漏业务细节。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ...llm import chat_complete_cloud_first, chat_complete_multimodal, chat_complete_race
from ...ocr import ocr_image_base64
from ...settings import settings
from ...tts import synthesize_tts_wav
from .screen_detector import ScreenChangeDetector
from .suggestion_engine import ProactiveSuggestionEngine, SuggestionType
from .trigger_engine import SmartTriggerEngine, TriggerPriority

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """会话级上下文（助教与教师的最近 N 轮交互）。

    支持打断续接：已播报内容作为 assistant 记录，未播报内容标记为
    [interrupted:未播报]，让 LLM 充分了解打断位置。
    """

    turns: list[dict[str, Any]] = field(default_factory=list)
    max_turns: int = 6
    _interrupted_buffer: str = ""  # 未播报内容缓冲区

    def append(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})
        if len(self.turns) > self.max_turns * 2:
            self.turns = self.turns[-self.max_turns * 2 :]

    def mark_interrupted(self, spoken: str, remaining: str) -> None:
        """标记打断状态：已播报内容加入历史，未播报内容存入缓冲区。"""
        if spoken:
            self.turns.append({
                "role": "assistant",
                "content": spoken,
                "metadata": {"interrupted": True, "part": "spoken"}
            })
        if remaining:
            self._interrupted_buffer = remaining

    def get_interruption_context(self) -> str:
        """获取打断上下文提示（注入 System Prompt）。"""
        if not self._interrupted_buffer:
            return ""
        return (
            f"【打断上下文】上一次回复在播报中被教师打断。"
            f"未播报内容：{self._interrupted_buffer[:200]}..."
            f"请基于未播报内容的意图继续表达，不要重复已播报部分。"
        )

    def clear_interruption(self) -> None:
        """清除打断缓冲区（新一轮成功播报后）。"""
        self._interrupted_buffer = ""

    def to_history(self) -> list[dict[str, Any]]:
        return list(self.turns)


@dataclass
class FrameState:
    """屏幕帧处理状态。"""

    last_ocr_text: str = ""
    last_ocr_timestamp: float = 0.0
    frame_counter: int = 0


@dataclass
class SessionConfig:
    """会话运行时配置（从 settings 读取，可按用户覆盖）。"""

    cooldown_seconds: float = 5.0
    ocr_language: str = "english"
    tts_enabled: bool = True
    llm_model: str = "moonshot-v1-auto"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_timeout: float = 15.0
    max_context_turns: int = 6

    @classmethod
    def from_settings(cls) -> SessionConfig:
        return cls(
            cooldown_seconds=settings.rta_cooldown_seconds,
            ocr_language=settings.rta_ocr_language,
            tts_enabled=settings.rta_tts_enabled,
            llm_model=settings.rta_llm_model,
            llm_base_url=settings.rta_llm_base_url,
            llm_api_key=settings.rta_llm_api_key,
            llm_timeout=settings.rta_llm_timeout_seconds,
            max_context_turns=settings.rta_max_context_turns,
        )


class RealtimeAssistantSession:
    """实时助教会话。

    职责：
    1. 接收前端事件（屏幕帧、鼠标、键盘、ASR）
    2. 维护会话上下文和屏幕状态
    3. 执行触发决策和主动建议
    4. 调用 OCR → LLM（多模态）→ TTS 完整链路
    5. 向教师返回结构化建议（文本+音频）

    鲁棒性：
    - 任何子系统失败都有降级保护（OCR 失败只用语音文本；LLM 失败返回本地兜底；TTS 失败只发文本）
    - 单会话内串行处理（_lock 保护），避免并发请求导致 Token 爆炸
    - 冷却时间防止高频触发
    """

    SYSTEM_PROMPT = (
        "你是一位英语教学课堂的隐形助教。你的核心原则是\"无感、非侵入\"——"
        "只有在教师真正需要帮助、或被显式唤醒时，才给出建议；否则保持完全沉默。\n\n"
        "判断标准（满足任一才建议介入）：\n"
        "1. 教师明显遇到困难：长时间停顿、自我纠错、重复、语气不确定\n"
        "2. 学生提问教师未回答或答非所问\n"
        "3. 课件中出现常见教学陷阱（如易混淆词汇、语法误区）\n"
        "4. 被显式唤醒词触发：'Hi Helix' 或 'Hey Helix'\n\n"
        "输出格式（严格 JSON，不要输出任何多余文本、Markdown、代码块）：\n"
        '{\n'
        '  "should_intervene": true/false,\n'
        '  "intervention_type": "hint|correction|answer|encouragement|none",\n'
        '  "content": "简短口语化建议（150字以内，适合直接朗读）",\n'
        '  "use_tts": true/false,\n'
        '  "urgency": "high|medium|low"\n'
        '}\n\n'
        "要求：\n"
        "- 如果不需要介入：should_intervene=false, content='', use_tts=false\n"
        "- 如果需要介入但只需静默显示（不打扰课堂）：use_tts=false\n"
        "- 如果需要声音打断（紧急纠正、唤醒响应）：use_tts=true\n"
        "- content 必须口语化、简洁，适合直接朗读，用中文输出\n"
        "- urgency 仅当 should_intervene=true 时有效：high=立即打断，medium=正常建议，low=轻量提示"
    )

    # 唤醒响应兜底文本（LLM 不可用时使用）
    WAKE_FALLBACK_TEXT = "我在，请说。"
    # 常规 fallback 静默处理——LLM 不可用时默认不介入
    FALLBACK_TEXT = ""

    def __init__(self, user_id: int, username: str) -> None:
        self.user_id = user_id
        self.username = username
        self.config = SessionConfig.from_settings()
        self.context = SessionContext(max_turns=self.config.max_context_turns)
        self.frame_state = FrameState()
        self.screen_detector = ScreenChangeDetector(
            hash_threshold=8,
            pixel_threshold=0.03,
            cooldown_seconds=self.config.cooldown_seconds,
        )
        self.trigger_engine = SmartTriggerEngine(
            cooldown_seconds=self.config.cooldown_seconds,
            buffer_window_seconds=8.0,
        )
        self.suggestion_engine = ProactiveSuggestionEngine()

        self._lock = asyncio.Lock()
        self._last_trigger_time: float = 0.0
        self._active: bool = True

        # Barge-in 打断续接状态
        self._current_tts_content: str = ""       # 当前正在播报的内容
        self._current_tts_total_bytes: int = 0    # TTS 总字节数
        self._current_tts_sent_bytes: int = 0     # 已发送字节数

    # ── 公共事件接口 ──

    async def on_screen_frame(self, image_base64: str) -> dict[str, Any] | None:
        """处理屏幕帧（教师翻页/框选后发送）。

        返回：若触发分析，返回建议 payload；否则返回 None。
        """
        if not self._active:
            return None

        async with self._lock:
            return await self._handle_screen_frame(image_base64)

    async def on_asr_result(self, text: str, is_final: bool) -> dict[str, Any] | None:
        """处理 ASR 结果。

        如果是 final，会：
        1. 注入触发决策引擎
        2. 检测唤醒词（智能兜底）
        3. 输入主动建议引擎检测显式/隐式需求
        4. 让 LLM 做最终决策：是否介入、是否 TTS
        """
        if not self._active or not text:
            return None

        now = time.time()
        # 注入触发引擎
        from .trigger_engine import ContextEvent

        self.trigger_engine.on_event(
            ContextEvent(timestamp=now, event_type="voice_pause", data={"asr_text": text})
        )

        if not is_final:
            return None

        # 唤醒词检测（第一层兜底，避免彻底无法唤醒）
        is_wake = self._detect_wake_word(text)

        async with self._lock:
            if is_wake:
                # 唤醒请求：强制高优先级，让 LLM 决定具体内容
                return await self._generate_suggestion(
                    trigger_text=f"[WAKE] {text}",
                    image_base64=None,
                    priority="high",
                    is_wake_request=True,
                )
            return await self._handle_voice_request(text)

    async def on_explicit_request(
        self, text: str, image_base64: str | None = None
    ) -> dict[str, Any] | None:
        """处理教师的显式请求（如点击"请教助教"按钮）。"""
        if not self._active:
            return None
        async with self._lock:
            return await self._generate_suggestion(
                trigger_text=text,
                image_base64=image_base64,
                priority="high",
            )

    async def on_mouse_lasso(
        self, region: dict[str, Any], image_base64: str | None = None
    ) -> dict[str, Any] | None:
        """处理鼠标框选事件。"""
        if not self._active:
            return None

        from .trigger_engine import ContextEvent

        decision = self.trigger_engine.on_event(
            ContextEvent(
                timestamp=time.time(),
                event_type="lasso",
                data={"region": region, "image_base64": image_base64},
            )
        )
        if decision and decision.priority == TriggerPriority.HIGH:
            async with self._lock:
                return await self._generate_suggestion(
                    trigger_text="教师框选了课件内容",
                    image_base64=image_base64,
                    priority="high",
                    region=region,
                )
        return None

    # ── Barge-in 打断续接 ──

    def on_barge_in(self, spoken_bytes: int, total_bytes: int) -> None:
        """处理教师打断事件。

        将已播报内容作为 assistant 记录到上下文，未播报内容标记为
        "打断而未表达"，让 LLM 充分了解打断位置。
        """
        content = self._current_tts_content
        if not content or total_bytes <= 0:
            return

        ratio = max(0.0, min(1.0, spoken_bytes / float(total_bytes)))
        cut = int(len(content) * ratio)
        spoken_text = content[:cut].strip()
        remaining_text = content[cut:].strip()

        # 已播报内容加入历史，未播报内容存入缓冲区
        self.context.mark_interrupted(spoken_text, remaining_text)
        logger.info(
            "RTA barge-in for user=%s: spoken=%d chars, remaining=%d chars",
            self.user_id,
            len(spoken_text),
            len(remaining_text),
        )

        # 清空当前 TTS 状态
        self._current_tts_content = ""
        self._current_tts_total_bytes = 0
        self._current_tts_sent_bytes = 0

    def on_tts_progress(self, sent_bytes: int, total_bytes: int) -> None:
        """更新 TTS 播报进度（前端通过 WebSocket 上报）。"""
        self._current_tts_sent_bytes = sent_bytes
        self._current_tts_total_bytes = total_bytes

    def close(self) -> None:
        """关闭会话，释放资源。"""
        self._active = False
        self.context.turns = []
        logger.info("RTA session closed for user=%s", self.user_id)

    # ── 内部处理链路 ──

    async def _handle_screen_frame(self, image_base64: str) -> dict[str, Any] | None:
        """屏幕帧内部处理：变化检测 → OCR → 对比 → 触发分析。"""
        # 1. 屏幕变化检测（在字节层面做快速过滤）
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            logger.warning("Invalid base64 image from user=%s", self.user_id)
            return None

        change = self.screen_detector.detect_change(image_bytes)
        if not change.changed:
            logger.debug("Screen unchanged for user=%s", self.user_id)
            return None

        # 2. OCR（复用现有能力）
        ocr_text = ""
        try:
            ocr_text = ocr_image_base64(image_base64, language=self.config.ocr_language)
            ocr_text = (ocr_text or "").strip()
        except Exception as exc:
            logger.warning("OCR failed for user=%s: %s", self.user_id, exc)

        # 3. 与上一次 OCR 结果对比（编辑距离代理）
        if ocr_text and self._text_similarity(ocr_text, self.frame_state.last_ocr_text) > 0.85:
            logger.debug("OCR text similar to previous, skip analysis for user=%s", self.user_id)
            return None

        self.frame_state.last_ocr_text = ocr_text
        self.frame_state.last_ocr_timestamp = time.time()
        self.frame_state.frame_counter += 1

        # 4. 触发 LLM 分析（用 OCR 文本 + 可选图片）
        return await self._generate_suggestion(
            trigger_text=f"课件内容：{ocr_text[:300]}" if ocr_text else "课件画面",
            image_base64=image_base64,
            priority="medium",
        )

    async def _handle_voice_request(self, text: str) -> dict[str, Any] | None:
        """语音请求内部处理：主动建议检测 → 让 LLM 决策是否介入。"""
        suggestion = self.suggestion_engine.on_asr_result(text, True, time.time())
        if not suggestion:
            return None

        # 所有语音触发都交给 LLM 做最终决策（是否介入、是否 TTS）
        priority_map = {
            SuggestionType.ON_DEMAND: "high",
            SuggestionType.PROACTIVE_ALERT: "high",
            SuggestionType.PROACTIVE_ASSIST: "medium",
            SuggestionType.PROACTIVE_HINT: "low",
        }
        return await self._generate_suggestion(
            trigger_text=text,
            image_base64=None,
            priority=priority_map.get(suggestion.type, "medium"),
        )

    async def _generate_suggestion(
        self,
        *,
        trigger_text: str,
        image_base64: str | None,
        priority: str,
        region: dict[str, Any] | None = None,
        is_wake_request: bool = False,
    ) -> dict[str, Any] | None:
        """核心链路：组装 Prompt → LLM → 解析决策 → 条件 TTS → 返回 payload。

        关键行为：
        - LLM 返回 JSON 决策：should_intervene / use_tts / content / urgency
        - 默认不 TTS，只有 LLM 明确 use_tts=true 时才合成音频
        - 如果 LLM 判断 should_intervene=false，返回 None（前端无感）
        - 唤醒请求失败时有兜底响应
        """
        now = time.time()
        if now - self._last_trigger_time < self.config.cooldown_seconds:
            logger.debug("Cooldown active for user=%s", self.user_id)
            return None
        self._last_trigger_time = now

        # 1. 组装 Prompt
        user_prompt = self._build_user_prompt(trigger_text, region)

        # 2. LLM 调用（优先多模态；无图或失败时降级到纯文本）
        llm_raw = ""
        use_image = bool(image_base64) and priority in ("high", "medium")

        if use_image:
            llm_raw = await chat_complete_multimodal(
                system_prompt=self.SYSTEM_PROMPT,
                user_text=user_prompt,
                image_base64=image_base64,
                history=self.context.to_history(),
                model=self.config.llm_model,
                base_url=self.config.llm_base_url or None,
                api_key=self.config.llm_api_key or None,
                timeout_seconds=self.config.llm_timeout,
                temperature=0.5,
                max_tokens=400,
            )

        def _is_degraded_reply(text: str) -> bool:
            return (not text) or ("网络不太稳定" in text) or ("LLM 输出为空" in text)

        if _is_degraded_reply(llm_raw):
            # 先复用场景对话链路中的云+本地竞速能力。
            llm_raw = await chat_complete_race(
                system_prompt=self.SYSTEM_PROMPT,
                user_text=user_prompt,
                history=self.context.to_history(),
                temperature=0.7,
            )

        if _is_degraded_reply(llm_raw):
            # 竞速仍失败时，保留原有云优先超时回退策略作为最后兜底。
            llm_raw = await chat_complete_cloud_first(
                system_prompt=self.SYSTEM_PROMPT,
                user_text=user_prompt,
                history=self.context.to_history(),
                temperature=0.7,
                timeout_seconds=1.0,
            )

        # 3. 解析 LLM 决策
        decision = self._extract_rta_decision(llm_raw)

        # 4. LLM 不可用时的兜底
        if _is_degraded_reply(llm_raw):
            if is_wake_request:
                # 唤醒请求必须响应，使用兜底文本并可 TTS
                decision = {
                    "should_intervene": True,
                    "intervention_type": "answer",
                    "content": self.WAKE_FALLBACK_TEXT,
                    "use_tts": True,
                    "urgency": "high",
                }
            else:
                # 非唤醒请求：静默失败，不打扰课堂
                logger.info("LLM unavailable for user=%s, staying silent", self.user_id)
                return None

        # 5. LLM 决策：不介入 → 静默
        if not decision.get("should_intervene"):
            logger.info("LLM decided not to intervene for user=%s", self.user_id)
            # 仍更新上下文，让 LLM 记住观察历史
            self.context.append("user", trigger_text)
            self.context.append("assistant", "[silent]")
            return None

        content = decision.get("content", "")
        use_tts = decision.get("use_tts", False)
        urgency = decision.get("urgency", priority)

        # 6. 更新上下文（只记录实际介入的内容）
        # 如果有打断缓冲区，说明上一轮被打断，本轮 LLM 已基于未播报内容生成新回复
        # 清除打断状态，避免重复注入
        self.context.clear_interruption()
        self.context.append("user", trigger_text)
        self.context.append("assistant", content)

        # 7. TTS 合成（仅当 LLM 明确要求时才执行）
        audio_base64 = ""
        audio_bytes = b""
        if self.config.tts_enabled and use_tts and content:
            try:
                audio_bytes = await asyncio.to_thread(synthesize_tts_wav, content)
                if audio_bytes:
                    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                    # 记录当前 TTS 内容用于打断续接
                    self._current_tts_content = content
                    self._current_tts_total_bytes = len(audio_bytes)
                    self._current_tts_sent_bytes = 0
            except Exception as exc:
                logger.warning("TTS failed for user=%s: %s", self.user_id, exc)

        # 8. 组装返回 payload
        payload: dict[str, Any] = {
            "type": "suggestion",
            "priority": urgency,
            "content": content,
            "has_audio": bool(audio_base64),
            "should_intervene": True,
            "intervention_type": decision.get("intervention_type", "hint"),
        }
        if audio_base64:
            payload["audio_base64"] = audio_base64
            payload["audio_format"] = "wav"
            payload["tts_total_bytes"] = len(audio_bytes)

        logger.info(
            "RTA suggestion generated for user=%s priority=%s intervene=%s use_tts=%s has_audio=%s",
            self.user_id,
            urgency,
            True,
            use_tts,
            payload["has_audio"],
        )
        return payload

    # ── 工具方法 ──

    def _build_user_prompt(self, trigger_text: str, region: dict[str, Any] | None) -> str:
        parts: list[str] = []

        # 注入打断续接上下文（如果有未播报内容）
        interruption_ctx = self.context.get_interruption_context()
        if interruption_ctx:
            parts.append(interruption_ctx)

        if trigger_text.startswith("[WAKE] "):
            actual = trigger_text.removeprefix("[WAKE] ")
            parts.append(f"[显式唤醒] 教师说：{actual}")
            parts.append("这是唤醒请求，请简短响应确认你在听，并询问需要什么帮助。")
        else:
            parts.append(f"教师当前讲解/提问：{trigger_text}")
        if region:
            parts.append(
                f"教师框选了课件区域：x={region.get('x1')}-{region.get('x2')}, "
                f"y={region.get('y1')}-{region.get('y2')}"
            )
        parts.append(
            "请基于以上内容做出判断：是否需要介入？如果需要，请给出简短口语化建议；"
            "如果不需要，请返回 should_intervene=false。"
        )
        return "\n".join(parts)

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """简单 Jaccard 相似度。"""
        sa, sb = set(a.lower().split()), set(b.lower().split())
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union else 0.0

    # ── 唤醒词检测 ──

    @staticmethod
    def _detect_wake_word(text: str) -> bool:
        """检测唤醒词 'Hi Helix' / 'Hey Helix'，含智能兜底机制。

        兜底策略（避免彻底无法唤醒）：
        1. 精确包含：hi helix / hey helix
        2. 音似容错：high helix / hay helix / hi heliks / hey heliks
        3. 分离匹配：文本中同时包含 helix 和 hi/hey/high/hay
        4. 兜底：只要包含 helix（ASR 可能漏掉前半部分）
        """
        import re

        t = (text or "").lower()
        # 去除常见标点
        t_clean = re.sub(r"[^\w\s]", " ", t)
        words = set(t_clean.split())

        # 1. 精确包含（空格或标点分隔）
        exact_patterns = ["hi helix", "hey helix"]
        if any(p in t for p in exact_patterns):
            return True

        # 2. 音似容错（编辑距离 <= 2 的近似匹配）
        def _levenshtein(a: str, b: str) -> int:
            if len(a) < len(b):
                return _levenshtein(b, a)
            if not b:
                return len(a)
            prev = list(range(len(b) + 1))
            for i, ca in enumerate(a):
                curr = [i + 1]
                for j, cb in enumerate(b):
                    curr.append(
                        min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1))
                    )
                prev = curr
            return prev[-1]

        # 将文本按 2-3 词窗口滑动，检查与唤醒词的编辑距离
        word_list = t_clean.split()
        for i in range(len(word_list) - 1):
            bigram = f"{word_list[i]} {word_list[i + 1]}"
            for pat in exact_patterns:
                if _levenshtein(bigram, pat) <= 2:
                    return True

        # 3. 分离匹配：包含 helix + hi/hey/high/hay
        helix_aliases = {"helix", "heliks", "helixs", "helics"}
        wake_aliases = {"hi", "hey", "high", "hay", "hai"}
        if any(w in words for w in helix_aliases) and any(w in words for w in wake_aliases):
            return True

        # 4. 最终兜底：只要包含 helix（避免 ASR 漏前半部分导致彻底无法唤醒）
        if "helix" in t:
            return True

        return False

    # ── LLM 决策解析 ──

    @staticmethod
    def _extract_rta_decision(text: str) -> dict[str, Any]:
        """从 LLM 输出中提取结构化决策。容错处理非 JSON / 非结构化输出。"""
        import json as _json
        import re

        s = (text or "").strip()
        if not s:
            return {
                "should_intervene": False, "content": "",
                "use_tts": False, "urgency": "low",
                "intervention_type": "none",
            }

        # 1. 从 markdown code block 中提取
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if m:
            s = m.group(1).strip()

        # 2. 尝试直接解析 JSON
        try:
            obj = _json.loads(s)
            if isinstance(obj, dict):
                return RealtimeAssistantSession._normalize_decision(obj)
        except Exception:
            pass

        # 3. 尝试提取最大的 {...} 块
        start = s.find("{")
        end = s.rfind("}")
        if 0 <= start < end:
            try:
                obj = _json.loads(s[start : end + 1])
                if isinstance(obj, dict):
                    return RealtimeAssistantSession._normalize_decision(obj)
            except Exception:
                pass

        # 4. 兜底推断：如果输出是中文建议文本（有中文且长度适中），视为 should_intervene=true
        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in s)
        if has_chinese and 20 < len(s) < 500:
            lower = s.lower()
            use_tts = any(k in lower for k in ["播报", "朗读", "请听", "注意听"])
            return {
                "should_intervene": True,
                "intervention_type": "hint",
                "content": s,
                "use_tts": use_tts,
                "urgency": "medium",
            }

        return {
            "should_intervene": False, "content": "",
            "use_tts": False, "urgency": "low",
            "intervention_type": "none",
        }

    @staticmethod
    def _normalize_decision(obj: dict[str, Any]) -> dict[str, Any]:
        should = bool(obj.get("should_intervene", False))
        content = str(obj.get("content") or "").strip()
        use_tts = bool(obj.get("use_tts", False)) if should else False
        urgency = str(obj.get("urgency") or "medium").lower()
        itype = str(obj.get("intervention_type") or "hint").lower()
        if urgency not in ("high", "medium", "low"):
            urgency = "medium"
        if itype not in ("hint", "correction", "answer", "encouragement", "none"):
            itype = "hint"
        return {
            "should_intervene": should,
            "intervention_type": itype,
            "content": content,
            "use_tts": use_tts,
            "urgency": urgency,
        }
