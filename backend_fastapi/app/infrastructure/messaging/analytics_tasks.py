"""Celery 异步任务 — 学情分析模块定时任务。

- generate_all_daily_summaries_task: 每日凌晨为所有学生生成纵向摘要
- generate_class_weekly_report_task: 每周日凌晨生成班级周报
- run_tiered_analysis_task: 运行 Agent-1/2/3 分层分析
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from ...domain.analytics.models import ClassDailySnapshot, InterventionTask, StudentDailySummary
from ...domain.models import User
from ..application.analytics.agents import BottomTierAgent, MiddleTierAgent, TopTierAgent
from ..application.analytics.class_snapshot import generate_class_daily_snapshot
from ..application.analytics.daily_summary import generate_student_daily_summary
from ..application.analytics.weekly_report import generate_class_weekly_report
from .celery_app import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def generate_all_daily_summaries_task(self, target_date_str: str | None = None) -> dict[str, Any]:
    """每日凌晨为所有学生生成纵向摘要，并为所有有数据的班级生成横向快照。"""
    try:
        if target_date_str:
            target_date = date.fromisoformat(target_date_str)
        else:
            target_date = date.today() - timedelta(days=1)

        with Session(get_engine()) as session:
            users = list(session.exec(select(User).where(User.role == "student")))

        created = 0
        skipped = 0
        for user in users:
            # 检查是否已存在
            with Session(get_engine()) as session:
                existing = session.exec(
                    select(StudentDailySummary)
                    .where(StudentDailySummary.user_id == user.id)
                    .where(StudentDailySummary.summary_date == target_date)
                ).first()
                if existing:
                    skipped += 1
                    continue

            try:
                summary = generate_student_daily_summary(user.id, target_date)
                with Session(get_engine()) as session:
                    session.add(summary)
                    session.commit()
                    created += 1
            except Exception as exc:
                logger.error("Failed to generate summary for user=%s: %s", user.id, exc)

        # 生成班级横向快照
        snapshot_created = 0
        snapshot_skipped = 0
        with Session(get_engine()) as session:
            class_ids = {
                row.class_id
                for row in session.exec(select(StudentDailySummary.class_id).where(StudentDailySummary.summary_date == target_date))
                if row.class_id
            }
        for class_id in class_ids:
            with Session(get_engine()) as session:
                existing = session.exec(
                    select(ClassDailySnapshot)
                    .where(ClassDailySnapshot.class_id == class_id)
                    .where(ClassDailySnapshot.snapshot_date == target_date)
                ).first()
                if existing:
                    snapshot_skipped += 1
                    continue
            try:
                snapshot = generate_class_daily_snapshot(class_id, target_date)
                with Session(get_engine()) as session:
                    session.add(snapshot)
                    session.commit()
                    snapshot_created += 1
            except Exception as exc:
                logger.error("Failed to generate snapshot for class=%s: %s", class_id, exc)

        result = {
            "target_date": str(target_date),
            "total_students": len(users),
            "created": created,
            "skipped": skipped,
            "snapshot_created": snapshot_created,
            "snapshot_skipped": snapshot_skipped,
        }
        logger.info("Daily summary task completed: %s", result)
        return result
    except Exception as exc:
        logger.error("generate_all_daily_summaries_task error: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@app.task(bind=True, max_retries=3)
def run_tiered_analysis_task(self, class_id: str, target_date_str: str | None = None) -> dict[str, Any]:
    """运行 Agent-1/2/3 分层分析并生成干预任务。"""
    try:
        if target_date_str:
            target_date = date.fromisoformat(target_date_str)
        else:
            target_date = date.today() - timedelta(days=1)

        with Session(get_engine()) as session:
            summaries = list(
                session.exec(
                    select(StudentDailySummary).where(StudentDailySummary.summary_date == target_date)
                )
            )
            snapshot = session.exec(
                select(ClassDailySnapshot)
                .where(ClassDailySnapshot.class_id == class_id)
                .where(ClassDailySnapshot.snapshot_date == target_date)
            ).first()

        if not summaries:
            return {"class_id": class_id, "target_date": str(target_date), "status": "no_data"}

        # 运行三个 Agent
        bottom_report = BottomTierAgent.analyze(summaries, class_id=class_id)
        middle_report = MiddleTierAgent.analyze(summaries, class_snapshot=snapshot, class_id=class_id)
        top_report = TopTierAgent.analyze(summaries, class_id=class_id)

        # 持久化干预任务
        total_tasks = 0
        for report in [bottom_report, middle_report, top_report]:
            for task in report.intervention_tasks:
                with Session(get_engine()) as session:
                    session.add(task)
                    session.commit()
                    total_tasks += 1

        result = {
            "class_id": class_id,
            "target_date": str(target_date),
            "student_count": len(summaries),
            "intervention_tasks_created": total_tasks,
            "bottom_risks": len(bottom_report.risk_students),
            "middle_risks": len(middle_report.risk_students),
            "top_risks": len(top_report.risk_students),
        }
        logger.info("Tiered analysis task completed: %s", result)
        return result
    except Exception as exc:
        logger.error("run_tiered_analysis_task error: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@app.task(bind=True, max_retries=3)
def generate_class_weekly_report_task(self, class_id: str, week_start_str: str | None = None) -> dict[str, Any]:
    """每周日凌晨生成班级周报。"""
    try:
        if week_start_str:
            week_start = date.fromisoformat(week_start_str)
        else:
            today = date.today()
            week_start = today - timedelta(days=today.weekday() + 1)
            if today.weekday() == 6:
                week_start = today

        record = generate_class_weekly_report(class_id, week_start)
        with Session(get_engine()) as session:
            session.add(record)
            session.commit()
            session.refresh(record)

        result = {
            "class_id": class_id,
            "week_start": str(week_start),
            "record_id": record.id,
            "content_length": len(record.content),
        }
        logger.info("Weekly report task completed: %s", result)
        return result
    except Exception as exc:
        logger.error("generate_class_weekly_report_task error: %s", exc)
        raise self.retry(exc=exc, countdown=300)
