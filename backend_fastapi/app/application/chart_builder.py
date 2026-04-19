"""后端统一图表构建器（能力复用层）。

为 analytics、作文模块、教师端等提供统一的 ChartData 结构生成能力，
消除各模块手工拼装 dict 的重复和格式不一致问题。

ChartData Schema（与前端 BaseChart.vue / ECharts 兼容）：
    {
        "type": "pie" | "bar" | "line" | "radar",
        "title": str,
        "labels": list[str],
        "datasets": list[{ "label": str, "data": list[float] }],
    }
"""

from __future__ import annotations

from typing import Any


def build_pie_chart(title: str, labels: list[str], data: list[float], dataset_label: str = "数值") -> dict[str, Any]:
    """构建饼图。"""
    return {
        "type": "pie",
        "title": title,
        "labels": list(labels),
        "datasets": [{"label": dataset_label, "data": list(data)}],
    }


def build_bar_chart(
    title: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建柱状图。

    datasets 示例:
        [
            {"label": "当天", "data": [80, 75, 90]},
            {"label": "均值", "data": [70, 72, 85]},
        ]
    """
    return {
        "type": "bar",
        "title": title,
        "labels": list(labels),
        "datasets": [
            {"label": ds.get("label", ""), "data": list(ds.get("data", []))}
            for ds in datasets
        ],
    }


def build_line_chart(
    title: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建折线图。"""
    return {
        "type": "line",
        "title": title,
        "labels": list(labels),
        "datasets": [
            {"label": ds.get("label", ""), "data": list(ds.get("data", []))}
            for ds in datasets
        ],
    }


def build_radar_chart(
    title: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建雷达图。"""
    return {
        "type": "radar",
        "title": title,
        "labels": list(labels),
        "datasets": [
            {"label": ds.get("label", ""), "data": list(ds.get("data", []))}
            for ds in datasets
        ],
    }


# ── 作文模块专用快捷构建器 ──

def build_essay_dimension_radar(dimensions: dict[str, dict[str, float]], title: str = "作文能力雷达") -> dict[str, Any]:
    """根据 EssayResult.dimensions 构建作文四维雷达图。

    dimensions 格式:
        {
            "content": {"score": 8.0, "weight": 0.30, "weighted": 2.40},
            "structure": {"score": 7.0, ...},
            "language": {"score": 8.0, ...},
            "grammar": {"score": 6.0, ...},
        }
    """
    labels = ["内容", "结构", "语言", "语法"]
    keys = ["content", "structure", "language", "grammar"]
    data = [dimensions.get(k, {}).get("score", 0) * 10 for k in keys]
    return build_radar_chart(
        title=title,
        labels=labels,
        datasets=[{"label": "本次批改", "data": data}],
    )


def build_essay_history_line(
    dates: list[str],
    content_scores: list[float],
    structure_scores: list[float],
    language_scores: list[float],
    grammar_scores: list[float],
    title: str = "作文历史趋势",
) -> dict[str, Any]:
    """根据历史作文批改结果构建趋势折线图。"""
    return build_line_chart(
        title=title,
        labels=dates,
        datasets=[
            {"label": "内容", "data": content_scores},
            {"label": "结构", "data": structure_scores},
            {"label": "语言", "data": language_scores},
            {"label": "语法", "data": grammar_scores},
        ],
    )
