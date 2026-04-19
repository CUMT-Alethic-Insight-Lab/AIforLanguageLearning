"""Thin analytics facade for unified teacher-facing workflows.

This module centralizes:
- teacher dashboard payload assembly
- student dashboard payload assembly
- class assignment / transfer and downstream class_id synchronization
- class_id backfill inference for legacy data

Routers should prefer calling this layer instead of hand-assembling workflow logic.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from ...domain.analytics.models import (
    AnalyticsArtifact,
    ClassDailySnapshot,
    InterventionTask,
    StudentDailySummary,
    StudentLongitudinalSummary,
)
from ...domain.models import StudentProfile, User
from .agents import run_and_persist_tiered_analysis
from .daily_summary import get_metric_methodology
from .orchestration import (
    generate_class_window_analysis,
    generate_student_longitudinal_summary,
    get_class_summaries,
    resolve_class_id_for_user,
    upsert_analytics_artifact,
)
from .weekly_report import async_generate_class_weekly_report


def _normalize_class_id(class_id: str | None) -> str | None:
    value = (class_id or "").strip()
    return value or None


def _get_user_name(session: Session, user_id: int) -> str | None:
    user = session.exec(select(User).where(User.id == user_id)).first()
    return user.username if user else None


def _summary_score(summary: StudentDailySummary) -> float:
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
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def _avg(values: list[float | int | None]) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _calc_ability_distribution(summaries: list[StudentDailySummary]) -> dict[str, int]:
    scored = sorted(_summary_score(s) for s in summaries)
    if not scored:
        return {"bottom": 0, "middle": 0, "top": 0}
    n = len(scored)
    bottom_cutoff = scored[max(0, n // 5 - 1)]
    top_cutoff = scored[max(0, n - n // 5 - 1)]
    bottom = sum(1 for s in scored if s <= bottom_cutoff)
    top = sum(1 for s in scored if s >= top_cutoff)
    return {"bottom": bottom, "middle": n - bottom - top, "top": top}


def _risk_tags(summary: StudentDailySummary) -> list[str]:
    tags: list[str] = []
    if summary.vocab_growth_rate is not None and summary.vocab_growth_rate < 2.0:
        tags.append("词汇薄弱")
    if summary.learning_stability_std is not None and summary.learning_stability_std > 2.0:
        tags.append("稳定性差")
    if summary.response_latency_avg_ms is not None and summary.response_latency_avg_ms > 3000:
        tags.append("响应迟缓")
    if summary.grammar_error_decay_slope is not None and summary.grammar_error_decay_slope < 0:
        tags.append("语法退步")
    return tags


def _dedupe_dict_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _merge_meta_data(
    target: dict[str, Any] | None,
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(target or {})
    for key, value in (source or {}).items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
            continue
        if isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*merged[key], *value]))
    return merged


def _build_class_charts(
    latest_summaries: list[StudentDailySummary],
    window_summaries: list[StudentDailySummary],
) -> dict[str, Any]:
    charts: dict[str, Any] = {}
    ability_dist = _calc_ability_distribution(latest_summaries)
    charts["ability_pie"] = {
        "type": "pie",
        "title": "能力分布",
        "labels": ["底层", "中层", "顶层"],
        "datasets": [{"label": "人数", "data": [ability_dist["bottom"], ability_dist["middle"], ability_dist["top"]]}],
    }

    risk_counter = {"词汇薄弱": 0, "稳定性差": 0, "响应迟缓": 0, "语法退步": 0}
    for summary in latest_summaries:
        for tag in _risk_tags(summary):
            risk_counter[tag] += 1
    charts["risk_bar"] = {
        "type": "bar",
        "title": "风险分布",
        "labels": list(risk_counter.keys()),
        "datasets": [{"label": "人数", "data": list(risk_counter.values())}],
    }

    dates = sorted({str(s.summary_date) for s in window_summaries})
    if dates:
        vocab_series: list[float] = []
        grammar_series: list[float] = []
        for day in dates:
            items = [s for s in window_summaries if str(s.summary_date) == day]
            vocab_series.append(_avg([s.vocab_growth_rate for s in items]) or 0.0)
            grammar_series.append(_avg([s.grammar_error_decay_slope for s in items]) or 0.0)
        charts["trend_line"] = {
            "type": "line",
            "title": "近7日班级趋势",
            "labels": dates,
            "datasets": [
                {"label": "词汇增长", "data": vocab_series},
                {"label": "语法收敛", "data": grammar_series},
            ],
        }

    if latest_summaries:
        charts["class_radar"] = {
            "type": "radar",
            "title": "班级能力雷达",
            "labels": ["词汇", "语法", "逻辑", "口语", "稳定性", "自主学习"],
            "datasets": [
                {
                    "label": "班级均值",
                    "data": [
                        min(100, (_avg([s.vocab_growth_rate for s in latest_summaries]) or 0) * 20),
                        min(100, (_avg([s.grammar_error_decay_slope for s in latest_summaries]) or 0) * 20),
                        min(100, _avg([s.logical_coherence_trend for s in latest_summaries]) or 0),
                        min(100, _avg([s.speech_wpm for s in latest_summaries]) or 0),
                        min(100, 100 - (_avg([s.learning_stability_std for s in latest_summaries]) or 0) * 20),
                        min(100, (_avg([s.autonomous_drive_count for s in latest_summaries]) or 0) * 20),
                    ],
                }
            ],
        }
    return charts


def _build_student_charts(summaries: list[StudentDailySummary]) -> dict[str, Any]:
    charts: dict[str, Any] = {}
    latest = summaries[-1] if summaries else None
    if latest:
        radar_labels = [
            "词汇增长", "SM-2保持", "查词转化", "构词迁移", "长时记忆",
            "语法收敛", "高级词汇", "句式多样", "逻辑连贯", "语义准确",
            "响应延迟", "语音速率", "难度跳变", "文化得体", "转述能力",
            "学习稳定", "错误复发", "反馈深度", "主题覆盖", "自主学习",
        ]
        raw = [
            latest.vocab_growth_rate, latest.sm2_retention_rate, latest.active_lookup_conversion,
            latest.morph_transfer_ability, latest.long_term_memory_robustness, latest.grammar_error_decay_slope,
            latest.advanced_vocab_substitution, latest.msl_diversity_index, latest.logical_coherence_trend,
            latest.semantic_accuracy_trend, latest.response_latency_avg_ms, latest.speech_wpm,
            latest.difficulty_jump_success, latest.cross_cultural_deviation, latest.paraphrase_count,
            latest.learning_stability_std, latest.error_regression_rate, latest.feedback_response_depth,
            latest.topic_coverage_breadth, latest.autonomous_drive_count,
        ]
        normalized: list[float] = []
        for idx, value in enumerate(raw):
            if value is None:
                normalized.append(0)
            elif idx in (10, 15, 16):
                normalized.append(max(0, min(100, 100 - float(value))))
            elif idx in (4, 14, 18, 19):
                normalized.append(max(0, min(100, float(value) * 10)))
            else:
                normalized.append(max(0, min(100, float(value) * 20 if float(value) <= 5 else float(value))))
        charts["radar_20d"] = {
            "type": "radar",
            "title": "20维度能力雷达",
            "labels": radar_labels,
            "datasets": [{"label": "当天快照", "data": normalized}],
        }

        focus_keys = [
            ("词汇增长", "vocab_growth_rate"),
            ("语法收敛", "grammar_error_decay_slope"),
            ("逻辑连贯", "logical_coherence_trend"),
            ("学习稳定", "learning_stability_std"),
            ("自主学习", "autonomous_drive_count"),
        ]
        charts["focus_bar"] = {
            "type": "bar",
            "title": "当天 vs 窗口均值",
            "labels": [label for label, _ in focus_keys],
            "datasets": [
                {
                    "label": "当天",
                    "data": [float(getattr(latest, key) or 0) for _, key in focus_keys],
                },
                {
                    "label": "窗口均值",
                    "data": [_avg([getattr(s, key, None) for s in summaries]) or 0.0 for _, key in focus_keys],
                },
            ],
        }

    if len(summaries) >= 2:
        dates = [str(s.summary_date) for s in summaries]
        charts["trend_lines"] = [
            {
                "type": "line",
                "title": "核心趋势",
                "labels": dates,
                "datasets": [
                    {"label": "词汇增长", "data": [float(s.vocab_growth_rate or 0) for s in summaries]},
                    {"label": "语法收敛", "data": [float(s.grammar_error_decay_slope or 0) for s in summaries]},
                    {"label": "逻辑连贯", "data": [float(s.logical_coherence_trend or 0) for s in summaries]},
                ],
            },
            {
                "type": "line",
                "title": "状态趋势",
                "labels": dates,
                "datasets": [
                    {"label": "学习稳定", "data": [float(s.learning_stability_std or 0) for s in summaries]},
                    {"label": "响应延迟", "data": [float(s.response_latency_avg_ms or 0) for s in summaries]},
                    {"label": "自主学习", "data": [float(s.autonomous_drive_count or 0) for s in summaries]},
                ],
            },
        ]
    return charts


async def build_class_overview_payload(
    session: Session,
    *,
    class_id: str,
    target_date: date | None = None,
    recent_days: int = 3,
) -> dict[str, Any]:
    target_date = target_date or (date.today() - timedelta(days=1))
    latest_summaries = get_class_summaries(session, class_id, target_date, target_date)
    week_summaries = get_class_summaries(session, class_id, target_date - timedelta(days=6), target_date)
    snapshot = session.exec(
        select(ClassDailySnapshot)
        .where(ClassDailySnapshot.class_id == class_id)
        .where(ClassDailySnapshot.snapshot_date == target_date)
    ).first()
    recent_analysis = await generate_class_window_analysis(
        session,
        class_id=class_id,
        target_date=target_date,
        window_days=recent_days,
    )

    vocab_rates = [s.vocab_growth_rate for s in week_summaries if s.vocab_growth_rate is not None]
    grammar_slopes = [s.grammar_error_decay_slope for s in week_summaries if s.grammar_error_decay_slope is not None]
    ability_dist = _calc_ability_distribution(latest_summaries)
    risk_count = sum(1 for s in latest_summaries if _risk_tags(s))

    return {
        "class_id": class_id,
        "date": target_date,
        "total_students": len(latest_summaries),
        "active_students": len(latest_summaries),
        "risk_count": risk_count,
        "avg_vocab_growth": _avg(vocab_rates),
        "avg_grammar_decay": _avg(grammar_slopes),
        "ability_distribution": ability_dist,
        "trend_7d": {
            "vocab_growth_avg": _avg(vocab_rates),
            "grammar_decay_avg": _avg(grammar_slopes),
            "data_points": len(week_summaries),
            "common_error_index": snapshot.common_error_index if snapshot else None,
        },
        "recent_analysis": {
            "window_start": str(recent_analysis.window_start) if recent_analysis.window_start else None,
            "window_end": str(recent_analysis.window_end) if recent_analysis.window_end else None,
            "content": recent_analysis.content,
            "evidence": recent_analysis.evidence,
        },
        "charts": _build_class_charts(latest_summaries, week_summaries),
    }


def build_class_students_payload(
    session: Session,
    *,
    class_id: str,
    target_date: date | None = None,
) -> list[dict[str, Any]]:
    target_date = target_date or (date.today() - timedelta(days=1))
    summaries = get_class_summaries(session, class_id, target_date, target_date)
    return [
        {
            "user_id": s.user_id,
            "username": _get_user_name(session, s.user_id),
            "risk_tags": _risk_tags(s),
            "latest_score": _summary_score(s),
            "last_active_date": s.summary_date,
            "class_id": class_id,
        }
        for s in summaries
    ]


async def build_weekly_report_payload(
    session: Session,
    *,
    class_id: str,
    week_start: date | None = None,
) -> dict[str, Any]:
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday() + 1)
        if today.weekday() == 6:
            week_start = today
    week_end = week_start + timedelta(days=6)
    record = session.exec(
        select(AnalyticsArtifact)
        .where(AnalyticsArtifact.artifact_type == "weekly_report")
        .where(AnalyticsArtifact.class_id == class_id)
        .where(AnalyticsArtifact.window_start == week_start)
        .where(AnalyticsArtifact.window_end == week_end)
    ).first()
    if record is None:
        record = await async_generate_class_weekly_report(session, class_id, week_start)
    return {
        "class_id": class_id,
        "week_start": week_start,
        "content": record.content,
        "generated_at": record.updated_at.date(),
        "evidence": record.evidence,
    }


async def build_class_dashboard_payload(
    session: Session,
    *,
    class_id: str,
    target_date: date | None = None,
    recent_days: int = 3,
    include_weekly: bool = False,
) -> dict[str, Any]:
    overview = await build_class_overview_payload(
        session,
        class_id=class_id,
        target_date=target_date,
        recent_days=recent_days,
    )
    students = build_class_students_payload(session, class_id=class_id, target_date=target_date)
    payload: dict[str, Any] = {
        "class_id": class_id,
        "overview": overview,
        "students": students,
    }
    if include_weekly:
        payload["weekly"] = await build_weekly_report_payload(session, class_id=class_id)
    else:
        payload["weekly"] = None
    return payload


async def build_student_profile_payload(
    session: Session,
    *,
    student_id: int,
    days: int = 14,
    target_date: date | None = None,
) -> dict[str, Any]:
    target_date = target_date or (date.today() - timedelta(days=1))
    start_date = target_date - timedelta(days=days - 1)
    summaries = list(
        session.exec(
            select(StudentDailySummary)
            .where(StudentDailySummary.user_id == student_id)
            .where(StudentDailySummary.summary_date >= start_date)
            .where(StudentDailySummary.summary_date <= target_date)
            .order_by(StudentDailySummary.summary_date)
        )
    )
    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    longitudinal = await generate_student_longitudinal_summary(
        session,
        student_id,
        class_id=profile.class_id if profile else None,
        end_date=target_date,
        window_days=days,
    )
    latest = summaries[-1] if summaries else None

    latest_summary = None
    if latest:
        latest_summary = {
            "date": str(latest.summary_date),
            "class_id": latest.class_id,
            "vocab_growth_rate": latest.vocab_growth_rate,
            "sm2_retention_rate": latest.sm2_retention_rate,
            "grammar_error_decay_slope": latest.grammar_error_decay_slope,
            "logical_coherence_trend": latest.logical_coherence_trend,
            "learning_stability_std": latest.learning_stability_std,
            "level": latest.level,
            "goals": latest.goals,
            "interests": latest.interests,
            "llm_narrative": latest.llm_narrative,
            "metric_methodology": (latest.raw_snapshot or {}).get("metric_methodology") or get_metric_methodology(),
            "llm_used_for": (latest.raw_snapshot or {}).get("llm_used_for") or [],
            "topics": (latest.raw_snapshot or {}).get("topics") or [],
        }

    time_series = [
        {
            "date": str(s.summary_date),
            "vocab_growth_rate": s.vocab_growth_rate,
            "sm2_retention_rate": s.sm2_retention_rate,
            "active_lookup_conversion": s.active_lookup_conversion,
            "morph_transfer_ability": s.morph_transfer_ability,
            "long_term_memory_robustness": s.long_term_memory_robustness,
            "grammar_error_decay_slope": s.grammar_error_decay_slope,
            "advanced_vocab_substitution": s.advanced_vocab_substitution,
            "msl_diversity_index": s.msl_diversity_index,
            "logical_coherence_trend": s.logical_coherence_trend,
            "semantic_accuracy_trend": s.semantic_accuracy_trend,
            "response_latency_avg_ms": s.response_latency_avg_ms,
            "speech_wpm": s.speech_wpm,
            "difficulty_jump_success": s.difficulty_jump_success,
            "cross_cultural_deviation": s.cross_cultural_deviation,
            "paraphrase_count": s.paraphrase_count,
            "learning_stability_std": s.learning_stability_std,
            "error_regression_rate": s.error_regression_rate,
            "feedback_response_depth": s.feedback_response_depth,
            "topic_coverage_breadth": s.topic_coverage_breadth,
            "autonomous_drive_count": s.autonomous_drive_count,
        }
        for s in summaries
    ]

    return {
        "user_id": student_id,
        "username": _get_user_name(session, student_id),
        "profile": (
            {
                "class_id": profile.class_id if profile else None,
                "level": profile.level if profile else None,
                "goals": profile.goals if profile else [],
                "interests": profile.interests if profile else [],
            }
            if profile
            else None
        ),
        "time_series": time_series,
        "latest_summary": latest_summary,
        "llm_narrative": latest.llm_narrative if latest else None,
        "longitudinal_summary": {
            "window_start": longitudinal.window_start,
            "window_end": longitudinal.window_end,
            "window_days": longitudinal.window_days,
            "llm_summary": longitudinal.llm_summary,
            "risk_flags": longitudinal.risk_flags,
            "strength_flags": longitudinal.strength_flags,
            "metric_deltas": longitudinal.metric_deltas,
            "evidence": longitudinal.evidence,
        },
        "charts": _build_student_charts(summaries),
        "analysis_methodology": get_metric_methodology(),
        "data_quality": {
            "days_requested": days,
            "days_with_summary": len(summaries),
            "class_id": profile.class_id if profile else None,
            "latest_snapshot": latest.raw_snapshot if latest else {},
        },
    }


async def build_student_report_payload(
    session: Session,
    *,
    student_id: int,
    target_date: date | None = None,
    llm_enhance: bool = False,
) -> dict[str, Any]:
    target_date = target_date or (date.today() - timedelta(days=1))
    class_id = resolve_class_id_for_user(session, student_id)
    if not class_id:
        raise ValueError(f"Student {student_id} has no class assignment")
    reports = await run_and_persist_tiered_analysis(
        session,
        class_id=class_id,
        target_date=target_date,
        llm_enhance=llm_enhance,
    )
    if not reports:
        raise LookupError(f"Class {class_id} has no summary for {target_date}")

    agent_reports: list[dict[str, Any]] = []
    for report in reports:
        student_risks = [item for item in report.risk_students if item["user_id"] == student_id]
        student_tasks = [task for task in report.intervention_tasks if task.student_id == student_id]
        if student_risks or student_tasks:
            agent_reports.append(
                {
                    "agent_type": report.agent_type,
                    "insights": report.insights,
                    "suggestions": report.suggestions,
                    "risk_flags": [item["risk_flags"] for item in student_risks],
                    "evidence": [item for item in report.evidence if item.get("user_id") == student_id],
                    "intervention_tasks": [
                        {
                            "title": task.title,
                            "description": task.description,
                            "priority": task.priority,
                            "status": task.status,
                            "due_date": str(task.due_date) if task.due_date else None,
                        }
                        for task in student_tasks
                    ],
                }
            )
    if not agent_reports:
        agent_reports.append(
            {
                "agent_type": "overview",
                "insights": ["该学生今日无显著风险或突破信号"],
                "suggestions": ["继续保持当前学习节奏"],
                "risk_flags": [],
                "evidence": [],
                "intervention_tasks": [],
            }
        )
    return {
        "user_id": student_id,
        "date": target_date,
        "agent_reports": agent_reports,
    }


async def build_student_dashboard_payload(
    session: Session,
    *,
    student_id: int,
    days: int = 14,
    target_date: date | None = None,
    llm_enhance: bool = False,
) -> dict[str, Any]:
    profile = await build_student_profile_payload(
        session,
        student_id=student_id,
        days=days,
        target_date=target_date,
    )
    report = await build_student_report_payload(
        session,
        student_id=student_id,
        target_date=target_date,
        llm_enhance=llm_enhance,
    )
    return {
        "student_id": student_id,
        "profile": profile,
        "report": report,
    }


def _merge_longitudinal_row(
    session: Session,
    row: StudentLongitudinalSummary,
    *,
    class_id: str | None,
) -> str:
    duplicate = session.exec(
        select(StudentLongitudinalSummary)
        .where(StudentLongitudinalSummary.id != row.id)
        .where(StudentLongitudinalSummary.user_id == row.user_id)
        .where(StudentLongitudinalSummary.class_id == class_id)
        .where(StudentLongitudinalSummary.window_start == row.window_start)
        .where(StudentLongitudinalSummary.window_end == row.window_end)
        .where(StudentLongitudinalSummary.window_days == row.window_days)
    ).first()
    if duplicate is None:
        row.class_id = class_id
        session.add(row)
        return "updated"

    if row.updated_at >= duplicate.updated_at:
        duplicate.llm_summary = row.llm_summary or duplicate.llm_summary
        duplicate.risk_flags = list(dict.fromkeys([*duplicate.risk_flags, *row.risk_flags]))
        duplicate.strength_flags = list(dict.fromkeys([*duplicate.strength_flags, *row.strength_flags]))
        duplicate.metric_deltas = row.metric_deltas or duplicate.metric_deltas
        duplicate.evidence = _dedupe_dict_list([*duplicate.evidence, *row.evidence])
        duplicate.source_summary_ids = list(dict.fromkeys([*duplicate.source_summary_ids, *row.source_summary_ids]))
        duplicate.meta_data = _merge_meta_data(duplicate.meta_data, row.meta_data)
        duplicate.updated_at = row.updated_at
        session.add(duplicate)
    session.delete(row)
    return "merged"


def _merge_artifact_row(
    session: Session,
    row: AnalyticsArtifact,
    *,
    class_id: str | None,
) -> str:
    duplicate = session.exec(
        select(AnalyticsArtifact)
        .where(AnalyticsArtifact.id != row.id)
        .where(AnalyticsArtifact.artifact_type == row.artifact_type)
        .where(AnalyticsArtifact.scope == row.scope)
        .where(AnalyticsArtifact.class_id == class_id)
        .where(AnalyticsArtifact.user_id == row.user_id)
        .where(AnalyticsArtifact.agent_type == row.agent_type)
        .where(AnalyticsArtifact.target_date == row.target_date)
        .where(AnalyticsArtifact.window_start == row.window_start)
        .where(AnalyticsArtifact.window_end == row.window_end)
    ).first()
    if duplicate is None:
        row.class_id = class_id
        session.add(row)
        return "updated"

    if row.updated_at >= duplicate.updated_at:
        duplicate.title = row.title or duplicate.title
        duplicate.content = row.content or duplicate.content
        duplicate.evidence = _dedupe_dict_list([*duplicate.evidence, *row.evidence])
        duplicate.meta_data = _merge_meta_data(duplicate.meta_data, row.meta_data)
        duplicate.updated_at = row.updated_at
        session.add(duplicate)
    session.delete(row)
    return "merged"


def sync_class_id_for_user(
    session: Session,
    *,
    user_id: int,
    class_id: str | None,
) -> dict[str, int]:
    stats = {
        "student_profile_updated": 0,
        "daily_summaries_updated": 0,
        "longitudinal_summaries_updated": 0,
        "longitudinal_summaries_merged": 0,
        "intervention_tasks_updated": 0,
        "artifacts_updated": 0,
        "artifacts_merged": 0,
    }
    normalized = _normalize_class_id(class_id)

    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
    if profile is None:
        profile = StudentProfile(user_id=user_id, class_id=normalized)
    elif profile.class_id != normalized:
        profile.class_id = normalized
    session.add(profile)
    stats["student_profile_updated"] = 1

    for row in list(session.exec(select(StudentDailySummary).where(StudentDailySummary.user_id == user_id))):
        if row.class_id != normalized:
            row.class_id = normalized
            session.add(row)
            stats["daily_summaries_updated"] += 1

    for row in list(session.exec(select(StudentLongitudinalSummary).where(StudentLongitudinalSummary.user_id == user_id))):
        result = _merge_longitudinal_row(session, row, class_id=normalized)
        stats[f"longitudinal_summaries_{result}"] += 1

    for row in list(session.exec(select(InterventionTask).where(InterventionTask.student_id == user_id))):
        if row.class_id != normalized:
            row.class_id = normalized
            session.add(row)
            stats["intervention_tasks_updated"] += 1

    for row in list(session.exec(select(AnalyticsArtifact).where(AnalyticsArtifact.user_id == user_id))):
        result = _merge_artifact_row(session, row, class_id=normalized)
        stats[f"artifacts_{result}"] += 1

    session.flush()
    return stats


async def assign_student_class(
    session: Session,
    *,
    user_id: int,
    class_id: str | None,
    operator_user_id: int | None = None,
    note: str = "",
    sync_related_records: bool = True,
) -> dict[str, Any]:
    user = session.exec(select(User).where(User.id == user_id)).first()
    if user is None:
        raise LookupError(f"Student {user_id} not found")

    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
    previous_class_id = profile.class_id if profile else None
    normalized = _normalize_class_id(class_id)

    if sync_related_records:
        sync_stats = sync_class_id_for_user(session, user_id=user_id, class_id=normalized)
    else:
        if profile is None:
            profile = StudentProfile(user_id=user_id, class_id=normalized)
        else:
            profile.class_id = normalized
        session.add(profile)
        session.flush()
        sync_stats = {
            "student_profile_updated": 1,
            "daily_summaries_updated": 0,
            "longitudinal_summaries_updated": 0,
            "longitudinal_summaries_merged": 0,
            "intervention_tasks_updated": 0,
            "artifacts_updated": 0,
            "artifacts_merged": 0,
        }

    target_scope_class_id = normalized or previous_class_id
    await upsert_analytics_artifact(
        session,
        artifact_type="class_assignment_change",
        scope="student",
        class_id=target_scope_class_id,
        user_id=user_id,
        title=f"学生{user_id}分班变更",
        content=(
            f"学生 {user.username}({user_id}) 班级变更："
            f"{previous_class_id or '未分班'} -> {normalized or '未分班'}。"
            f"{('备注：' + note) if note else ''}"
        ),
        evidence=[
            {
                "previous_class_id": previous_class_id,
                "current_class_id": normalized,
                "sync_stats": sync_stats,
            }
        ],
        meta_data={
            "previous_class_id": previous_class_id,
            "current_class_id": normalized,
            "operator_user_id": operator_user_id,
            "note": note,
            "tags": ["class_assignment_change", normalized or "unassigned"],
        },
    )
    return {
        "user_id": user_id,
        "username": user.username,
        "previous_class_id": previous_class_id,
        "class_id": normalized,
        "changed": previous_class_id != normalized,
        "sync_stats": sync_stats,
    }


def _infer_class_votes(
    session: Session,
    *,
    user_id: int,
) -> tuple[str | None, list[dict[str, Any]], bool]:
    votes: dict[str, int] = {}
    evidence: list[dict[str, Any]] = []

    def add_vote(source: str, value: str | None, weight: int) -> None:
        class_value = _normalize_class_id(value)
        if not class_value:
            return
        votes[class_value] = votes.get(class_value, 0) + weight
        evidence.append({"source": source, "class_id": class_value, "weight": weight})

    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
    if profile:
        add_vote("student_profile", profile.class_id, 6)

    latest_daily = session.exec(
        select(StudentDailySummary)
        .where(StudentDailySummary.user_id == user_id)
        .where(StudentDailySummary.class_id.is_not(None))
        .order_by(StudentDailySummary.summary_date.desc(), StudentDailySummary.id.desc())
    ).first()
    if latest_daily:
        add_vote("student_daily_summary", latest_daily.class_id, 4)

    latest_longitudinal = session.exec(
        select(StudentLongitudinalSummary)
        .where(StudentLongitudinalSummary.user_id == user_id)
        .where(StudentLongitudinalSummary.class_id.is_not(None))
        .order_by(StudentLongitudinalSummary.updated_at.desc(), StudentLongitudinalSummary.id.desc())
    ).first()
    if latest_longitudinal:
        add_vote("student_longitudinal_summary", latest_longitudinal.class_id, 3)

    latest_artifact = session.exec(
        select(AnalyticsArtifact)
        .where(AnalyticsArtifact.user_id == user_id)
        .where(AnalyticsArtifact.class_id.is_not(None))
        .order_by(AnalyticsArtifact.updated_at.desc(), AnalyticsArtifact.id.desc())
    ).first()
    if latest_artifact:
        add_vote("analytics_artifact", latest_artifact.class_id, 2)

    latest_task = session.exec(
        select(InterventionTask)
        .where(InterventionTask.student_id == user_id)
        .where(InterventionTask.class_id.is_not(None))
        .order_by(InterventionTask.created_at.desc(), InterventionTask.id.desc())
    ).first()
    if latest_task:
        add_vote("intervention_task", latest_task.class_id, 1)

    if not votes:
        return None, evidence, False

    ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    ambiguous = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
    return ranked[0][0], evidence, ambiguous


def list_student_class_assignments(
    session: Session,
    *,
    class_id: str | None = None,
    include_unassigned: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    profiles = {
        row.user_id: row
        for row in session.exec(select(StudentProfile))
    }
    latest_summary_map: dict[int, StudentDailySummary] = {}
    for row in session.exec(
        select(StudentDailySummary).order_by(StudentDailySummary.summary_date.desc(), StudentDailySummary.id.desc())
    ):
        latest_summary_map.setdefault(row.user_id, row)

    users = list(
        session.exec(
            select(User)
            .where(User.role == "student")
            .order_by(User.id)
        )
    )
    items: list[dict[str, Any]] = []
    normalized_filter = _normalize_class_id(class_id)
    for user in users:
        profile = profiles.get(user.id or 0)
        current_class_id = _normalize_class_id(profile.class_id if profile else None)
        if normalized_filter and current_class_id != normalized_filter:
            continue
        if not include_unassigned and normalized_filter is None and current_class_id is None:
            continue
        latest = latest_summary_map.get(user.id or 0)
        items.append(
            {
                "user_id": int(user.id or 0),
                "username": user.username,
                "role": user.role,
                "class_id": current_class_id,
                "latest_summary_class_id": latest.class_id if latest else None,
                "latest_score": _summary_score(latest) if latest else None,
                "risk_tags": _risk_tags(latest) if latest else [],
                "last_active_date": latest.summary_date if latest else None,
                "level": profile.level if profile else None,
            }
        )
    return items[:limit]


async def backfill_student_class_ids(
    session: Session,
    *,
    explicit_mapping: dict[int, str] | None = None,
    only_missing: bool = True,
    dry_run: bool = True,
    default_class_id: str | None = None,
    target_user_ids: list[int] | None = None,
) -> dict[str, Any]:
    mapping = {int(k): str(v) for k, v in (explicit_mapping or {}).items() if _normalize_class_id(str(v))}
    target_set = set(target_user_ids or [])
    users = list(
        session.exec(
            select(User)
            .where(User.role == "student")
            .order_by(User.id)
        )
    )
    summary = {
        "dry_run": dry_run,
        "only_missing": only_missing,
        "default_class_id": _normalize_class_id(default_class_id),
        "scanned_students": 0,
        "updated_students": 0,
        "skipped_students": 0,
        "ambiguous_students": 0,
        "items": [],
    }

    for user in users:
        user_id = int(user.id or 0)
        if target_set and user_id not in target_set:
            continue
        summary["scanned_students"] += 1
        profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
        current_class_id = _normalize_class_id(profile.class_id if profile else None)

        candidate_class_id: str | None = None
        source = "unknown"
        evidence: list[dict[str, Any]] = []
        ambiguous = False

        if user_id in mapping:
            candidate_class_id = _normalize_class_id(mapping[user_id])
            source = "explicit_mapping"
            evidence = [{"source": "explicit_mapping", "class_id": candidate_class_id, "weight": 99}]
        elif current_class_id:
            candidate_class_id = current_class_id
            source = "existing_profile"
            evidence = [{"source": "student_profile", "class_id": current_class_id, "weight": 99}]
        else:
            candidate_class_id, evidence, ambiguous = _infer_class_votes(session, user_id=user_id)
            source = "inferred"
            if not candidate_class_id:
                candidate_class_id = _normalize_class_id(default_class_id)
                if candidate_class_id:
                    source = "default_class_id"
                    evidence.append({"source": "default_class_id", "class_id": candidate_class_id, "weight": 1})

        if ambiguous:
            summary["ambiguous_students"] += 1
            summary["items"].append(
                {
                    "user_id": user_id,
                    "username": user.username,
                    "current_class_id": current_class_id,
                    "candidate_class_id": candidate_class_id,
                    "status": "ambiguous",
                    "source": source,
                    "evidence": evidence,
                }
            )
            continue

        if not candidate_class_id and only_missing:
            summary["skipped_students"] += 1
            summary["items"].append(
                {
                    "user_id": user_id,
                    "username": user.username,
                    "current_class_id": current_class_id,
                    "candidate_class_id": None,
                    "status": "skipped",
                    "source": source,
                    "evidence": evidence,
                }
            )
            continue

        should_apply = (not only_missing) or current_class_id is None or current_class_id != candidate_class_id
        if current_class_id == candidate_class_id and candidate_class_id is not None:
            status = "sync_only"
        elif should_apply:
            status = "apply"
        else:
            status = "skipped"

        item: dict[str, Any] = {
            "user_id": user_id,
            "username": user.username,
            "current_class_id": current_class_id,
            "candidate_class_id": candidate_class_id,
            "status": status if dry_run else "pending",
            "source": source,
            "evidence": evidence,
        }

        if not dry_run and candidate_class_id is not None and status in {"apply", "sync_only"}:
            result = await assign_student_class(
                session,
                user_id=user_id,
                class_id=candidate_class_id,
                sync_related_records=True,
                note=f"legacy_backfill:{source}",
            )
            item["status"] = "updated"
            item["sync_stats"] = result["sync_stats"]
            summary["updated_students"] += 1
        elif dry_run and candidate_class_id is not None and status in {"apply", "sync_only"}:
            summary["updated_students"] += 1
        else:
            summary["skipped_students"] += 1

        summary["items"].append(item)

    return summary
