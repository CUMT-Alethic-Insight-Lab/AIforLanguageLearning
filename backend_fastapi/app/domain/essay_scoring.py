"""作文多维度评分算法"""

from __future__ import annotations

from typing import Any


DIMENSION_WEIGHTS = {
    "content": 0.30,
    "structure": 0.25,
    "language": 0.25,
    "grammar": 0.20,
}


def _map_grade(total_score: float) -> str:
    if total_score >= 9:
        return "A+"
    if total_score >= 8:
        return "A"
    if total_score >= 7:
        return "B+"
    if total_score >= 6:
        return "B"
    if total_score >= 5:
        return "C"
    return "D"


def calculate_essay_score(
    *,
    content_score: float,
    structure_score: float,
    language_score: float,
    grammar_score: float,
) -> dict[str, Any]:
    """计算作文多维度评分。

    输入为 0-10 分的各维度得分，输出包含加权总分、等级映射和结构化维度信息。
    """
    scores = {
        "content": float(content_score),
        "structure": float(structure_score),
        "language": float(language_score),
        "grammar": float(grammar_score),
    }

    dimensions: dict[str, dict[str, float]] = {}
    total = 0.0
    for key, weight in DIMENSION_WEIGHTS.items():
        raw = max(0.0, min(10.0, scores[key]))
        weighted = round(raw * weight, 2)
        dimensions[key] = {
            "score": round(raw, 2),
            "weight": weight,
            "weighted": weighted,
        }
        total += weighted

    total_score = round(total, 2)
    grade = _map_grade(total_score)

    return {
        "dimensions": dimensions,
        "total_score": total_score,
        "grade": grade,
    }


def build_essay_result(
    *,
    content_score: float,
    structure_score: float,
    language_score: float,
    grammar_score: float,
    feedback: str,
    suggestions: list[str],
    corrected_text: str,
    llm_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建完整的 EssayResult.result JSON 结构。"""
    scoring = calculate_essay_score(
        content_score=content_score,
        structure_score=structure_score,
        language_score=language_score,
        grammar_score=grammar_score,
    )

    result: dict[str, Any] = {
        "dimensions": scoring["dimensions"],
        "total_score": scoring["total_score"],
        "grade": scoring["grade"],
        "feedback": feedback,
        "suggestions": suggestions,
        "corrected_text": corrected_text,
    }

    if llm_raw is not None:
        result["llm_raw"] = llm_raw

    return result


def convert_llm_scores_to_dimensions(
    llm_scores: dict[str, int],
) -> dict[str, float]:
    """将 LLM 返回的 0-100 分制分数映射到 0-10 分制的多维度评分。

    映射规则：
    - content = content / 10
    - structure = structure / 10
    - language = (vocabulary + fluency) / 2 / 10
    - grammar = grammar / 10
    """
    content = float(llm_scores.get("content", 60)) / 10.0
    structure = float(llm_scores.get("structure", 60)) / 10.0
    language = (
        float(llm_scores.get("vocabulary", 60)) + float(llm_scores.get("fluency", 60))
    ) / 2.0 / 10.0
    grammar = float(llm_scores.get("grammar", 60)) / 10.0

    return {
        "content": round(content, 2),
        "structure": round(structure, 2),
        "language": round(language, 2),
        "grammar": round(grammar, 2),
    }
