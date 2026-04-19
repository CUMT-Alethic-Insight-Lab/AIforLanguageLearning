"""Agent-0: 历史总结引擎 — 每日为学生生成纵向摘要。"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from ...domain.analytics.models import StudentDailySummary
from ...domain.models import LearningRecord, StudentProfile, VocabularyItem
from ...llm import chat_complete, chat_complete_cloud_first
from ...models import ConversationEvent, EssayResult, EssaySubmission, UserVocabQuery
from ._text_analysis import (
    analyze_morph_transfer,
    analyze_sentence_diversity,
    estimate_advanced_vocab_substitution,
)

logger = logging.getLogger(__name__)

METRIC_METHODS: dict[str, dict[str, str]] = {
    "vocab_growth_rate": {"mode": "no_llm", "reason": "直接基于词汇表增长与时间窗口统计"},
    "sm2_retention_rate": {"mode": "no_llm", "reason": "直接基于 SM-2 复习状态计算"},
    "active_lookup_conversion": {"mode": "no_llm", "reason": "查词记录与词表落库直接关联"},
    "morph_transfer_ability": {"mode": "automation_assisted", "reason": "基于作文结构化评分做规则映射"},
    "long_term_memory_robustness": {"mode": "no_llm", "reason": "直接统计长间隔仍保留的词汇项"},
    "grammar_error_decay_slope": {"mode": "no_llm", "reason": "基于连续作文维度分数斜率"},
    "advanced_vocab_substitution": {"mode": "automation_assisted", "reason": "基于作文分项分数与替代率规则估计"},
    "msl_diversity_index": {"mode": "automation_assisted", "reason": "基于作文结构化结果和句式代理指标"},
    "logical_coherence_trend": {"mode": "automation_assisted", "reason": "使用作文结构分数与趋势规则"},
    "semantic_accuracy_trend": {"mode": "automation_assisted", "reason": "使用作文语义维度分数聚合"},
    "response_latency_avg_ms": {"mode": "no_llm", "reason": "直接来自对话事件埋点"},
    "speech_wpm": {"mode": "no_llm", "reason": "直接由 ASR 文本词数和音频时长计算"},
    "difficulty_jump_success": {"mode": "automation_assisted", "reason": "场景难度启发式 + 对话完成质量规则"},
    "cross_cultural_deviation": {"mode": "llm_required", "reason": "文化得体性需要语义与语境判断，规则仅做候选筛选"},
    "paraphrase_count": {"mode": "automation_assisted", "reason": "基于转述标记词和事件统计"},
    "learning_stability_std": {"mode": "no_llm", "reason": "基于近7日学习记录频次标准差"},
    "error_regression_rate": {"mode": "no_llm", "reason": "基于复习错题记录直接统计"},
    "feedback_response_depth": {"mode": "automation_assisted", "reason": "基于连续作文进步与复习行为估计反馈采纳深度"},
    "topic_coverage_breadth": {"mode": "automation_assisted", "reason": "场景/词汇主题规则聚类，无需 LLM 全量参与"},
    "autonomous_drive_count": {"mode": "no_llm", "reason": "主动查词/生成/复习记录直接计数"},
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "daily_life": ("daily", "weekend", "grocery", "routine", "neighbor", "budget", "commute", "home"),
    "travel": ("travel", "airport", "hotel", "boarding", "customs", "destination", "trip", "ticket"),
    "business": ("business", "meeting", "agenda", "proposal", "deadline", "stakeholder", "invoice", "client"),
    "academic": ("academic", "research", "thesis", "lecture", "seminar", "curriculum", "citation", "exam"),
    "social": ("party", "friend", "dating", "small talk", "conversation", "introduce", "greet"),
    "food_service": ("restaurant", "menu", "order", "coffee", "cafe", "dish", "bill", "reservation"),
    "technology": ("technology", "software", "app", "code", "ai", "robot", "device", "computer"),
    "culture": ("host family", "festival", "cultural", "polite", "礼貌", "custom", "礼仪", "跨文化"),
}

CULTURAL_SCENARIO_KEYWORDS = (
    "host family",
    "interview",
    "customs",
    "small talk",
    "restaurant",
    "cafe",
    "negotiation",
    "meeting",
    "festival",
    "礼貌",
    "礼仪",
    "文化",
)

# ───────────────────────────────────────────────
# 数据收集接口（预留/占位）
# 说明：以下接口定义了理论上可收集的数据源。
# 当 Neo4j KG、Redis 活跃度统计、ASR 细粒度事件等模块就绪后，
# 替换对应占位实现即可，无需改动整体流程。
# ───────────────────────────────────────────────


def _collect_vocab_items(user_id: int, target_date: date, session: Session) -> list[VocabularyItem]:
    """获取用户截至 target_date 的所有词汇记录。"""
    next_day = datetime.combine(target_date, datetime.min.time()) + timedelta(days=1)
    stmt = (
        select(VocabularyItem)
        .where(VocabularyItem.user_id == user_id)
        .where(VocabularyItem.created_at < next_day)
    )
    return list(session.exec(stmt))


def _collect_essay_results(user_id: int, target_date: date, session: Session) -> list[EssayResult]:
    """获取用户截至 target_date 的所有作文批改结果。"""
    next_day = datetime.combine(target_date, datetime.min.time()) + timedelta(days=1)
    stmt = (
        select(EssayResult)
        .join(EssaySubmission, EssaySubmission.id == EssayResult.submission_id)
        .where(EssaySubmission.user_id == user_id)
        .where(EssayResult.created_at < next_day)
    )
    return list(session.exec(stmt))


def _collect_essay_submissions(user_id: int, target_date: date, session: Session) -> list[EssaySubmission]:
    """获取用户截至 target_date 的所有作文提交。"""
    next_day = datetime.combine(target_date, datetime.min.time()) + timedelta(days=1)
    stmt = (
        select(EssaySubmission)
        .where(EssaySubmission.user_id == user_id)
        .where(EssaySubmission.created_at < next_day)
    )
    return list(session.exec(stmt))


def _collect_conversation_events(
    user_id: int, target_date: date, session: Session
) -> list[ConversationEvent]:
    """获取用户 target_date 当天的对话事件。"""
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(ConversationEvent)
        .where(ConversationEvent.user_id == user_id)
        .where(ConversationEvent.created_at >= day_start)
        .where(ConversationEvent.created_at < day_end)
    )
    return list(session.exec(stmt))


def _collect_vocab_queries(user_id: int, target_date: date, session: Session) -> list[UserVocabQuery]:
    """获取用户 target_date 当天的查词记录。"""
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(UserVocabQuery)
        .where(UserVocabQuery.user_id == user_id)
        .where(UserVocabQuery.created_at >= day_start)
        .where(UserVocabQuery.created_at < day_end)
    )
    return list(session.exec(stmt))


def _collect_learning_records(
    user_id: int, target_date: date, session: Session
) -> list[LearningRecord]:
    """获取用户 target_date 当天的通用学习记录。"""
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(LearningRecord)
        .where(LearningRecord.user_id == user_id)
        .where(LearningRecord.created_at >= day_start)
        .where(LearningRecord.created_at < day_end)
    )
    return list(session.exec(stmt))


def _collect_learning_records_window(
    user_id: int, target_date: date, session: Session, window_days: int = 7
) -> list[LearningRecord]:
    """获取用户截至 target_date 的近 N 日学习记录。"""
    day_end = datetime.combine(target_date, datetime.min.time()) + timedelta(days=1)
    day_start = day_end - timedelta(days=max(1, window_days))
    stmt = (
        select(LearningRecord)
        .where(LearningRecord.user_id == user_id)
        .where(LearningRecord.created_at >= day_start)
        .where(LearningRecord.created_at < day_end)
    )
    return list(session.exec(stmt))


def get_metric_methodology() -> dict[str, dict[str, str]]:
    return {key: dict(value) for key, value in METRIC_METHODS.items()}


def _tokenize_text(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z\u4e00-\u9fff]+", (text or "").lower()) if token]


def _classify_topic_labels(*texts: str) -> list[str]:
    haystack = " ".join(str(text or "").lower() for text in texts if text).strip()
    if not haystack:
        return []

    labels: set[str] = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            labels.add(topic)

    if labels:
        return sorted(labels)

    tokens = _tokenize_text(haystack)
    if any(token in {"school", "class", "homework", "teacher"} for token in tokens):
        return ["academic"]
    if any(token in {"airport", "train", "visa"} for token in tokens):
        return ["travel"]
    return ["general"]


def _estimate_scenario_difficulty(text: str) -> int:
    haystack = str(text or "").strip().lower()
    if not haystack:
        return 1

    difficulty = 1
    if len(haystack) >= 60:
        difficulty += 1
    if len(haystack) >= 120:
        difficulty += 1
    if any(keyword in haystack for keyword in ("negotiation", "presentation", "interview", "academic", "debate")):
        difficulty += 1
    if any(keyword in haystack for keyword in ("跨文化", "cultural", "host family", "礼貌", "customs")):
        difficulty += 1
    return max(1, min(5, difficulty))


# ───────────────────────────────────────────────
# 维度计算（含冷启动保护）
# ───────────────────────────────────────────────


def _calc_vocab_growth_rate(vocab_items: list[VocabularyItem]) -> float | None:
    """A1: 词汇熟练度增长率。"""
    if not vocab_items:
        return None
    levels = [v.mastery_level for v in vocab_items]
    return round(sum(levels) / max(len(levels), 1), 4)


def _calc_sm2_retention(vocab_items: list[VocabularyItem]) -> float | None:
    """A2: SM-2 复习遗忘抑制比（简化版：已掌握词汇占比）。"""
    if not vocab_items:
        return None
    mastered = sum(1 for v in vocab_items if v.mastery_level >= 3)
    return round(mastered / len(vocab_items), 4)


def _calc_lookup_conversion(
    queries: list[UserVocabQuery], vocab_items: list[VocabularyItem]
) -> float | None:
    """A3: 主动查词转化率。"""
    if not queries:
        return None
    query_terms = {q.term.lower().strip() for q in queries}
    vocab_words = {v.word.lower().strip() for v in vocab_items if v.mastery_level > 3}
    converted = query_terms & vocab_words
    return round(len(converted) / len(query_terms), 4)


def _calc_morph_transfer_ability(
    essay_submissions: list[EssaySubmission],
    vocab_items: list[VocabularyItem],
) -> float | None:
    """A4: 构词法迁移能力。

    基于作文文本中未学过但含已学词根的新词比例。
    无作文或词汇数据时返回 None（冷启动保护）。
    """
    if not essay_submissions or not vocab_items:
        return None

    learned_words = {v.word.strip().lower() for v in vocab_items if v.word}
    all_text = " ".join(s.ocr_text or "" for s in essay_submissions)
    result = analyze_morph_transfer(all_text, learned_words)
    return result.get("transfer_ratio")


def _calc_long_term_memory(vocab_items: list[VocabularyItem]) -> int | None:
    """A5: 长时记忆健壮度（进入长复习周期的单词数）。"""
    if not vocab_items:
        return None
    one_year_later = datetime.utcnow() + timedelta(days=365)
    return sum(1 for v in vocab_items if v.next_review_at >= one_year_later)


def _calc_grammar_error_decay(essay_results: list[EssayResult]) -> float | None:
    """A6: 语法错误收敛速度（最近5篇 grammar 分数变化斜率）。"""
    scores: list[float] = []
    for er in sorted(essay_results, key=lambda x: x.created_at)[-5:]:
        dims = (er.result or {}).get("dimensions", {})
        g = dims.get("grammar")
        if isinstance(g, (int, float)):
            scores.append(float(g))
    if len(scores) < 2:
        return None
    # 简单线性斜率：(末 - 首) / (n - 1)
    return round((scores[-1] - scores[0]) / max(len(scores) - 1, 1), 4)


def _calc_advanced_vocab_substitution(
    essay_results: list[EssayResult],
    essay_submissions: list[EssaySubmission],
) -> float | None:
    """A7: 高级词汇替代率。

    优先使用 EssayResult.dimensions.vocabulary 分数；
    若无，则基于作文文本中高级形态词汇比例做代理估计。
    """
    if not essay_results and not essay_submissions:
        return None

    # 优先取最新作文的 vocabulary 维度
    latest_result = max(essay_results, key=lambda x: x.created_at) if essay_results else None
    latest_submission = max(essay_submissions, key=lambda x: x.created_at) if essay_submissions else None
    essay_text = latest_submission.ocr_text if latest_submission else ""
    result = estimate_advanced_vocab_substitution(
        essay_text,
        latest_result.result if latest_result else None,
    )
    return result.get("substitution_rate")


def _calc_msl_diversity(essay_submissions: list[EssaySubmission]) -> float | None:
    """A8: 句式多样性指数 (MSL)。

    基于作文文本的句长标准差和复合句占比做轻量规则估计。
    """
    if not essay_submissions:
        return None

    all_text = " ".join(s.ocr_text or "" for s in essay_submissions)
    result = analyze_sentence_diversity(all_text)
    return result.get("diversity_index")


def _calc_logical_coherence(essay_results: list[EssayResult]) -> float | None:
    """A9: 逻辑衔接连贯度（最近5篇 structure 维度趋势）。"""
    scores: list[float] = []
    for er in sorted(essay_results, key=lambda x: x.created_at)[-5:]:
        dims = (er.result or {}).get("dimensions", {})
        s = dims.get("structure")
        if isinstance(s, (int, float)):
            scores.append(float(s))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _calc_semantic_accuracy(essay_results: list[EssayResult]) -> float | None:
    """A10: 语义表达准确性（最近5篇 language 维度均值，越低越好，取反）。"""
    scores: list[float] = []
    for er in sorted(essay_results, key=lambda x: x.created_at)[-5:]:
        dims = (er.result or {}).get("dimensions", {})
        l = dims.get("language")
        if isinstance(l, (int, float)):
            scores.append(float(l))
    if not scores:
        return None
    avg = sum(scores) / len(scores)
    # 转换为"越高越好"方向（假设满分 100）
    return round(100 - avg, 4)


def _calc_response_latency(events: list[ConversationEvent]) -> int | None:
    """A11: 对话响应潜伏期（ms，简化：ASR_START 到 AI_MESSAGE 的间隔）。"""
    if not events:
        return None
    latencies: list[int] = []
    for event in events:
        payload = event.payload or {}
        latency = payload.get("response_latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(int(latency))
    if not latencies:
        return None
    return int(sum(latencies) / len(latencies))


def _calc_speech_wpm(events: list[ConversationEvent]) -> float | None:
    """A12: 语音产出速率（WPM，预留 — 需 ASR 文本时长精确计算）。"""
    samples: list[float] = []
    for event in events:
        if event.type != "USER_MESSAGE":
            continue
        payload = event.payload or {}
        duration_ms = payload.get("audio_duration_ms")
        word_count = payload.get("word_count")
        if not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
            continue
        if not isinstance(word_count, (int, float)) or word_count <= 0:
            continue
        minutes = float(duration_ms) / 60000.0
        if minutes <= 0:
            continue
        samples.append(float(word_count) / minutes)
    if not samples:
        return None
    return round(sum(samples) / len(samples), 4)


def _calc_difficulty_jump_success(events: list[ConversationEvent]) -> float | None:
    """A13: 对话难度跳变成功率。

    启发式规则：
    - 仅统计场景复杂度 >= 4 的用户回合，避免简单寒暄稀释结果；
    - 认为“成功”需同时满足：用户有足够输出、AI 正常响应且延迟不过长。
    """
    attempts = 0
    successes = 0
    for event in events:
        if event.type != "USER_MESSAGE":
            continue
        payload = event.payload or {}
        scenario = str(payload.get("scenario") or "").strip()
        difficulty = _estimate_scenario_difficulty(scenario)
        if difficulty < 4:
            continue

        attempts += 1
        word_count = payload.get("word_count")
        latency = payload.get("response_latency_ms")
        if not isinstance(word_count, (int, float)) or word_count < 4:
            continue
        if isinstance(latency, (int, float)) and latency > 8000:
            continue
        successes += 1
    if attempts == 0:
        return None
    return round(successes / attempts, 4)


def _calc_cross_cultural_deviation(events: list[ConversationEvent]) -> float | None:
    """A14: 跨文化得体性偏离值。

    该维度默认依赖 LLM 评估；若会话中已写回结构化评估结果，则直接复用。
    """
    samples: list[float] = []
    for event in events:
        payload = event.payload or {}
        score = payload.get("cross_cultural_deviation")
        if isinstance(score, (int, float)):
            samples.append(float(score))
    if not samples:
        return None
    return round(sum(samples) / len(samples), 4)


def _calc_paraphrase_count(events: list[ConversationEvent]) -> int | None:
    """A15: 口语解释/转述能力（预留 — 需意图识别标记）。"""
    total = 0
    for event in events:
        if event.type != "USER_MESSAGE":
            continue
        payload = event.payload or {}
        markers = payload.get("paraphrase_markers")
        if isinstance(markers, (int, float)):
            total += int(markers)
    return total if total > 0 else None


def _calc_learning_stability(records: list[LearningRecord]) -> float | None:
    """A16: 学习行为稳定性（近7日学习记录频次标准差，越小越稳）。"""
    if not records:
        return None
    daily_counts: dict[date, int] = {}
    for record in records:
        day = record.created_at.date()
        daily_counts[day] = daily_counts.get(day, 0) + 1
    if len(daily_counts) <= 1:
        return 0.0
    values = list(daily_counts.values())
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return round(math.sqrt(variance), 4)


def _calc_error_regression_rate(records: list[LearningRecord]) -> float | None:
    """A17: 错误复发率（近7日复习中错误占比）。"""
    review_records = [
        record
        for record in records
        if record.type == "vocabulary" and str((record.meta_data or {}).get("action") or "") == "review"
    ]
    if not review_records:
        return None
    wrong = 0
    total = 0
    for record in review_records:
        meta = record.meta_data or {}
        correct = meta.get("correct")
        if isinstance(correct, bool):
            total += 1
            if not correct:
                wrong += 1
    if total == 0:
        return None
    return round(wrong / total, 4)


def _calc_feedback_response_depth(essay_results: list[EssayResult], records: list[LearningRecord]) -> float | None:
    """A18: 反馈响应深度。

    以“连续作文是否提升”+“是否存在复习/查词跟进行为”做轻量估计。
    """
    if len(essay_results) < 2:
        return None
    sorted_results = sorted(essay_results, key=lambda item: item.created_at)
    improvements: list[int] = []
    for prev, curr in zip(sorted_results, sorted_results[1:]):
        improvements.append(1 if int(curr.score or 0) > int(prev.score or 0) else 0)
    if not improvements:
        return None

    follow_up_actions = sum(
        1
        for record in records
        if record.type in {"vocabulary", "dialogue"} and str((record.meta_data or {}).get("action") or "") in {"review", "lookup", "lookup_ocr"}
    )
    base = sum(improvements) / len(improvements)
    depth = base * 0.7 + min(1.0, follow_up_actions / 5.0) * 0.3
    return round(depth, 4)


def _calc_topic_coverage_breadth(
    vocab_items: list[VocabularyItem],
    queries: list[UserVocabQuery],
    events: list[ConversationEvent],
    records: list[LearningRecord],
) -> int | None:
    """A19: 主题覆盖广度（主题桶数量）。"""
    labels: set[str] = set()

    for item in vocab_items[-50:]:
        labels.update(_classify_topic_labels(item.word, item.definition, item.example))
    for query in queries:
        meta = query.meta_data or {}
        labels.update(_classify_topic_labels(query.term, query.result, meta.get("theme") or "", meta.get("scenario") or ""))
    for event in events:
        payload = event.payload or {}
        labels.update(_classify_topic_labels(payload.get("scenario") or "", payload.get("text") or ""))
    for record in records:
        meta = record.meta_data or {}
        labels.update(_classify_topic_labels(record.content, meta.get("theme") or "", meta.get("scenario") or ""))

    labels.discard("general")
    return len(labels) if labels else None


def _calc_autonomous_drive(queries: list[UserVocabQuery], records: list[LearningRecord]) -> int | None:
    """A20: 自主学习驱动力（预留 — 需主动生成主题词汇记录）。"""
    if not queries and not records:
        return None
    count = 0
    for query in queries:
        meta = query.meta_data or {}
        action = str(meta.get("action") or "").strip().lower()
        source = str(query.source or "").strip().lower()
        if source in {"manual", "ocr"} or action in {"generate_vocab", "lookup", "lookup_ocr"}:
            count += 1
    for record in records:
        meta = record.meta_data or {}
        action = str(meta.get("action") or "").strip().lower()
        if action in {"generate_vocab", "lookup", "lookup_ocr", "review"}:
            count += 1
    return count if count > 0 else None


# ───────────────────────────────────────────────
# 主入口
# ───────────────────────────────────────────────


async def _generate_llm_daily_narrative(
    user_id: int,
    target_date: date,
    profile: StudentProfile | None,
    metrics: dict[str, Any],
) -> str | None:
    """使用本地 LLM 生成个性化日度分析摘要。

    结合用户画像（level、goals、interests）和当日数据，
    生成教师友好的自然语言分析。
    """
    system_prompt = (
        "你是一位资深外语教学分析师。请根据学生的画像和当日学习数据，"
        "生成一段个性化的学情分析摘要。要求：\n"
        "1. 结合学生的英语水平、学习目标、兴趣爱好\n"
        "2. 不使用行业黑话，用通俗的教学语言\n"
        "3. 客观总结当日表现，不夸大不贬低\n"
        "4. 给出 1-2 条与目标/兴趣相关的个性化建议\n"
        "5. 控制在 150 字以内"
    )

    user_text = (
        f"学生ID: {user_id}\n"
        f"日期: {target_date}\n"
        f"英语水平: {profile.level if profile else '未知'}\n"
        f"学习目标: {', '.join(profile.goals) if profile and profile.goals else '未设置'}\n"
        f"兴趣爱好: {', '.join(profile.interests) if profile and profile.interests else '未设置'}\n"
        f"当日数据:\n"
        f"- 词汇增长: {metrics.get('vocab_growth_rate')}\n"
        f"- 语法收敛: {metrics.get('grammar_error_decay_slope')}\n"
        f"- 逻辑连贯: {metrics.get('logical_coherence_trend')}\n"
        f"- 学习稳定: {metrics.get('learning_stability_std')}\n"
        f"- 主题覆盖: {metrics.get('topic_coverage_breadth')}\n"
        f"- 自主学习: {metrics.get('autonomous_drive_count')}"
    )

    try:
        response = await chat_complete_cloud_first(
            system_prompt=system_prompt,
            user_text=user_text,
            timeout_seconds=10.0,
        )
        if response and "网络不太稳定" not in response:
            return response
    except Exception as exc:
        logger.warning("LLM daily narrative failed for user %s: %s", user_id, exc)
    return None


async def _llm_assess_cross_cultural_deviation(events: list[ConversationEvent]) -> float | None:
    """仅在跨文化/社交敏感场景下调用 LLM 做轻量评估。"""
    samples: list[str] = []
    for event in events:
        if event.type != "USER_MESSAGE":
            continue
        payload = event.payload or {}
        scenario = str(payload.get("scenario") or "").strip()
        text = str(payload.get("text") or "").strip()
        haystack = f"{scenario}\n{text}".lower()
        if not text:
            continue
        if any(keyword in haystack for keyword in CULTURAL_SCENARIO_KEYWORDS):
            samples.append(f"场景: {scenario}\n学生表达: {text}")
        if len(samples) >= 3:
            break

    if not samples:
        return None

    system_prompt = (
        "你是一位跨文化交际教学分析师。请基于给出的学习者表达片段，"
        "判断其在礼貌、语域、文化得体性上是否存在偏离。"
        "只输出 0 到 100 的数字，数值越高表示偏离越大。"
    )
    user_text = "\n\n".join(samples)
    try:
        response = await chat_complete_cloud_first(system_prompt=system_prompt, user_text=user_text, timeout_seconds=10.0)
        match = re.search(r"(\d+(?:\.\d+)?)", str(response or ""))
        if not match:
            return None
        score = float(match.group(1))
        return round(max(0.0, min(100.0, score)), 4)
    except Exception as exc:
        logger.warning("LLM cross-cultural assessment failed: %s", exc)
        return None


async def _run_llm_enrichment(
    *,
    user_id: int,
    target_date: date,
    profile: StudentProfile | None,
    metrics: dict[str, Any],
    events: list[ConversationEvent],
) -> dict[str, Any]:
    narrative = await _generate_llm_daily_narrative(user_id, target_date, profile, metrics)
    cross_cultural = metrics.get("cross_cultural_deviation")
    if cross_cultural is None:
        cross_cultural = await _llm_assess_cross_cultural_deviation(events)
    return {
        "llm_narrative": narrative,
        "cross_cultural_deviation": cross_cultural,
    }


def generate_student_daily_summary(user_id: int, target_date: date | None = None) -> StudentDailySummary:
    """为指定用户生成某日的纵向摘要。

    Args:
        user_id: 学生用户 ID
        target_date: 目标日期，默认为昨天（每日凌晨任务逻辑）

    Returns:
        StudentDailySummary 实例（未写入数据库，需调用方 commit）
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    with Session(get_engine()) as session:
        vocab_items = _collect_vocab_items(user_id, target_date, session)
        essay_results = _collect_essay_results(user_id, target_date, session)
        essay_submissions = _collect_essay_submissions(user_id, target_date, session)
        events = _collect_conversation_events(user_id, target_date, session)
        queries = _collect_vocab_queries(user_id, target_date, session)
        records = _collect_learning_records(user_id, target_date, session)
        rolling_records = _collect_learning_records_window(user_id, target_date, session, window_days=7)

        # 读取用户画像
        profile = session.exec(
            select(StudentProfile).where(StudentProfile.user_id == user_id)
        ).first()

    # 计算20维度指标
    metrics = {
        "vocab_growth_rate": _calc_vocab_growth_rate(vocab_items),
        "sm2_retention_rate": _calc_sm2_retention(vocab_items),
        "active_lookup_conversion": _calc_lookup_conversion(queries, vocab_items),
        "morph_transfer_ability": _calc_morph_transfer_ability(essay_submissions, vocab_items),
        "long_term_memory_robustness": _calc_long_term_memory(vocab_items),
        "grammar_error_decay_slope": _calc_grammar_error_decay(essay_results),
        "advanced_vocab_substitution": _calc_advanced_vocab_substitution(essay_results, essay_submissions),
        "msl_diversity_index": _calc_msl_diversity(essay_submissions),
        "logical_coherence_trend": _calc_logical_coherence(essay_results),
        "semantic_accuracy_trend": _calc_semantic_accuracy(essay_results),
        "response_latency_avg_ms": _calc_response_latency(events),
        "speech_wpm": _calc_speech_wpm(events),
        "difficulty_jump_success": _calc_difficulty_jump_success(events),
        "cross_cultural_deviation": _calc_cross_cultural_deviation(events),
        "paraphrase_count": _calc_paraphrase_count(events),
        "learning_stability_std": _calc_learning_stability(rolling_records),
        "error_regression_rate": _calc_error_regression_rate(rolling_records),
        "feedback_response_depth": _calc_feedback_response_depth(essay_results, rolling_records),
        "topic_coverage_breadth": _calc_topic_coverage_breadth(vocab_items, queries, events, rolling_records),
        "autonomous_drive_count": _calc_autonomous_drive(queries, rolling_records),
    }

    llm_enrichment = asyncio.run(
        _run_llm_enrichment(
            user_id=user_id,
            target_date=target_date,
            profile=profile,
            metrics=metrics,
            events=events,
        )
    )
    llm_narrative = llm_enrichment.get("llm_narrative")
    metrics["cross_cultural_deviation"] = llm_enrichment.get("cross_cultural_deviation")
    metric_methodology = get_metric_methodology()
    discovered_topics = sorted(
        {
            *(
                label
                for item in vocab_items[-50:]
                for label in _classify_topic_labels(item.word, item.definition, item.example)
            ),
            *(
                label
                for query in queries
                for label in _classify_topic_labels(
                    query.term,
                    query.result,
                    (query.meta_data or {}).get("theme") or "",
                    (query.meta_data or {}).get("scenario") or "",
                )
            ),
            *(
                label
                for event in events
                for label in _classify_topic_labels(
                    (event.payload or {}).get("scenario") or "",
                    (event.payload or {}).get("text") or "",
                )
            ),
            *(
                label
                for record in rolling_records
                for label in _classify_topic_labels(
                    record.content,
                    (record.meta_data or {}).get("theme") or "",
                    (record.meta_data or {}).get("scenario") or "",
                )
            ),
        }
    )
    llm_used_for = [
        metric
        for metric, config in METRIC_METHODS.items()
        if config["mode"] == "llm_required" and metrics.get(metric) is not None
    ]
    if llm_narrative:
        llm_used_for.append("llm_narrative")

    summary = StudentDailySummary(
        user_id=user_id,
        class_id=profile.class_id if profile else None,
        summary_date=target_date,
        # A1-A5
        vocab_growth_rate=metrics["vocab_growth_rate"],
        sm2_retention_rate=metrics["sm2_retention_rate"],
        active_lookup_conversion=metrics["active_lookup_conversion"],
        morph_transfer_ability=metrics["morph_transfer_ability"],
        long_term_memory_robustness=metrics["long_term_memory_robustness"],
        # A6-A10
        grammar_error_decay_slope=metrics["grammar_error_decay_slope"],
        advanced_vocab_substitution=metrics["advanced_vocab_substitution"],
        msl_diversity_index=metrics["msl_diversity_index"],
        logical_coherence_trend=metrics["logical_coherence_trend"],
        semantic_accuracy_trend=metrics["semantic_accuracy_trend"],
        # A11-A15
        response_latency_avg_ms=metrics["response_latency_avg_ms"],
        speech_wpm=metrics["speech_wpm"],
        difficulty_jump_success=metrics["difficulty_jump_success"],
        cross_cultural_deviation=metrics["cross_cultural_deviation"],
        paraphrase_count=metrics["paraphrase_count"],
        # A16-A20
        learning_stability_std=metrics["learning_stability_std"],
        error_regression_rate=metrics["error_regression_rate"],
        feedback_response_depth=metrics["feedback_response_depth"],
        topic_coverage_breadth=metrics["topic_coverage_breadth"],
        autonomous_drive_count=metrics["autonomous_drive_count"],
        # 用户画像融合
        level=profile.level if profile else None,
        goals=profile.goals if profile else [],
        interests=profile.interests if profile else [],
        llm_narrative=llm_narrative,
        profile_snapshot={
            "level": profile.level if profile else None,
            "goals": profile.goals if profile else [],
            "interests": profile.interests if profile else [],
            "llm_narrative": llm_narrative,
            "metrics": {k: v for k, v in metrics.items() if v is not None},
            "metric_methodology": metric_methodology,
        },
        # 原始快照
        raw_snapshot={
            "vocab_count": len(vocab_items),
            "essay_count": len(essay_results),
            "event_count": len(events),
            "query_count": len(queries),
            "record_count": len(records),
            "rolling_record_count": len(rolling_records),
            "topics": discovered_topics,
            "metric_methodology": metric_methodology,
            "llm_used_for": llm_used_for,
        },
    )

    logger.info(
        "Generated daily summary for user=%s date=%s vocab=%s essay=%s events=%s profile=%s llm=%s",
        user_id,
        target_date,
        len(vocab_items),
        len(essay_results),
        len(events),
        "yes" if profile else "no",
        "yes" if llm_narrative else "no",
    )
    return summary
