"""轻量作文结构化解析（纯 Python，零外部 NLP 依赖）。

对应架构文档中"阶段2: 作文结构化解析"的轻量实现：
- 连接词/过渡词检测
- 论证标记词识别
- 段落结构统计

后续可替换为 spaCy/NLTK 增强版本。
"""

from __future__ import annotations

import re
from typing import Any

# 常见英语连接词与过渡词库（按功能分类）
_CONNECTIVE_CATEGORIES: dict[str, list[str]] = {
    "addition": ["also", "additionally", "furthermore", "moreover", "in addition", "besides"],
    "contrast": ["however", "nevertheless", "nonetheless", "on the other hand", "in contrast", "whereas", "while", "although", "though", "but", "yet"],
    "cause_effect": ["because", "since", "as", "due to", "owing to", "therefore", "thus", "hence", "consequently", "as a result", "so"],
    "example": ["for example", "for instance", "such as", "like", "specifically"],
    "sequence": ["first", "second", "third", "firstly", "secondly", "thirdly", "next", "then", "finally", "lastly", "in conclusion", "to conclude", "in summary"],
    "emphasis": ["indeed", "in fact", "certainly", "obviously", "clearly", "undoubtedly"],
}

# 论证标记词
_ARGUMENT_MARKERS = [
    "argue", "argument", "claim", "assert", "maintain", "contend",
    "evidence", "proof", "support", "demonstrate", "illustrate",
    "reason", "justify", "conclude", "infer", "imply",
]

# 修辞手法标记词
_RHETORICAL_MARKERS = {
    "metaphor": ["like", "as", "metaphor", "symbolize"],
    "parallelism": [],  # 需句式结构分析，当前版本暂不做自动检测
    "rhetorical_question": [],  # 需标点+句式分析
}


def _word_boundary_pattern(word: str) -> re.Pattern:
    """为单词/短语构建带词边界的正则。"""
    escaped = re.escape(word.lower())
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def extract_connectives(text: str) -> dict[str, list[dict[str, Any]]]:
    """检测文本中的连接词与过渡词，按功能分类返回位置和类型。

    返回格式:
        {
            "addition": [{"word": "Furthermore", "start": 120, "end": 131}],
            "contrast": [...],
            ...
        }
    """
    if not text:
        return {cat: [] for cat in _CONNECTIVE_CATEGORIES}

    result: dict[str, list[dict[str, Any]]] = {}
    for category, words in _CONNECTIVE_CATEGORIES.items():
        found: list[dict[str, Any]] = []
        for word in words:
            pat = _word_boundary_pattern(word)
            for m in pat.finditer(text):
                found.append({
                    "word": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                })
        # 去重并按位置排序
        seen: set[tuple[int, int]] = set()
        unique = []
        for item in sorted(found, key=lambda x: x["start"]):
            key = (item["start"], item["end"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        result[category] = unique
    return result


def detect_argument_markers(text: str) -> list[dict[str, Any]]:
    """检测论证相关标记词的位置。"""
    if not text:
        return []

    found: list[dict[str, Any]] = []
    for word in _ARGUMENT_MARKERS:
        pat = _word_boundary_pattern(word)
        for m in pat.finditer(text):
            found.append({
                "word": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })

    seen: set[tuple[int, int]] = set()
    unique = []
    for item in sorted(found, key=lambda x: x["start"]):
        key = (item["start"], item["end"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def analyze_paragraphs(paragraphs: list[str]) -> dict[str, Any]:
    """分析段落结构统计信息。

    输入为段落列表（已由 preprocess_essay 生成）。
    """
    if not paragraphs:
        return {
            "paragraph_count": 0,
            "avg_sentences_per_paragraph": 0.0,
            "avg_words_per_paragraph": 0.0,
            "has_introduction": False,
            "has_conclusion": False,
        }

    total_sentences = 0
    total_words = 0
    for para in paragraphs:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", para) if s.strip()]
        total_sentences += len(sentences)
        total_words += len(para.split())

    para_count = len(paragraphs)
    avg_sentences = round(total_sentences / para_count, 2) if para_count else 0.0
    avg_words = round(total_words / para_count, 2) if para_count else 0.0

    # 轻量启发式：首段是否像引言（包含主题/观点/讨论等词）
    first_para_lower = paragraphs[0].lower()
    intro_markers = ["discuss", "topic", "issue", "question", "opinion", "view", "believe", "think", "argue"]
    has_introduction = any(m in first_para_lower for m in intro_markers)

    # 轻量启发式：末段是否像结论（包含结论/总结/因此/总之等词或 therefore/in conclusion）
    last_para_lower = paragraphs[-1].lower()
    conclusion_markers = ["conclusion", "summary", "therefore", "thus", "in conclusion", "to sum up", "overall", "all in all"]
    has_conclusion = any(m in last_para_lower for m in conclusion_markers)

    return {
        "paragraph_count": para_count,
        "avg_sentences_per_paragraph": avg_sentences,
        "avg_words_per_paragraph": avg_words,
        "has_introduction": has_introduction,
        "has_conclusion": has_conclusion,
    }


def analyze_essay_structure(text: str) -> dict[str, Any]:
    """作文结构化解析统一入口。

    返回:
        {
            "connectives": {category: [...]},
            "argument_markers": [...],
            "paragraph_analysis": {...},
        }
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return {
        "connectives": extract_connectives(text),
        "argument_markers": detect_argument_markers(text),
        "paragraph_analysis": analyze_paragraphs(paragraphs),
    }
