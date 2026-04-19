"""Unified analytics orchestration/context layer.

This module keeps prompt construction, rolling-window aggregation, evidence
packing, RAG indexing, and retrieval in one place for analytics workflows.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from ...domain.analytics.models import (
    AnalyticsArtifact,
    InterventionTask,
    StudentDailySummary,
    StudentLongitudinalSummary,
)
from ...domain.models import LearningRecord, StudentProfile
from ...infrastructure.persistence.search.analytics_rag import (
    index_analytics_document,
    search_analytics_documents,
)
from ...llm import chat_complete, chat_complete_cloud_first

logger = logging.getLogger(__name__)

KEY_METRICS = [
    "vocab_growth_rate",
    "grammar_error_decay_slope",
    "logical_coherence_trend",
    "response_latency_avg_ms",
    "learning_stability_std",
    "topic_coverage_breadth",
    "autonomous_drive_count",
]

METRIC_LABELS = {
    "vocab_growth_rate": "词汇增长",
    "grammar_error_decay_slope": "语法收敛",
    "logical_coherence_trend": "逻辑连贯",
    "response_latency_avg_ms": "响应延迟",
    "learning_stability_std": "学习稳定性",
    "topic_coverage_breadth": "主题覆盖",
    "autonomous_drive_count": "自主学习",
}


def resolve_class_id_for_user(session: Session, user_id: int) -> str | None:
    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
    return profile.class_id if profile else None


def get_class_user_ids(session: Session, class_id: str) -> list[int]:
    profiles = list(
        session.exec(select(StudentProfile).where(StudentProfile.class_id == class_id))
    )
    return [p.user_id for p in profiles]


def get_class_summaries(
    session: Session,
    class_id: str,
    start_date: date,
    end_date: date,
) -> list[StudentDailySummary]:
    user_ids = get_class_user_ids(session, class_id)
    if not user_ids:
        return []
    stmt = (
        select(StudentDailySummary)
        .where(StudentDailySummary.user_id.in_(user_ids))
        .where(StudentDailySummary.summary_date >= start_date)
        .where(StudentDailySummary.summary_date <= end_date)
        .order_by(StudentDailySummary.summary_date, StudentDailySummary.user_id)
    )
    return list(session.exec(stmt))


def _avg(values: list[float | int | None]) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _extract_topics(summaries: list[StudentDailySummary]) -> list[str]:
    topics: list[str] = []
    for summary in summaries:
        raw = summary.raw_snapshot or {}
        values = raw.get("topics") or []
        if isinstance(values, list):
            for item in values:
                text = str(item or "").strip()
                if text and text not in topics:
                    topics.append(text)
    return topics[:12]


def _metric_deltas(summaries: list[StudentDailySummary]) -> dict[str, dict[str, float | None]]:
    if not summaries:
        return {}
    first = summaries[0]
    last = summaries[-1]
    deltas: dict[str, dict[str, float | None]] = {}
    for key in KEY_METRICS:
        first_val = getattr(first, key, None)
        last_val = getattr(last, key, None)
        avg_val = _avg([getattr(s, key, None) for s in summaries])
        delta = None
        if isinstance(first_val, (int, float)) and isinstance(last_val, (int, float)):
            delta = round(float(last_val) - float(first_val), 4)
        deltas[key] = {
            "first": round(float(first_val), 4) if isinstance(first_val, (int, float)) else None,
            "latest": round(float(last_val), 4) if isinstance(last_val, (int, float)) else None,
            "avg": avg_val,
            "delta": delta,
        }
    return deltas


def _risk_flags(
    latest: StudentDailySummary | None,
    deltas: dict[str, dict[str, float | None]],
    interventions: list[dict[str, Any]],
) -> list[str]:
    flags: list[str] = []
    if latest is None:
        return ["窗口内暂无有效日摘要"]
    if latest.vocab_growth_rate is not None and latest.vocab_growth_rate < 2:
        flags.append("基础词汇增长偏弱")
    if latest.learning_stability_std is not None and latest.learning_stability_std > 2:
        flags.append("学习波动偏大")
    if latest.response_latency_avg_ms is not None and latest.response_latency_avg_ms > 3000:
        flags.append("口语响应延迟偏高")
    grammar_delta = deltas.get("grammar_error_decay_slope", {}).get("delta")
    if isinstance(grammar_delta, (int, float)) and grammar_delta < 0:
        flags.append("语法表现近期回落")
    unresolved = [item for item in interventions if item.get("status") not in {"resolved", "dismissed"}]
    if len(unresolved) >= 2:
        flags.append("历史干预任务仍未闭环")
    return flags[:6]


def _strength_flags(
    latest: StudentDailySummary | None,
    deltas: dict[str, dict[str, float | None]],
) -> list[str]:
    flags: list[str] = []
    if latest is None:
        return flags
    if latest.topic_coverage_breadth is not None and latest.topic_coverage_breadth >= 5:
        flags.append("主题覆盖较广")
    if latest.autonomous_drive_count is not None and latest.autonomous_drive_count >= 2:
        flags.append("自主学习主动性较强")
    logical_delta = deltas.get("logical_coherence_trend", {}).get("delta")
    if isinstance(logical_delta, (int, float)) and logical_delta > 0:
        flags.append("逻辑表达持续改善")
    vocab_delta = deltas.get("vocab_growth_rate", {}).get("delta")
    if isinstance(vocab_delta, (int, float)) and vocab_delta > 0:
        flags.append("词汇增长趋势向上")
    return flags[:6]


def _recent_learning_evidence(
    session: Session,
    user_id: int,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    rows = list(
        session.exec(
            select(LearningRecord)
            .where(LearningRecord.user_id == user_id)
            .where(LearningRecord.created_at >= start_dt)
            .where(LearningRecord.created_at <= end_dt)
            .order_by(LearningRecord.created_at.desc())
        )
    )
    evidence: list[dict[str, Any]] = []
    for row in rows[:8]:
        evidence.append(
            {
                "type": row.type,
                "content": row.content[:160],
                "created_at": row.created_at.isoformat(),
                "meta_data": row.meta_data or {},
            }
        )
    return evidence


def _intervention_history(
    session: Session,
    user_id: int,
    class_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(InterventionTask).where(InterventionTask.student_id == user_id)
    if class_id:
        stmt = stmt.where(InterventionTask.class_id == class_id)
    tasks = list(session.exec(stmt.order_by(InterventionTask.created_at.desc())))
    history: list[dict[str, Any]] = []
    for task in tasks[:8]:
        history.append(
            {
                "agent_type": task.agent_type,
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "description": task.description,
                "created_at": task.created_at.isoformat(),
            }
        )
    return history


async def _index_student_summary(summary: StudentLongitudinalSummary) -> None:
    await index_analytics_document(
        {
            "artifact_type": "student_longitudinal_summary",
            "scope": "student",
            "class_id": summary.class_id,
            "user_id": str(summary.user_id),
            "title": f"学生{summary.user_id}近{summary.window_days}天纵向总结",
            "content": summary.llm_summary,
            "tags": summary.risk_flags + summary.strength_flags,
            "created_at": summary.updated_at.isoformat(),
        },
        doc_id=f"student-longitudinal-{summary.user_id}-{summary.class_id or 'none'}-{summary.window_start}-{summary.window_end}",
    )


async def generate_student_longitudinal_summary(
    session: Session,
    user_id: int,
    *,
    class_id: str | None = None,
    end_date: date | None = None,
    window_days: int = 14,
    force: bool = False,
) -> StudentLongitudinalSummary:
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(window_days - 1, 0))
    resolved_class_id = class_id if class_id is not None else resolve_class_id_for_user(session, user_id)

    existing = session.exec(
        select(StudentLongitudinalSummary)
        .where(StudentLongitudinalSummary.user_id == user_id)
        .where(StudentLongitudinalSummary.class_id == resolved_class_id)
        .where(StudentLongitudinalSummary.window_start == start_date)
        .where(StudentLongitudinalSummary.window_end == end_date)
        .where(StudentLongitudinalSummary.window_days == window_days)
    ).first()
    if existing and not force:
        return existing

    summaries = list(
        session.exec(
            select(StudentDailySummary)
            .where(StudentDailySummary.user_id == user_id)
            .where(StudentDailySummary.summary_date >= start_date)
            .where(StudentDailySummary.summary_date <= end_date)
            .order_by(StudentDailySummary.summary_date)
        )
    )
    latest = summaries[-1] if summaries else None
    resolved_class_id = resolved_class_id or (latest.class_id if latest else None)
    deltas = _metric_deltas(summaries)
    interventions = _intervention_history(session, user_id, resolved_class_id)
    risk_flags = _risk_flags(latest, deltas, interventions)
    strength_flags = _strength_flags(latest, deltas)
    topics = _extract_topics(summaries)
    evidence = [
        {
            "date": str(s.summary_date),
            "vocab_growth_rate": s.vocab_growth_rate,
            "grammar_error_decay_slope": s.grammar_error_decay_slope,
            "logical_coherence_trend": s.logical_coherence_trend,
            "learning_stability_std": s.learning_stability_std,
        }
        for s in summaries[-5:]
    ]
    learning_evidence = _recent_learning_evidence(session, user_id, start_date, end_date)

    if summaries:
        user_text = (
            f"学生ID: {user_id}\n"
            f"班级ID: {resolved_class_id or '未分班'}\n"
            f"时间窗口: {start_date} 至 {end_date}（{window_days}天）\n"
            f"风险标签: {'；'.join(risk_flags) or '暂无显著风险'}\n"
            f"优势标签: {'；'.join(strength_flags) or '暂无明显优势标签'}\n"
            f"关键指标变化: {deltas}\n"
            f"近期主题: {topics}\n"
            f"近期行为证据: {learning_evidence}\n"
            f"干预历史: {interventions}\n"
            f"近5日摘要切片: {evidence}\n"
            "请输出一段教师可直接阅读的纵向总结，要求："
            "1. 先讲趋势，再讲风险/亮点，再讲下一步建议；"
            "2. 必须结合时间变化，不要只复述当天；"
            "3. 语气克制、专业；"
            "4. 控制在220字以内。"
        )
        llm_summary = await chat_complete_cloud_first(
            system_prompt="你是一位严谨的外语学习分析师，请生成学生纵向历史总结。",
            user_text=user_text,
            timeout_seconds=10.0,
        )
        if "网络不太稳定" in llm_summary:
            llm_summary = (
                f"近{window_days}天内，学生{user_id}的学习趋势已完成客观汇总。"
                f"当前主要风险为：{('、'.join(risk_flags) or '暂无显著风险')}；"
                f"亮点为：{('、'.join(strength_flags) or '暂无明显亮点')}。"
            )
    else:
        llm_summary = f"学生{user_id}在 {start_date} 至 {end_date} 窗口内暂无足够日摘要数据。"

    record = existing or StudentLongitudinalSummary(
        user_id=user_id,
        class_id=resolved_class_id,
        window_start=start_date,
        window_end=end_date,
        window_days=window_days,
    )
    record.class_id = resolved_class_id
    record.summary_kind = "rolling_window"
    record.llm_summary = llm_summary
    record.risk_flags = risk_flags
    record.strength_flags = strength_flags
    record.metric_deltas = deltas
    record.evidence = evidence + learning_evidence[:4]
    record.source_summary_ids = [s.id for s in summaries if s.id is not None]
    record.meta_data = {
        "topics": topics,
        "interventions": interventions,
        "days_with_summary": len(summaries),
    }
    record.updated_at = datetime.utcnow()
    session.add(record)
    session.flush()
    await _index_student_summary(record)
    return record


async def upsert_analytics_artifact(
    session: Session,
    *,
    artifact_type: str,
    scope: str,
    title: str,
    content: str,
    class_id: str | None = None,
    user_id: int | None = None,
    agent_type: str | None = None,
    target_date: date | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    evidence: list[dict[str, Any]] | None = None,
    meta_data: dict[str, Any] | None = None,
) -> AnalyticsArtifact:
    artifact = session.exec(
        select(AnalyticsArtifact)
        .where(AnalyticsArtifact.artifact_type == artifact_type)
        .where(AnalyticsArtifact.scope == scope)
        .where(AnalyticsArtifact.class_id == class_id)
        .where(AnalyticsArtifact.user_id == user_id)
        .where(AnalyticsArtifact.agent_type == agent_type)
        .where(AnalyticsArtifact.target_date == target_date)
        .where(AnalyticsArtifact.window_start == window_start)
        .where(AnalyticsArtifact.window_end == window_end)
    ).first()
    if artifact is None:
        artifact = AnalyticsArtifact(
            artifact_type=artifact_type,
            scope=scope,
            class_id=class_id,
            user_id=user_id,
            agent_type=agent_type,
            target_date=target_date,
            window_start=window_start,
            window_end=window_end,
        )
    artifact.title = title
    artifact.content = content
    artifact.evidence = evidence or []
    artifact.meta_data = meta_data or {}
    artifact.updated_at = datetime.utcnow()
    session.add(artifact)
    session.flush()
    await index_analytics_document(
        {
            "artifact_type": artifact_type,
            "scope": scope,
            "class_id": class_id,
            "user_id": str(user_id) if user_id is not None else "",
            "agent_type": agent_type or "",
            "title": title,
            "content": content,
            "tags": list((meta_data or {}).get("tags") or []),
            "created_at": artifact.updated_at.isoformat(),
        },
        doc_id=(
            f"artifact-{artifact_type}-{scope}-{class_id or 'none'}-"
            f"{user_id or 'none'}-{agent_type or 'none'}-{target_date or window_end or 'none'}"
        ),
    )
    return artifact


async def search_analytics_evidence(
    session: Session,
    *,
    query: str,
    class_id: str | None = None,
    user_id: int | None = None,
    artifact_types: list[str] | None = None,
    size: int = 8,
) -> list[dict[str, Any]]:
    indexed = await search_analytics_documents(
        query,
        class_id=class_id,
        user_id=user_id,
        artifact_types=artifact_types,
        size=size,
    )
    if indexed:
        return indexed

    docs: list[dict[str, Any]] = []
    requested = set(artifact_types or [])
    if not requested or "student_longitudinal_summary" in requested:
        stmt = select(StudentLongitudinalSummary).order_by(StudentLongitudinalSummary.updated_at.desc())
        if class_id:
            stmt = stmt.where(StudentLongitudinalSummary.class_id == class_id)
        if user_id is not None:
            stmt = stmt.where(StudentLongitudinalSummary.user_id == user_id)
        for row in list(session.exec(stmt))[:size]:
            docs.append(
                {
                    "artifact_type": "student_longitudinal_summary",
                    "scope": "student",
                    "class_id": row.class_id,
                    "user_id": str(row.user_id),
                    "title": f"学生{row.user_id}近{row.window_days}天纵向总结",
                    "content": row.llm_summary,
                    "score": None,
                }
            )
    if len(docs) < size and (not requested or requested - {"student_longitudinal_summary"}):
        stmt = select(AnalyticsArtifact).order_by(AnalyticsArtifact.updated_at.desc())
        if class_id:
            stmt = stmt.where(AnalyticsArtifact.class_id == class_id)
        if user_id is not None:
            stmt = stmt.where(AnalyticsArtifact.user_id == user_id)
        if requested:
            stmt = stmt.where(AnalyticsArtifact.artifact_type.in_(list(requested - {"student_longitudinal_summary"})))
        for row in list(session.exec(stmt))[: max(0, size - len(docs))]:
            docs.append(
                {
                    "artifact_type": row.artifact_type,
                    "scope": row.scope,
                    "class_id": row.class_id,
                    "user_id": str(row.user_id) if row.user_id is not None else "",
                    "title": row.title,
                    "content": row.content,
                    "score": None,
                }
            )
    return docs[:size]


async def generate_class_window_analysis(
    session: Session,
    *,
    class_id: str,
    target_date: date,
    window_days: int = 3,
) -> AnalyticsArtifact:
    start_date = target_date - timedelta(days=max(window_days - 1, 0))
    summaries = get_class_summaries(session, class_id, start_date, target_date)
    user_ids = sorted({s.user_id for s in summaries})
    latest_by_student: dict[int, StudentDailySummary] = {}
    for summary in summaries:
        latest_by_student[summary.user_id] = summary

    longitudinal: list[StudentLongitudinalSummary] = []
    for user_id in user_ids[:20]:
        longitudinal.append(
            await generate_student_longitudinal_summary(
                session,
                user_id,
                class_id=class_id,
                end_date=target_date,
                window_days=max(window_days, 7),
            )
        )

    avg_vocab = _avg([s.vocab_growth_rate for s in latest_by_student.values()])
    avg_grammar = _avg([s.grammar_error_decay_slope for s in latest_by_student.values()])
    avg_latency = _avg([s.response_latency_avg_ms for s in latest_by_student.values()])
    risk_count = sum(
        1
        for s in latest_by_student.values()
        if (s.vocab_growth_rate is not None and s.vocab_growth_rate < 2)
        or (s.learning_stability_std is not None and s.learning_stability_std > 2)
    )
    topics = _extract_topics(summaries)
    rag_evidence = await search_analytics_evidence(
        session,
        query="班级近3天 学情 风险 进步 干预",
        class_id=class_id,
        artifact_types=["student_longitudinal_summary", "agent_report"],
        size=8,
    )
    evidence = [
        {
            "user_id": item.user_id,
            "summary": item.llm_summary[:180],
            "risk_flags": item.risk_flags,
        }
        for item in longitudinal[:6]
    ]
    prompt = (
        f"班级ID: {class_id}\n"
        f"分析窗口: {start_date} 至 {target_date}\n"
        f"班级人数: {len(user_ids)}\n"
        f"风险人数: {risk_count}\n"
        f"词汇均值: {avg_vocab}\n"
        f"语法均值: {avg_grammar}\n"
        f"响应延迟均值: {avg_latency}\n"
        f"近期主题: {topics}\n"
        f"学生纵向证据: {evidence}\n"
        f"RAG证据: {rag_evidence[:4]}\n"
        "请生成最近几天的班级情况分析，输出结构："
        "1. 班级状态总览；2. 主要进步点；3. 风险与建议。控制在260字以内。"
    )
    content = await chat_complete_cloud_first(
        system_prompt="你是一位严谨的班级学情分析师，请生成班级近几日分析。",
        user_text=prompt,
        timeout_seconds=10.0,
    )
    if "网络不太稳定" in content:
        content = (
            f"{class_id} 班级近{window_days}天整体状态已完成客观聚合。"
            f"当前风险人数约 {risk_count}，近期主题集中在 {('、'.join(topics[:4]) or '常规学习活动')}。"
        )

    return await upsert_analytics_artifact(
        session,
        artifact_type="class_window_analysis",
        scope="class",
        class_id=class_id,
        target_date=target_date,
        window_start=start_date,
        window_end=target_date,
        title=f"{class_id} 最近{window_days}天班级分析",
        content=content,
        evidence=evidence,
        meta_data={
            "window_days": window_days,
            "risk_count": risk_count,
            "student_count": len(user_ids),
            "topics": topics,
            "tags": ["class_window_analysis", "teacher_dashboard"],
        },
    )
