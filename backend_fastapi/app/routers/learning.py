from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from ..db import get_session
from ..domain.analytics.models import StudentDailySummary
from ..domain.models import LearningRecord, User
from ..infrastructure.dependencies import get_current_user
from ..models import ConversationEvent, EssaySubmission, UserVocabQuery

router = APIRouter(prefix="/v1/learning", tags=["learning"])


class LearningStats(BaseModel):
    vocabulary: int
    essay: int
    dialogue: int
    analysis: int


class LearningAnalyzeRequest(BaseModel):
    dimension: str


class LearningAnalyzeResult(BaseModel):
    dimension: str
    score: int
    trend: int
    insights: list[str]
    recommendations: list[str]
    visualization: dict


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _normalize_ratio(value: float | int | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    raw = float(value)
    if raw <= 1.0:
        raw *= 100.0
    return max(0.0, min(100.0, raw))


def _normalize_vocab_growth(value: float | int | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value) * 20.0))


def _normalize_grammar_slope(value: float | int | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value) * 10.0 + 50.0))


def _normalize_wpm(value: float | int | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    # 以 40-160 WPM 作为常见学习区间进行线性映射。
    raw = (float(value) - 40.0) / 120.0 * 100.0
    return max(0.0, min(100.0, raw))


def _normalize_stability(value: float | int | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    raw = 100.0 - float(value) * 25.0
    return max(0.0, min(100.0, raw))


DIMENSION_CONFIG: dict[str, dict[str, object]] = {
    "vocabulary": {
        "field": "vocab_growth_rate",
        "label": "词汇增长",
        "normalizer": _normalize_vocab_growth,
    },
    "retention": {
        "field": "sm2_retention_rate",
        "label": "记忆保持",
        "normalizer": _normalize_ratio,
    },
    "grammar": {
        "field": "grammar_error_decay_slope",
        "label": "语法收敛",
        "normalizer": _normalize_grammar_slope,
    },
    "fluency": {
        "field": "speech_wpm",
        "label": "口语流利度",
        "normalizer": _normalize_wpm,
    },
    "dialogue": {
        "field": "difficulty_jump_success",
        "label": "对话跃迁",
        "normalizer": _normalize_ratio,
    },
    "coherence": {
        "field": "logical_coherence_trend",
        "label": "逻辑连贯",
        "normalizer": lambda value: float(value) if isinstance(value, (int, float)) else None,
    },
    "semantic": {
        "field": "semantic_accuracy_trend",
        "label": "语义准确",
        "normalizer": lambda value: float(value) if isinstance(value, (int, float)) else None,
    },
    "stability": {
        "field": "learning_stability_std",
        "label": "学习稳定性",
        "normalizer": _normalize_stability,
    },
}

DIMENSION_ALIASES = {
    "memory": "retention",
    "speaking": "fluency",
    "oral": "fluency",
    "logic": "coherence",
    "writing": "coherence",
}


def _calc_learning_stats(session: Session, user_id: int) -> LearningStats:
    # Use COUNT queries to avoid loading all rows into memory.
    vocab = session.exec(
        select(func.count()).select_from(UserVocabQuery).where(UserVocabQuery.user_id == user_id)
    ).one()
    essay = session.exec(
        select(func.count()).select_from(EssaySubmission).where(EssaySubmission.user_id == user_id)
    ).one()
    dialogue = session.exec(
        select(func.count())
        .select_from(LearningRecord)
        .where(LearningRecord.user_id == user_id)
        .where(col(LearningRecord.type) == "dialogue")
    ).one()

    analysis = session.exec(
        select(func.count()).select_from(ConversationEvent)
        .where(col(ConversationEvent.type) == "ANALYSIS_RESULT")
        .where(ConversationEvent.user_id == user_id)
    ).one()

    return LearningStats(vocabulary=int(vocab), essay=int(essay), dialogue=int(dialogue), analysis=int(analysis))


def _recent_summaries(session: Session, user_id: int, limit: int = 14) -> list[StudentDailySummary]:
    rows = list(
        session.exec(
            select(StudentDailySummary)
            .where(StudentDailySummary.user_id == user_id)
            .order_by(StudentDailySummary.summary_date.desc(), StudentDailySummary.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return rows


def _analyze_learning_dimension(
    session: Session,
    *,
    user_id: int,
    dimension: str,
) -> LearningAnalyzeResult:
    normalized_dim = DIMENSION_ALIASES.get(dimension, dimension)
    config = DIMENSION_CONFIG.get(normalized_dim)
    stats = _calc_learning_stats(session, user_id)

    if config is None:
        activity_total = stats.vocabulary + stats.essay + stats.dialogue + stats.analysis
        score = _clamp_score(min(100.0, activity_total * 5.0))
        return LearningAnalyzeResult(
            dimension=dimension,
            score=score,
            trend=0,
            insights=[
                f"暂未建立维度 {dimension} 的专门指标，当前返回学习活跃度代理值。",
                f"累计数据：查词 {stats.vocabulary}、作文 {stats.essay}、对话 {stats.dialogue}、分析 {stats.analysis}。",
            ],
            recommendations=[
                "优先在词汇、作文、对话三个主模块持续积累数据。",
                "待该维度进入正式指标体系后，再查看趋势分析。",
            ],
            visualization={
                "type": "bar",
                "title": "Learning Activity Overview",
                "labels": ["vocabulary", "essay", "dialogue", "analysis"],
                "datasets": [
                    {
                        "label": "count",
                        "data": [stats.vocabulary, stats.essay, stats.dialogue, stats.analysis],
                    }
                ],
            },
        )

    field_name = str(config["field"])
    normalizer = config["normalizer"]
    label = str(config["label"])
    summaries = _recent_summaries(session, user_id)

    series: list[tuple[str, float]] = []
    for summary in summaries:
        raw_value = getattr(summary, field_name, None)
        normalized_value = normalizer(raw_value) if callable(normalizer) else None
        if isinstance(normalized_value, (int, float)):
            series.append((str(summary.summary_date), float(normalized_value)))

    if not series:
        fallback_score = _clamp_score(min(100.0, (stats.vocabulary + stats.essay + stats.dialogue) * 5.0))
        return LearningAnalyzeResult(
            dimension=normalized_dim,
            score=fallback_score,
            trend=0,
            insights=[
                f"维度 {label} 暂无可用的日摘要数据。",
                "当前只能根据学习活跃度给出保守估计，结果可信度较低。",
            ],
            recommendations=[
                "先完成至少 2-3 天相关训练，再查看该维度趋势。",
                "优先使用已接入分析链路的模块，避免数据长期为空。",
            ],
            visualization={
                "type": "bar",
                "title": f"{label} Data Availability",
                "labels": ["vocabulary", "essay", "dialogue"],
                "datasets": [
                    {
                        "label": "activity",
                        "data": [stats.vocabulary, stats.essay, stats.dialogue],
                    }
                ],
            },
        )

    latest_value = series[-1][1]
    previous_value = series[-2][1] if len(series) > 1 else latest_value
    trend = int(round(latest_value - previous_value))
    score = _clamp_score(latest_value)

    if score >= 75:
        level_insight = f"{label} 当前表现稳定，已达到较可用水平。"
        level_recommendation = "保持当前训练频率，优先追求稳定输出而不是盲目加量。"
    elif score >= 50:
        level_insight = f"{label} 处于中间区间，已有基础，但波动仍然明显。"
        level_recommendation = "针对这一维度做连续训练，尽量避免长时间中断。"
    else:
        level_insight = f"{label} 当前偏弱，短板会直接影响整体体验。"
        level_recommendation = "把这一维度列为短期主攻方向，先解决最明显的薄弱点。"

    data_points = [round(value, 2) for _, value in series]
    return LearningAnalyzeResult(
        dimension=normalized_dim,
        score=score,
        trend=trend,
        insights=[
            level_insight,
            f"近 {len(series)} 次摘要可用于 {label} 趋势判断，最新分数 {score}。",
        ],
        recommendations=[
            level_recommendation,
            f"继续积累 {label} 的连续数据，避免只看单次结果。",
        ],
        visualization={
            "type": "line",
            "title": f"{label} Trend",
            "labels": [item[0] for item in series],
            "datasets": [
                {
                    "label": label,
                    "data": data_points,
                }
            ],
        },
    )


@router.get("/stats", response_model=LearningStats)
async def learning_stats(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LearningStats:
    return _calc_learning_stats(session, current_user.id or 0)


@router.post("/analyze", response_model=LearningAnalyzeResult)
async def learning_analyze(
    req: LearningAnalyzeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LearningAnalyzeResult:
    dim = (req.dimension or "").strip() or "vocabulary"
    return _analyze_learning_dimension(session, user_id=current_user.id or 0, dimension=dim)
