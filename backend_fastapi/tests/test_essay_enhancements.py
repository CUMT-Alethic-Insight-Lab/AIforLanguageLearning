"""作文模块增强功能单元测试（错误标注标准化、结构化解析、图表构建、缓存）。"""

from __future__ import annotations

import pytest

from app.application.chart_builder import (
    build_bar_chart,
    build_essay_dimension_radar,
    build_essay_history_line,
    build_line_chart,
    build_pie_chart,
    build_radar_chart,
)
from app.application.essay_grading import _normalize_errors, _normalize_suggestions
from app.domain.essay_structure import (
    analyze_essay_structure,
    analyze_paragraphs,
    detect_argument_markers,
    extract_connectives,
)
from app.infrastructure.persistence.cache.sync_redis_cache import essay_cache_key


class TestNormalizeErrors:
    def test_exact_match(self):
        text = "I has a pen."
        errors = [{"span": "has a", "message": "语法错误", "suggestion": "have a"}]
        result = _normalize_errors(text, errors)
        assert len(result) == 1
        assert result[0]["start"] == 2
        assert result[0]["end"] == 7
        assert result[0]["span"] == "has a"
        assert "unresolved" not in result[0]

    def test_unresolved(self):
        text = "I have a pen."
        errors = [{"span": "does not exist", "message": "错误", "suggestion": ""}]
        result = _normalize_errors(text, errors)
        assert len(result) == 1
        assert result[0]["start"] == -1
        assert result[0]["end"] == -1
        assert result[0].get("unresolved") is True

    def test_fuzzy_match_strip_punctuation(self):
        # 精确匹配失败（因为 text 中不含引号包围的 "world"）
        # 但 strip 后能找到 world
        text = 'Hello world!'
        errors = [{"span": '"world"', "message": "标点", "suggestion": "world"}]
        result = _normalize_errors(text, errors)
        assert len(result) == 1
        assert result[0]["start"] == 6
        assert result[0]["end"] == 11
        assert result[0]["span"] == "world"

    def test_non_dict_errors_ignored(self):
        assert _normalize_errors("text", [None, "bad", 123]) == []


class TestNormalizeSuggestions:
    def test_basic(self):
        assert _normalize_suggestions(["a", "", "b", None]) == ["a", "b"]

    def test_non_list(self):
        assert _normalize_suggestions("not a list") == []


class TestEssayStructure:
    def test_extract_connectives(self):
        text = "First, I think it is good. However, there is a problem. Therefore, we should fix it."
        conns = extract_connectives(text)
        assert any(c["word"].lower() == "first" for c in conns["sequence"])
        assert any(c["word"].lower() == "however" for c in conns["contrast"])
        assert any(c["word"].lower() == "therefore" for c in conns["cause_effect"])

    def test_detect_argument_markers(self):
        text = "I argue that this is true. The evidence supports my claim."
        markers = detect_argument_markers(text)
        words = [m["word"].lower() for m in markers]
        assert "argue" in words
        assert "evidence" in words
        assert "claim" in words

    def test_analyze_paragraphs(self):
        paras = ["In my opinion, this is important.", "First, we need to discuss it.", "In conclusion, it is clear."]
        analysis = analyze_paragraphs(paras)
        assert analysis["paragraph_count"] == 3
        assert analysis["has_introduction"] is True
        assert analysis["has_conclusion"] is True
        assert analysis["avg_sentences_per_paragraph"] > 0

    def test_analyze_essay_structure(self):
        text = "I believe education is key.\n\nHowever, many people disagree.\n\nIn conclusion, we must act."
        result = analyze_essay_structure(text)
        assert "connectives" in result
        assert "argument_markers" in result
        assert "paragraph_analysis" in result
        assert result["paragraph_analysis"]["paragraph_count"] == 3


class TestChartBuilder:
    def test_build_pie_chart(self):
        chart = build_pie_chart("分布", ["A", "B"], [30, 70])
        assert chart["type"] == "pie"
        assert chart["title"] == "分布"
        assert chart["labels"] == ["A", "B"]
        assert chart["datasets"][0]["data"] == [30, 70]

    def test_build_bar_chart(self):
        chart = build_bar_chart(
            "对比",
            ["X", "Y"],
            [{"label": "A", "data": [10, 20]}, {"label": "B", "data": [15, 25]}],
        )
        assert chart["type"] == "bar"
        assert len(chart["datasets"]) == 2

    def test_build_radar_chart(self):
        chart = build_radar_chart("雷达", ["a", "b"], [{"label": "me", "data": [80, 90]}])
        assert chart["type"] == "radar"

    def test_build_line_chart(self):
        chart = build_line_chart("趋势", ["d1", "d2"], [{"label": "score", "data": [70, 75]}])
        assert chart["type"] == "line"

    def test_build_essay_dimension_radar(self):
        dims = {
            "content": {"score": 8.0, "weight": 0.30, "weighted": 2.40},
            "structure": {"score": 7.0, "weight": 0.25, "weighted": 1.75},
            "language": {"score": 8.0, "weight": 0.25, "weighted": 2.00},
            "grammar": {"score": 6.0, "weight": 0.20, "weighted": 1.20},
        }
        chart = build_essay_dimension_radar(dims)
        assert chart["type"] == "radar"
        assert chart["labels"] == ["内容", "结构", "语言", "语法"]
        assert chart["datasets"][0]["data"] == [80.0, 70.0, 80.0, 60.0]

    def test_build_essay_history_line(self):
        chart = build_essay_history_line(
            ["2026-04-01", "2026-04-02"],
            [7.0, 7.5],
            [6.5, 7.0],
            [8.0, 8.0],
            [6.0, 6.5],
        )
        assert chart["type"] == "line"
        assert len(chart["datasets"]) == 4


class TestEssayCacheKey:
    def test_deterministic(self):
        assert essay_cache_key("hello world") == essay_cache_key("hello world")

    def test_case_insensitive(self):
        assert essay_cache_key("Hello World") == essay_cache_key("hello world")

    def test_different_texts(self):
        assert essay_cache_key("a") != essay_cache_key("b")
