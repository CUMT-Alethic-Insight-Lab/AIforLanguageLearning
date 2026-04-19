"""LanguageTool 拼写与基础语法检查（可选依赖）。

对应架构文档阶段1中的"可靠语料库API"轻量实现。
若 language-tool-python 未安装或模型下载失败，静默降级为空列表，
不阻塞主批改流程。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_lt_tool: Any | None = None
_lt_available: bool | None = None


def _get_language_tool() -> Any | None:
    """懒加载 LanguageTool 实例。"""
    global _lt_tool, _lt_available
    if _lt_available is False:
        return None
    if _lt_tool is not None:
        return _lt_tool
    try:
        import language_tool_python as ltp

        _lt_tool = ltp.LanguageTool("en-US")
        _lt_available = True
        logger.info("LanguageTool initialized successfully")
        return _lt_tool
    except Exception as exc:
        logger.warning(f"LanguageTool not available: {exc}")
        _lt_available = False
        return None


def check_spelling_and_grammar(text: str, language: str = "en-US") -> list[dict[str, Any]]:
    """使用 LanguageTool 检查拼写和基础语法。

    返回格式:
        [
            {
                "start": int,
                "end": int,
                "message": str,
                "rule": str,
                "suggestions": list[str],
                "category": str,  # 如 "grammar", "spelling", "style"
            }
        ]
    """
    tool = _get_language_tool()
    if tool is None:
        return []

    try:
        matches = tool.check(text)
        results: list[dict[str, Any]] = []
        for m in matches:
            results.append({
                "start": int(m.offset),
                "end": int(m.offset + m.errorLength),
                "message": str(m.message),
                "rule": str(m.ruleId),
                "suggestions": list(m.replacements),
                "category": str(m.category),
            })
        return results
    except Exception as exc:
        logger.warning(f"LanguageTool check failed: {exc}")
        return []


def check_essay(text: str) -> dict[str, Any]:
    """作文拼写/语法检查统一入口。

    返回:
        {
            "issues": list[dict],      # 详细错误列表
            "issue_count": int,
            "spelling_count": int,
            "grammar_count": int,
        }
    """
    issues = check_spelling_and_grammar(text)
    spelling_count = sum(1 for i in issues if "spell" in i.get("category", "").lower())
    grammar_count = sum(1 for i in issues if "grammar" in i.get("category", "").lower())
    return {
        "issues": issues,
        "issue_count": len(issues),
        "spelling_count": spelling_count,
        "grammar_count": grammar_count,
    }
