"""班级每日横向快照生成引擎。

为指定班级生成 ClassDailySnapshot，覆盖 10 个班级横向维度。
当前实现基于已有的 StudentDailySummary 聚合，无需额外外部服务。
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from ...domain.analytics.models import ClassDailySnapshot, StudentDailySummary
from ...domain.models import StudentProfile
from .daily_summary import _classify_topic_labels

logger = logging.getLogger(__name__)


def _summary_score(summary: StudentDailySummary) -> float:
    """计算学生综合分（与 agents.py 保持一致）。"""
    scores: list[float] = []
    if summary.vocab_growth_rate is not None:
        scores.append(summary.vocab_growth_rate * 20)
    if summary.sm2_retention_rate is not None:
        scores.append(summary.sm2_retention_rate * 100)
    if summary.grammar_error_decay_slope is not None:
        scores.append(max(0, summary.grammar_error_decay_slope * 10 + 50))
    if summary.logical_coherence_trend is not None:
        scores.append(summary.logical_coherence_trend)
    if summary.semantic_accuracy_trend is not None:
        scores.append(summary.semantic_accuracy_trend)
    return sum(scores) / len(scores) if scores else 0.0


def _avg(values: list[float | int | None]) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 4) if nums else None


def _calc_lower_tier_lift_rate(
    current_summaries: list[StudentDailySummary],
    previous_summaries: list[StudentDailySummary],
) -> float | None:
    """B1: 中下层进步斜率。

    计算底层 40% 学生（覆盖中下层）在当前 vs 7 天前的综合分变化斜率。
    """
    if not current_summaries:
        return None

    def _bottom_40pct_avg(summaries: list[StudentDailySummary]) -> float | None:
        scored = [(s, _summary_score(s)) for s in summaries]
        scored.sort(key=lambda x: x[1])
        cutoff = max(1, int(len(scored) * 0.4))
        bottom = scored[:cutoff]
        vals = [score for _, score in bottom if score > 0]
        return sum(vals) / len(vals) if vals else None

    current_avg = _bottom_40pct_avg(current_summaries)
    previous_avg = _bottom_40pct_avg(previous_summaries)

    if current_avg is None or previous_avg is None:
        return None
    # 归一化斜率：避免分母为 0
    denom = max(abs(previous_avg), 1.0)
    return round((current_avg - previous_avg) / denom, 4)


def _calc_common_error_index(current_summaries: list[StudentDailySummary]) -> float | None:
    """B2: 群体性错误共性指数。

    启发式：grammar_error_decay_slope < 0（语法退步）的学生比例，
    叠加 error_regression_rate > 0.3 的比例。
    """
    if not current_summaries:
        return None

    grammar_regress = 0
    error_high = 0
    valid = 0
    for s in current_summaries:
        has_signal = False
        if s.grammar_error_decay_slope is not None:
            has_signal = True
            if s.grammar_error_decay_slope < 0:
                grammar_regress += 1
        if s.error_regression_rate is not None:
            has_signal = True
            if s.error_regression_rate > 0.3:
                error_high += 1
        if has_signal:
            valid += 1

    if valid == 0:
        return None

    # 取两个信号的平均，范围 0-1
    return round((grammar_regress / valid + error_high / valid) / 2, 4)


def _calc_mid_tier_difficulty_tolerance(current_summaries: list[StudentDailySummary]) -> float | None:
    """B3: 中层学生难度耐受力。

    中层 60% 学生的 difficulty_jump_success 均值。
    """
    if not current_summaries:
        return None

    scored = [(s, _summary_score(s)) for s in current_summaries]
    scored.sort(key=lambda x: x[1])
    n = len(scored)
    lower = n // 5
    upper = n - n // 5
    middle = scored[lower:upper]

    vals = [s.difficulty_jump_success for s, _ in middle if s.difficulty_jump_success is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _calc_learning_path_convergence(current_summaries: list[StudentDailySummary]) -> float | None:
    """B4: 学习路径收敛度。

    计算学生主题覆盖的 Jaccard 相似度均值。
    越接近 1 表示班级学习主题越集中。
    """
    if len(current_summaries) < 2:
        return None

    def _topics(summary: StudentDailySummary) -> set[str]:
        raw = summary.raw_snapshot or {}
        topics = raw.get("topics") or []
        if isinstance(topics, list):
            return set(str(t).strip() for t in topics if t)
        return set()

    topic_sets = [_topics(s) for s in current_summaries if _topics(s)]
    if len(topic_sets) < 2:
        return None

    similarities: list[float] = []
    for i in range(len(topic_sets)):
        for j in range(i + 1, len(topic_sets)):
            a, b = topic_sets[i], topic_sets[j]
            intersection = len(a & b)
            union = len(a | b)
            if union > 0:
                similarities.append(intersection / union)

    return round(sum(similarities) / len(similarities), 4) if similarities else None


def _calc_ability_distribution_shift(
    current_summaries: list[StudentDailySummary],
    previous_summaries: list[StudentDailySummary],
) -> float | None:
    """B5: 能力等级分布位移。

    对比当前与 7 天前的底层/中层/顶层比例变化。
    返回位移幅度（0 表示无变化，越大表示分布变动越大）。
    """
    if not current_summaries or not previous_summaries:
        return None

    def _distribution(summaries: list[StudentDailySummary]) -> tuple[float, float, float]:
        scored = sorted([_summary_score(s) for s in summaries if _summary_score(s) > 0])
        n = len(scored)
        if n == 0:
            return 0.0, 0.0, 0.0
        cutoff = max(1, n // 5)
        bottom = cutoff / n
        top = cutoff / n
        middle = 1.0 - bottom - top
        return bottom, middle, top

    cur_b, cur_m, cur_t = _distribution(current_summaries)
    prev_b, prev_m, prev_t = _distribution(previous_summaries)

    shift = abs(cur_b - prev_b) + abs(cur_m - prev_m) + abs(cur_t - prev_t)
    return round(shift / 2, 4)  # 归一化到 0-1


def _calc_bottleneck_duration_days(current_summaries: list[StudentDailySummary]) -> float | None:
    """B8: 中上层瓶颈期时长。

    中上层学生（综合分前 40%）中 logical_coherence_trend < 60 的平均天数估计。
    由于只有单日数据，用比例乘以 14 天窗口做代理。
    """
    if not current_summaries:
        return None

    scored = [(s, _summary_score(s)) for s in current_summaries]
    scored.sort(key=lambda x: x[1], reverse=True)
    cutoff = max(1, int(len(scored) * 0.4))
    upper = scored[:cutoff]

    bottleneck_count = 0
    total = 0
    for s, _ in upper:
        if s.logical_coherence_trend is not None:
            total += 1
            if s.logical_coherence_trend < 60:
                bottleneck_count += 1

    if total == 0:
        return None

    # 用比例估计瓶颈天数：假设持续比例 × 14 天
    return round((bottleneck_count / total) * 14, 4)


def _calc_feedback_adoption_tendency(current_summaries: list[StudentDailySummary]) -> dict[str, Any] | None:
    """B9: 反馈采纳群体倾向。

    基于 feedback_response_depth 分布统计结构/语法建议采纳比例代理。
    """
    if not current_summaries:
        return None

    depths = [s.feedback_response_depth for s in current_summaries if s.feedback_response_depth is not None]
    if not depths:
        return None

    high = sum(1 for d in depths if d >= 0.6)
    medium = sum(1 for d in depths if 0.3 <= d < 0.6)
    low = sum(1 for d in depths if d < 0.3)
    total = len(depths)

    return {
        "high_adoption_ratio": round(high / total, 4),
        "medium_adoption_ratio": round(medium / total, 4),
        "low_adoption_ratio": round(low / total, 4),
        "avg_depth": round(sum(depths) / total, 4),
    }


def _calc_task_completion_resilience(current_summaries: list[StudentDailySummary]) -> float | None:
    """B10: 任务完成韧性。

    基于 sm2_retention_rate 和 long_term_memory_robustness 的代理指标。
    高保持率 + 高长时记忆 = 高韧性。
    """
    if not current_summaries:
        return None

    scores: list[float] = []
    for s in current_summaries:
        retention = s.sm2_retention_rate
        memory = s.long_term_memory_robustness
        if retention is not None and memory is not None:
            # retention 0-1, memory 通常 0-N，做归一化
            normalized_memory = min(1.0, memory / 10.0)
            scores.append(retention * 0.6 + normalized_memory * 0.4)
        elif retention is not None:
            scores.append(retention)

    return round(sum(scores) / len(scores), 4) if scores else None


def generate_class_daily_snapshot(
    class_id: str,
    target_date: date | None = None,
) -> ClassDailySnapshot:
    """为指定班级生成某日的横向快照。

    Returns:
        ClassDailySnapshot 实例（未写入数据库，需调用方 commit）
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    with Session(get_engine()) as session:
        user_ids = [
            p.user_id
            for p in session.exec(
                select(StudentProfile).where(StudentProfile.class_id == class_id)
            )
        ]

        # 当日摘要
        current_summaries = list(
            session.exec(
                select(StudentDailySummary)
                .where(StudentDailySummary.user_id.in_(user_ids))
                .where(StudentDailySummary.summary_date == target_date)
            )
        ) if user_ids else []

        # 7 天前摘要（用于对比）
        prev_date = target_date - timedelta(days=7)
        previous_summaries = list(
            session.exec(
                select(StudentDailySummary)
                .where(StudentDailySummary.user_id.in_(user_ids))
                .where(StudentDailySummary.summary_date == prev_date)
            )
        ) if user_ids else []

    b1 = _calc_lower_tier_lift_rate(current_summaries, previous_summaries)
    b2 = _calc_common_error_index(current_summaries)
    b3 = _calc_mid_tier_difficulty_tolerance(current_summaries)
    b4 = _calc_learning_path_convergence(current_summaries)
    b5 = _calc_ability_distribution_shift(current_summaries, previous_summaries)
    b8 = _calc_bottleneck_duration_days(current_summaries)
    b9 = _calc_feedback_adoption_tendency(current_summaries)
    b10 = _calc_task_completion_resilience(current_summaries)

    snapshot = ClassDailySnapshot(
        class_id=class_id,
        snapshot_date=target_date,
        lower_tier_lift_rate=b1,
        common_error_index=b2,
        mid_tier_difficulty_tolerance=b3,
        learning_path_convergence=b4,
        ability_distribution_shift=b5,
        collaboration_activity=None,  # B6 预留：需协作模块就绪
        kg_connectivity=None,         # B7 预留：需 Neo4j KG 班级级统计
        bottleneck_duration_days=b8,
        feedback_adoption_tendency=b9 or {},
        task_completion_resilience=b10,
        raw_snapshot={
            "student_count": len(current_summaries),
            "previous_date": str(prev_date),
            "previous_student_count": len(previous_summaries),
            "computed_dimensions": {
                "B1": b1 is not None,
                "B2": b2 is not None,
                "B3": b3 is not None,
                "B4": b4 is not None,
                "B5": b5 is not None,
                "B8": b8 is not None,
                "B9": b9 is not None,
                "B10": b10 is not None,
            },
        },
    )

    logger.info(
        "Generated class snapshot for class=%s date=%s students=%s dims=%s",
        class_id,
        target_date,
        len(current_summaries),
        sum(1 for v in [b1, b2, b3, b4, b5, b8, b9, b10] if v is not None),
    )
    return snapshot
