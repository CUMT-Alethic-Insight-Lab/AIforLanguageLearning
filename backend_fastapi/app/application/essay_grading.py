"""作文批改应用服务 — 统一的批改流水线（能力复用层）。

将预处理、LLM 调用、评分标准化提取为统一能力，供 HTTP、WebSocket、Celery 三种入口复用，
确保所有路径产出的 EssayResult.result JSON 结构完全一致。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from app.domain.essay_preprocessing import preprocess_essay
from app.domain.essay_scoring import build_essay_result, convert_llm_scores_to_dimensions
from app.domain.essay_spelling import check_essay
from app.domain.essay_structure import analyze_essay_structure
from app.llm import grade_essay


def _run_async_coro(coro: Any) -> Any:
    """在同步上下文中运行异步协程，兼容 Celery eager / 已有事件循环的场景。"""
    if not inspect.iscoroutine(coro):
        return coro
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _normalize_suggestions(suggestions: Any) -> list[str]:
    if not isinstance(suggestions, list):
        return []
    return [str(s) for s in suggestions if isinstance(s, str) and s.strip()]


def _normalize_errors(original_text: str, errors: Any) -> list[dict[str, Any]]:
    """将 LLM 返回的 errors（含 span 文本片段）映射为带字符偏移量的标准化错误列表。

    返回的每个元素包含：
    - start/end: 在 original_text 中的字符偏移量（-1 表示未解析）
    - span: 原始匹配文本
    - message: 错误说明
    - suggestion: 修改建议
    - unresolved: 当 span 在原文中找不到时为 True
    """
    if not isinstance(errors, list):
        return []

    normalized: list[dict[str, Any]] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        span = str(err.get("span", "")).strip()
        if not span:
            continue

        start = original_text.find(span)
        if start != -1:
            normalized.append({
                "start": start,
                "end": start + len(span),
                "span": span,
                "message": str(err.get("message", "")),
                "suggestion": str(err.get("suggestion", "")),
            })
        else:
            # 尝试忽略首尾空白/标点的模糊匹配
            cleaned_span = span.strip(" \t\n\"'.,;:!?")
            if cleaned_span and cleaned_span != span:
                start = original_text.find(cleaned_span)
                if start != -1:
                    normalized.append({
                        "start": start,
                        "end": start + len(cleaned_span),
                        "span": cleaned_span,
                        "message": str(err.get("message", "")),
                        "suggestion": str(err.get("suggestion", "")),
                    })
                    continue

            normalized.append({
                "start": -1,
                "end": -1,
                "span": span,
                "message": str(err.get("message", "")),
                "suggestion": str(err.get("suggestion", "")),
                "unresolved": True,
            })

    return normalized


async def run_grading_pipeline(*, ocr_text: str, language: str = "en") -> dict[str, Any]:
    """作文批改统一流水线（异步）。

    流程：
    1. 文本预处理（编码规范化、分句、语言检测）
    2. 截断超长文本（2000 词上限）
    3. LLM 综合批改
    4. 多维度评分标准化（4 维度 0-10 → 加权总分 → 等级映射）

    返回:
        标准化的 EssayResult.result JSON，包含：
        - dimensions: {content, structure, language, grammar} 各含 score/weight/weighted
        - total_score: 加权总分（0-10）
        - grade: A+/A/B+/B/C/D
        - feedback: 详细评语
        - suggestions: 改进建议列表
        - corrected_text: 润色后文本
        - llm_raw: LLM 原始返回（保留用于调试/追溯）
    """
    # 1. 预处理
    preprocessed = preprocess_essay(ocr_text)
    essay_text = preprocessed["normalized"]
    detected_language = preprocessed["language"]

    # 2. 截断控制 Token
    max_words = 2000
    words = essay_text.split()
    if len(words) > max_words:
        essay_text = " ".join(words[:max_words]) + "\n\n[Text truncated due to length limit]"

    # 3. LLM 批改
    llm_language = detected_language if detected_language in ("zh", "en") else language
    llm_result = await grade_essay(ocr_text=essay_text, language=llm_language)

    # 4. 标准化评分
    llm_scores = llm_result.get("scores", {})
    dim = convert_llm_scores_to_dimensions(llm_scores)

    feedback = llm_result.get("feedback", "")
    suggestions = _normalize_suggestions(llm_result.get("suggestions"))

    corrected_text = llm_result.get("rewritten", essay_text)
    if not isinstance(corrected_text, str):
        corrected_text = essay_text

    result_json = build_essay_result(
        content_score=dim["content"],
        structure_score=dim["structure"],
        vocabulary_score=dim["vocabulary"],
        grammar_score=dim["grammar"],
        fluency_score=dim["fluency"],
        logic_score=dim["logic"],
        feedback=feedback,
        suggestions=suggestions,
        corrected_text=corrected_text,
        llm_raw=llm_result,
    )

    # 将 LLM 返回的 errors 映射为带字符偏移量的标准化格式
    llm_errors = llm_result.get("errors", [])
    result_json["errors_normalized"] = _normalize_errors(essay_text, llm_errors)

    # 轻量结构化解析（连接词、论证标记、段落分析）
    result_json["structure_analysis"] = analyze_essay_structure(essay_text)

    # LanguageTool 拼写/基础语法预检（可选，失败时静默降级）
    result_json["spelling_check"] = check_essay(essay_text)

    return result_json


def run_grading_pipeline_sync(*, ocr_text: str, language: str = "en") -> dict[str, Any]:
    """作文批改统一流水线（同步封装，供 Celery 等同步上下文调用）。"""
    coro = run_grading_pipeline(ocr_text=ocr_text, language=language)
    return _run_async_coro(coro)
