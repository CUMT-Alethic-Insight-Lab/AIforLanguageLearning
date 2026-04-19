"""Agent-1/2/3: 分层分析引擎。

- BottomTierAgent: 底层托底（后 20%）
- MiddleTierAgent: 中层突破（中间 60%）
- TopTierAgent: 顶层突破（前 20%）

每个 Agent 接收 StudentDailySummary 列表，输出结构化分析报告与干预任务。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from ...domain.analytics.models import (
    ClassDailySnapshot,
    InterventionTask,
    StudentDailySummary,
)
from ...domain.models import User
from ...llm import chat_complete, chat_complete_cloud_first
from .orchestration import (
    generate_student_longitudinal_summary,
    get_class_summaries,
    search_analytics_evidence,
    upsert_analytics_artifact,
)

logger = logging.getLogger(__name__)



# ───────────────────────────────────────────────
# LLM 增强辅助函数
# ───────────────────────────────────────────────


async def _llm_enhance_insights(
    agent_type: str,
    risk_flags: list[str],
    raw_insights: list[str],
    raw_suggestions: list[str],
    profile: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """使用本地 LLM 对 Agent 报告进行自然语言润色。

    将硬编码的洞察和建议转化为教师友好的表述。
    结合学生画像（level、goals、interests）生成个性化建议。
    失败时返回原始内容（降级保护）。
    """
    if not risk_flags:
        return raw_insights, raw_suggestions

    system_prompt = (
        "你是一位资深外语教学分析师。请将以下机器生成的学情分析转化为"
        "教师能直接理解的自然语言。要求：\n"
        "1. 不使用行业黑话，用通俗的教学语言\n"
        "2. 客观总结学生现状，不夸大不贬低\n"
        "3. 建议要具体、可落地，避免空泛\n"
        "4. 语气平和、专业、有温度\n"
        "5. 输出格式：先洞察（1-2句），后建议（2-3条）"
    )

    user_text = (
        f"【学生层级】{agent_type}\n"
        f"【风险点】{', '.join(risk_flags)}\n"
        f"【原始洞察】{'；'.join(raw_insights)}\n"
        f"【原始建议】{'；'.join(raw_suggestions)}\n"
    )

    # 注入用户画像上下文
    if profile:
        user_text += (
            f"\n【学生画像】\n"
            f"英语水平: {profile.get('level', '未知')}\n"
            f"学习目标: {', '.join(profile.get('goals', [])) or '未设置'}\n"
            f"兴趣爱好: {', '.join(profile.get('interests', [])) or '未设置'}\n"
            f"请结合学生的目标和兴趣给出个性化建议。"
        )

    user_text += "\n\n请用中文输出：\n洞察：...\n建议：..."

    try:
        response = await chat_complete_cloud_first(
            system_prompt=system_prompt,
            user_text=user_text,
            timeout_seconds=10.0,
        )
        if not response or "网络不太稳定" in response:
            return raw_insights, raw_suggestions

        # 解析 LLM 输出
        insights: list[str] = []
        suggestions: list[str] = []
        current_section = None
        for line in response.splitlines():
            line = line.strip()
            if line.startswith("洞察"):
                current_section = "insights"
                continue
            elif line.startswith("建议"):
                current_section = "suggestions"
                continue
            if line and current_section == "insights":
                insights.append(line.lstrip("-• "))
            elif line and current_section == "suggestions":
                suggestions.append(line.lstrip("-• "))

        return (insights if insights else raw_insights), (suggestions if suggestions else raw_suggestions)
    except Exception as exc:
        logger.warning("LLM enhance failed for %s: %s", agent_type, exc)
        return raw_insights, raw_suggestions


# ───────────────────────────────────────────────
# 数据收集接口（预留/占位）
# ───────────────────────────────────────────────


def _fetch_summaries_for_class(class_id: str, target_date: date, session: Session) -> list[StudentDailySummary]:
    """获取班级某日的所有学生摘要。"""
    return get_class_summaries(session, class_id, target_date, target_date)


def _fetch_class_snapshot(class_id: str, target_date: date, session: Session) -> ClassDailySnapshot | None:
    """获取班级某日横向快照。"""
    stmt = (
        select(ClassDailySnapshot)
        .where(ClassDailySnapshot.class_id == class_id)
        .where(ClassDailySnapshot.snapshot_date == target_date)
    )
    return session.exec(stmt).first()


def _get_student_total_score(summary: StudentDailySummary) -> float:
    """基于现有维度计算一个综合总分（用于分层）。"""
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
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


# ───────────────────────────────────────────────
# 报告结构
# ───────────────────────────────────────────────


@dataclass
class TierReport:
    """单个 Agent 的分析报告。"""

    agent_type: str
    target_date: date
    risk_students: list[dict[str, Any]] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    intervention_tasks: list[InterventionTask] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


# ───────────────────────────────────────────────
# Agent-1: 底层托底
# ───────────────────────────────────────────────


class BottomTierAgent:
    """关注学习困难学生，识别基础缺口，设计最小有效干预。"""

    @staticmethod
    async def analyze(
        summaries: list[StudentDailySummary],
        class_id: str | None = None,
        llm_enhance: bool = False,
        student_contexts: dict[int, dict[str, Any]] | None = None,
    ) -> TierReport:
        """分析底层学生风险。

        关注指标:
        - C1: 最小有效干预点 (mastery_level < 2 连续出现)
        - C2: 基础词汇缺口率 (预留)
        - C3: 学习动机衰减 (learning_stability_std 异常 + latency 变长)
        - C4: L1 语言依赖度 (预留)
        - C5: 挫败感触发阈值 (预留)
        - A1: 基础词汇掌握 (vocab_growth_rate 低)
        - A16: 学习稳定性 (learning_stability_std 高)
        """
        report = TierReport(agent_type="bottom", target_date=summaries[0].summary_date if summaries else date.today())

        # 按综合分排序，取后 20%
        scored = [(s, _get_student_total_score(s)) for s in summaries]
        scored.sort(key=lambda x: x[1])
        cutoff = max(1, len(scored) // 5)
        bottom_summaries = scored[:cutoff]

        for summary, score in bottom_summaries:
            risk_flags: list[str] = []
            context = (student_contexts or {}).get(summary.user_id, {})

            # C1: 词汇掌握薄弱
            if summary.vocab_growth_rate is not None and summary.vocab_growth_rate < 2.0:
                risk_flags.append("基础词汇掌握薄弱")

            # C3: 学习稳定性差
            if summary.learning_stability_std is not None and summary.learning_stability_std > 2.0:
                risk_flags.append("学习行为波动大，动机可能衰减")

            # A11: 响应潜伏期异常长
            if summary.response_latency_avg_ms is not None and summary.response_latency_avg_ms > 3000:
                risk_flags.append("对话响应异常迟缓")

            if context.get("longitudinal_risk_flags"):
                risk_flags.extend(
                    [
                        flag
                        for flag in context["longitudinal_risk_flags"]
                        if flag not in risk_flags
                    ][:2]
                )

            if risk_flags:
                # 注入学生画像数据
                profile_dict = {
                    "level": summary.level,
                    "goals": summary.goals,
                    "interests": summary.interests,
                } if summary.level else None

                report.risk_students.append(
                    {
                        "user_id": summary.user_id,
                        "score": round(score, 2),
                        "risk_flags": risk_flags,
                        "profile": profile_dict,
                    }
                )
                if context.get("longitudinal_summary"):
                    report.evidence.append(
                        {
                            "user_id": summary.user_id,
                            "source": "student_longitudinal_summary",
                            "excerpt": str(context["longitudinal_summary"])[:180],
                        }
                    )

                # 生成干预任务（结合画像个性化）
                actions = [
                    "简化当日词汇任务至 5 个核心词",
                    "增加正向反馈频率",
                    "推送基础语法微课",
                ]
                # 如果有兴趣标签，增加个性化推荐
                if summary.interests:
                    actions.append(f"结合兴趣({', '.join(summary.interests[:2])})设计情境练习")

                task = InterventionTask(
                    student_id=summary.user_id,
                    class_id=class_id,
                    agent_type="bottom",
                    title=f"底层托底：学生 {summary.user_id} 基础能力干预",
                    description="; ".join(risk_flags),
                    suggestion={
                        "actions": actions,
                        "focus_dimensions": ["vocab_growth_rate", "learning_stability_std"],
                        "profile": profile_dict,
                    },
                    status="pending",
                    priority="high" if len(risk_flags) >= 2 else "normal",
                    due_date=date.today() + timedelta(days=3),
                )
                report.intervention_tasks.append(task)

        if report.risk_students:
            report.insights.append(f"识别出 {len(report.risk_students)} 名底层风险学生")
            report.suggestions.append("建议优先执行词汇补底与动机激励干预")
        else:
            report.insights.append("底层学生群体今日无显著风险信号")

        # LLM 增强：将硬编码洞察转化为教师友好语言
        if llm_enhance and report.risk_students:
            all_flags: list[str] = []
            profile_dict: dict[str, Any] | None = None
            for rs in report.risk_students:
                all_flags.extend(rs.get("risk_flags", []))
                # 从第一个风险学生提取画像（简化处理）
                if profile_dict is None and "profile" in rs:
                    profile_dict = rs["profile"]
            report.insights, report.suggestions = await _llm_enhance_insights(
                agent_type="bottom",
                risk_flags=list(set(all_flags)),
                raw_insights=report.insights,
                raw_suggestions=report.suggestions,
                profile=profile_dict,
            )

        return report


# ───────────────────────────────────────────────
# Agent-2: 中层突破
# ───────────────────────────────────────────────


class MiddleTierAgent:
    """关注中下层到中上层学生，识别进步趋势和集中错误。"""

    @staticmethod
    async def analyze(
        summaries: list[StudentDailySummary],
        class_snapshot: ClassDailySnapshot | None = None,
        class_id: str | None = None,
        llm_enhance: bool = False,
        student_contexts: dict[int, dict[str, Any]] | None = None,
    ) -> TierReport:
        """分析中层学生突破机会。

        关注指标:
        - B1-B10: 班级趋势维度
        - A6-A10: 作文能力
        - A11-A15: 口语能力
        """
        report = TierReport(agent_type="middle", target_date=summaries[0].summary_date if summaries else date.today())

        # 按综合分排序，取中间 60%
        scored = [(s, _get_student_total_score(s)) for s in summaries]
        scored.sort(key=lambda x: x[1])
        n = len(scored)
        lower = n // 5
        upper = n - n // 5
        middle_summaries = scored[lower:upper]

        # 识别进步斜率高的学生（grammar_error_decay_slope 为正）
        rising_students: list[dict[str, Any]] = []
        stagnant_students: list[dict[str, Any]] = []

        for summary, score in middle_summaries:
            context = (student_contexts or {}).get(summary.user_id, {})
            if summary.grammar_error_decay_slope is not None and summary.grammar_error_decay_slope > 0.5:
                rising_students.append({"user_id": summary.user_id, "score": round(score, 2)})

            if summary.logical_coherence_trend is not None and summary.logical_coherence_trend < 60:
                stagnant_students.append(
                    {
                        "user_id": summary.user_id,
                        "score": round(score, 2),
                        "flag": "逻辑连贯度低于 60，可能处于瓶颈期",
                    }
                )
                if context.get("longitudinal_summary"):
                    report.evidence.append(
                        {
                            "user_id": summary.user_id,
                            "source": "student_longitudinal_summary",
                            "excerpt": str(context["longitudinal_summary"])[:180],
                        }
                    )

        if rising_students:
            report.insights.append(f"中层群体中有 {len(rising_students)} 名学生作文语法错误显著收敛")
        if stagnant_students:
            report.insights.append(f"中层群体中有 {len(stagnant_students)} 名学生可能处于能力瓶颈期")

        # LLM 增强
        if llm_enhance and (rising_students or stagnant_students):
            flags: list[str] = []
            if rising_students:
                flags.append("部分学生进步明显")
            if stagnant_students:
                flags.append("部分学生处于瓶颈期")
            report.insights, report.suggestions = await _llm_enhance_insights(
                agent_type="middle",
                risk_flags=flags,
                raw_insights=report.insights,
                raw_suggestions=report.suggestions,
                profile=None,  # 中层分析是群体分析，不针对单个学生画像
            )

        # 基于班级快照生成建议
        if class_snapshot:
            if class_snapshot.common_error_index is not None and class_snapshot.common_error_index > 0.3:
                report.suggestions.append(
                    f"班级共性错误指数较高 ({class_snapshot.common_error_index:.2f})，建议组织专项语法练习"
                )
            if class_snapshot.bottleneck_duration_days is not None and class_snapshot.bottleneck_duration_days > 7:
                report.suggestions.append(
                    f"中上层瓶颈期平均 {class_snapshot.bottleneck_duration_days:.1f} 天，建议调整难度梯度"
                )

        # 为瓶颈期学生生成干预任务
        for stu in stagnant_students:
            task = InterventionTask(
                student_id=stu["user_id"],
                class_id=class_id,
                agent_type="middle",
                title=f"中层突破：学生 {stu['user_id']} 瓶颈期干预",
                description=stu["flag"],
                suggestion={
                    "actions": [
                        "推荐中等难度对话场景",
                        "提供结构模板练习",
                        "设置阶梯式作文目标",
                    ],
                    "focus_dimensions": ["logical_coherence_trend", "grammar_error_decay_slope"],
                },
                status="pending",
                priority="normal",
                due_date=date.today() + timedelta(days=5),
            )
            report.intervention_tasks.append(task)

        return report


# ───────────────────────────────────────────────
# Agent-3: 顶层突破
# ───────────────────────────────────────────────


class TopTierAgent:
    """关注高水平学生，识别瓶颈，设计高阶能力培养方案。"""

    @staticmethod
    async def analyze(
        summaries: list[StudentDailySummary],
        class_id: str | None = None,
        llm_enhance: bool = False,
        student_contexts: dict[int, dict[str, Any]] | None = None,
    ) -> TierReport:
        """分析顶层学生高阶能力。

        关注指标:
        - D1-D5: 顶层突破维度（预留）
        - A19, A20: 自主学习、主题覆盖
        """
        report = TierReport(agent_type="top", target_date=summaries[0].summary_date if summaries else date.today())

        # 按综合分排序，取前 20%
        scored = [(s, _get_student_total_score(s)) for s in summaries]
        scored.sort(key=lambda x: x[1], reverse=True)
        cutoff = max(1, len(scored) // 5)
        top_summaries = scored[:cutoff]

        for summary, score in top_summaries:
            # 检测高阶能力瓶颈：综合分高但某些维度停滞
            flags: list[str] = []
            context = (student_contexts or {}).get(summary.user_id, {})

            # 如果自主学习能力未体现，提示瓶颈
            if summary.autonomous_drive_count is not None and summary.autonomous_drive_count < 2:
                flags.append("高阶学生自主探索行为不足")

            # 如果主题覆盖广度不够
            if summary.topic_coverage_breadth is not None and summary.topic_coverage_breadth < 5:
                flags.append("主题覆盖广度有限，可能处于舒适区")

            # D1-D5 预留维度：当前无数据时跳过
            # TODO: 当修辞分析、跨文化思辨等 NLP 模块就绪后接入

            if flags:
                # 注入学生画像数据
                profile_dict = {
                    "level": summary.level,
                    "goals": summary.goals,
                    "interests": summary.interests,
                } if summary.level else None

                report.risk_students.append(
                    {
                        "user_id": summary.user_id,
                        "score": round(score, 2),
                        "risk_flags": flags,
                        "profile": profile_dict,
                    }
                )
                if context.get("longitudinal_summary"):
                    report.evidence.append(
                        {
                            "user_id": summary.user_id,
                            "source": "student_longitudinal_summary",
                            "excerpt": str(context["longitudinal_summary"])[:180],
                        }
                    )

                # 生成干预任务（结合画像个性化）
                actions = [
                    "推荐学术写作任务",
                    "开启跨文化辩论场景",
                    "推送修辞手法专题",
                ]
                # 如果有目标标签，增加目标导向推荐
                if summary.goals:
                    actions.append(f"结合目标({', '.join(summary.goals[:2])})设计高阶挑战")

                task = InterventionTask(
                    student_id=summary.user_id,
                    class_id=class_id,
                    agent_type="top",
                    title=f"顶层突破：学生 {summary.user_id} 高阶能力培养",
                    description="; ".join(flags),
                    suggestion={
                        "actions": actions,
                        "focus_dimensions": ["autonomous_drive_count", "topic_coverage_breadth"],
                        "profile": profile_dict,
                    },
                    status="pending",
                    priority="normal",
                    due_date=date.today() + timedelta(days=7),
                )
                report.intervention_tasks.append(task)

        if report.risk_students:
            report.insights.append(f"识别出 {len(report.risk_students)} 名顶层学生存在高阶瓶颈")
            report.suggestions.append("建议引入辩论、学术写作等高阶任务")
        else:
            report.insights.append("顶层学生群体今日表现稳健，无明显瓶颈")

        # LLM 增强
        if llm_enhance and report.risk_students:
            all_flags: list[str] = []
            profile_dict: dict[str, Any] | None = None
            for rs in report.risk_students:
                all_flags.extend(rs.get("risk_flags", []))
                if profile_dict is None and "profile" in rs:
                    profile_dict = rs["profile"]
            report.insights, report.suggestions = await _llm_enhance_insights(
                agent_type="top",
                risk_flags=list(set(all_flags)),
                raw_insights=report.insights,
                raw_suggestions=report.suggestions,
                profile=profile_dict,
            )

        return report


def _serialize_report(report: TierReport) -> dict[str, Any]:
    return {
        "agent_type": report.agent_type,
        "target_date": str(report.target_date),
        "risk_students": report.risk_students,
        "insights": report.insights,
        "suggestions": report.suggestions,
        "evidence": report.evidence,
        "intervention_tasks": [
            {
                "student_id": task.student_id,
                "class_id": task.class_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "due_date": str(task.due_date) if task.due_date else None,
            }
            for task in report.intervention_tasks
        ],
    }


def _upsert_intervention_task(session: Session, task: InterventionTask) -> InterventionTask:
    existing = session.exec(
        select(InterventionTask)
        .where(InterventionTask.student_id == task.student_id)
        .where(InterventionTask.class_id == task.class_id)
        .where(InterventionTask.agent_type == task.agent_type)
        .where(InterventionTask.title == task.title)
        .where(InterventionTask.status == "pending")
    ).first()
    if existing:
        existing.description = task.description
        existing.suggestion = task.suggestion
        existing.priority = task.priority
        existing.due_date = task.due_date
        session.add(existing)
        return existing
    session.add(task)
    return task


async def run_and_persist_tiered_analysis(
    session: Session,
    *,
    class_id: str,
    target_date: date,
    llm_enhance: bool = False,
    context_window_days: int = 14,
) -> list[TierReport]:
    summaries = _fetch_summaries_for_class(class_id, target_date, session)
    if not summaries:
        return []
    snapshot = _fetch_class_snapshot(class_id, target_date, session)

    student_contexts: dict[int, dict[str, Any]] = {}
    for summary in summaries:
        longitudinal = await generate_student_longitudinal_summary(
            session,
            summary.user_id,
            class_id=class_id,
            end_date=target_date,
            window_days=context_window_days,
        )
        student_contexts[summary.user_id] = {
            "longitudinal_summary": longitudinal.llm_summary,
            "longitudinal_risk_flags": longitudinal.risk_flags,
            "strength_flags": longitudinal.strength_flags,
        }

    reports = [
        await BottomTierAgent.analyze(
            summaries,
            class_id=class_id,
            llm_enhance=llm_enhance,
            student_contexts=student_contexts,
        ),
        await MiddleTierAgent.analyze(
            summaries,
            class_snapshot=snapshot,
            class_id=class_id,
            llm_enhance=llm_enhance,
            student_contexts=student_contexts,
        ),
        await TopTierAgent.analyze(
            summaries,
            class_id=class_id,
            llm_enhance=llm_enhance,
            student_contexts=student_contexts,
        ),
    ]

    rag_evidence = await search_analytics_evidence(
        session,
        query="班级分层分析 风险 干预 进步",
        class_id=class_id,
        artifact_types=["student_longitudinal_summary", "agent_report"],
        size=6,
    )

    for report in reports:
        for task in report.intervention_tasks:
            _upsert_intervention_task(session, task)
        title = f"{class_id} {target_date} {report.agent_type}层分析"
        content = "\n".join(report.insights + report.suggestions).strip() or "暂无显著信号"
        await upsert_analytics_artifact(
            session,
            artifact_type="agent_report",
            scope="class",
            class_id=class_id,
            agent_type=report.agent_type,
            target_date=target_date,
            title=title,
            content=content,
            evidence=report.evidence + rag_evidence[:2],
            meta_data={
                "report": _serialize_report(report),
                "tags": ["agent_report", report.agent_type, class_id],
            },
        )
    session.flush()
    return reports
