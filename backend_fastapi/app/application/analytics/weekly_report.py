"""班级周报生成模块。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from ...domain.analytics.models import AnalyticsArtifact, ClassDailySnapshot, StudentDailySummary
from ...llm import chat_complete, chat_complete_cloud_first
from .orchestration import (
    generate_class_window_analysis,
    generate_student_longitudinal_summary,
    get_class_summaries,
    search_analytics_evidence,
    upsert_analytics_artifact,
)

logger = logging.getLogger(__name__)

WEEKLY_REPORT_PROMPT_TEMPLATE = """你是一位资深外语教学分析师。请根据以下班级一周数据和历史证据，生成教师可直接使用的班级周报。

班级 ID: {class_id}
统计周期: {start_date} 至 {end_date}

【班级整体数据】
{class_data}

【学生分层摘要】
{student_summaries}

【RAG 历史证据】
{rag_evidence}

请用中文生成周报，包含以下板块：
1. 班级整体表现（能力分布、活跃趋势）
2. 进步学生亮点（具体维度与数据支撑）
3. 风险学生预警（具体原因与紧急程度）
4. 下周教学建议（可落地的 3-5 条建议）

要求：
- 语言简洁专业，教师可直接复制使用
- 每个结论尽量有数据支撑
- 对风险学生给出具体干预方向
"""


def _normalize_report_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, str):
            return content
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _aggregate_weekly_class_data(class_id: str, week_start: date, session: Session) -> dict[str, Any]:
    """聚合班级一周的横向快照数据。"""
    week_end = week_start + timedelta(days=6)
    snapshots = list(
        session.exec(
            select(ClassDailySnapshot)
            .where(ClassDailySnapshot.class_id == class_id)
            .where(ClassDailySnapshot.snapshot_date >= week_start)
            .where(ClassDailySnapshot.snapshot_date <= week_end)
            .order_by(ClassDailySnapshot.snapshot_date)
        )
    )
    summaries = get_class_summaries(session, class_id, week_start, week_end)

    if not snapshots and not summaries:
        return {"has_data": False, "message": "本周暂无班级快照数据"}

    lifts = [s.lower_tier_lift_rate for s in snapshots if s.lower_tier_lift_rate is not None]
    errors = [s.common_error_index for s in snapshots if s.common_error_index is not None]
    bottlenecks = [s.bottleneck_duration_days for s in snapshots if s.bottleneck_duration_days is not None]
    vocab = [s.vocab_growth_rate for s in summaries if s.vocab_growth_rate is not None]
    latency = [s.response_latency_avg_ms for s in summaries if s.response_latency_avg_ms is not None]
    active_students = len({s.user_id for s in summaries})

    return {
        "has_data": True,
        "snapshot_count": len(snapshots),
        "active_students": active_students,
        "avg_lower_tier_lift": round(sum(lifts) / len(lifts), 4) if lifts else None,
        "avg_common_error_index": round(sum(errors) / len(errors), 4) if errors else None,
        "avg_bottleneck_days": round(sum(bottlenecks) / len(bottlenecks), 4) if bottlenecks else None,
        "avg_vocab_growth": round(sum(vocab) / len(vocab), 4) if vocab else None,
        "avg_response_latency_ms": round(sum(latency) / len(latency), 2) if latency else None,
        "latest_date": str((snapshots[-1].snapshot_date if snapshots else week_end)),
    }


def _aggregate_weekly_student_summaries(class_id: str, week_start: date, session: Session) -> list[dict[str, Any]]:
    """聚合班级一周的学生纵向摘要（取最新一天）。"""
    week_end = week_start + timedelta(days=6)
    all_summaries = list(reversed(get_class_summaries(session, class_id, week_start, week_end)))

    # 去重：每个用户只取最新一天
    seen: set[int] = set()
    latest: list[StudentDailySummary] = []
    for s in all_summaries:
        if s.user_id not in seen:
            seen.add(s.user_id)
            latest.append(s)

    result: list[dict[str, Any]] = []
    for s in latest:
        result.append(
            {
                "user_id": s.user_id,
                "date": str(s.summary_date),
                "vocab_growth_rate": s.vocab_growth_rate,
                "sm2_retention_rate": s.sm2_retention_rate,
                "grammar_error_decay_slope": s.grammar_error_decay_slope,
                "logical_coherence_trend": s.logical_coherence_trend,
                "response_latency_avg_ms": s.response_latency_avg_ms,
                "learning_stability_std": s.learning_stability_std,
            }
        )
    return result


async def async_generate_class_weekly_report(
    session: Session,
    class_id: str,
    week_start: date | None = None,
) -> AnalyticsArtifact:
    """生成并持久化班级周报产物。"""
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday() + 1)
        if today.weekday() == 6:
            week_start = today
    week_end = week_start + timedelta(days=6)

    class_data = _aggregate_weekly_class_data(class_id, week_start, session)
    student_summaries = _aggregate_weekly_student_summaries(class_id, week_start, session)
    await generate_class_window_analysis(
        session,
        class_id=class_id,
        target_date=week_end,
        window_days=3,
    )

    for item in student_summaries[:20]:
        await generate_student_longitudinal_summary(
            session,
            item["user_id"],
            class_id=class_id,
            end_date=week_end,
            window_days=14,
        )

    rag_evidence = await search_analytics_evidence(
        session,
        query="班级周报 风险 进步 干预演进 纵向总结",
        class_id=class_id,
        artifact_types=["student_longitudinal_summary", "agent_report", "class_window_analysis"],
        size=10,
    )

    if not class_data.get("has_data") and not student_summaries:
        content = (
            f"【{class_id} 班级周报】\n"
            f"统计周期：{week_start} 至 {week_end}\n\n"
            "本周数据收集中，暂无足够数据生成详细分析。"
        )
    else:
        prompt = WEEKLY_REPORT_PROMPT_TEMPLATE.format(
            class_id=class_id,
            start_date=str(week_start),
            end_date=str(week_end),
            class_data=json.dumps(class_data, ensure_ascii=False, indent=2),
            student_summaries=json.dumps(student_summaries[:20], ensure_ascii=False, indent=2),
            rag_evidence=json.dumps(rag_evidence[:8], ensure_ascii=False, indent=2),
        )
        content = await chat_complete_cloud_first(
            system_prompt="你是一位资深外语教学分析师。请根据数据和历史证据生成简洁专业的周报。",
            user_text=prompt,
            timeout_seconds=10.0,
        )
        content = _normalize_report_content(content)
        if "网络不太稳定" in content:
            content = (
                f"【{class_id} 班级周报】\n"
                f"统计周期：{week_start} 至 {week_end}\n\n"
                f"班级活跃学生数：{class_data.get('active_students')}\n"
                f"平均词汇增长：{class_data.get('avg_vocab_growth')}\n"
                f"平均响应延迟：{class_data.get('avg_response_latency_ms')}\n"
                f"已收集 {len(student_summaries)} 份学生摘要与 {len(rag_evidence)} 条历史证据。"
            )

    return await upsert_analytics_artifact(
        session,
        artifact_type="weekly_report",
        scope="class",
        class_id=class_id,
        window_start=week_start,
        window_end=week_end,
        title=f"{class_id} {week_start} 周报",
        content=content,
        evidence=rag_evidence[:8],
        meta_data={
            "class_data": class_data,
            "student_count": len(student_summaries),
            "week_start": str(week_start),
            "week_end": str(week_end),
            "tags": ["weekly_report", class_id],
        },
    )


def generate_class_weekly_report(class_id: str, week_start: date | None = None) -> AnalyticsArtifact:
    """同步包装，供任务调度侧复用。"""
    with Session(get_engine()) as session:
        record = asyncio.run(async_generate_class_weekly_report(session, class_id, week_start))
        session.commit()
        session.refresh(record)
        logger.info("Generated weekly report for class=%s week=%s", class_id, week_start)
        return record
