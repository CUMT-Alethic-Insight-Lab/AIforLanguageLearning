"""作文文本预处理

对应架构文档阶段1：文本预处理（编码规范化、分段分句、语言检测）。
当前为轻量规则实现，后续可接入 NLP 模型增强。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_text(text: str) -> str:
    """编码规范化：去除多余空白、统一换行符、NFKC 标准化。"""
    if not isinstance(text, str):
        text = str(text or "")
    # Unicode NFKC 规范化（兼容字符统一、全角半角转换等）
    text = unicodedata.normalize("NFKC", text)
    # 统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去除控制字符（保留换行、制表符）
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    # 合并连续空白为单个空格（保留换行用于分段）
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    # 去除首尾空白
    text = text.strip()
    return text


def segment_sentences(text: str) -> list[str]:
    """简单分句：基于句末标点（.!?。！？）切分。"""
    if not text:
        return []
    # 保留英文和中文句末标点
    pattern = r"(?<=[.!?。！？])\s+"
    sentences = [s.strip() for s in re.split(pattern, text) if s.strip()]
    return sentences


def detect_language(text: str) -> str:
    """轻量语言检测：基于中文字符比例做启发式判断。

    返回 "zh" | "en" | "unknown"
    """
    if not text:
        return "unknown"
    # 统计中文字符（CJK Unified Ideographs 及扩展）
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    total_alpha = sum(1 for ch in text if ch.isalpha())
    if cjk_chars > 0 and (total_alpha == 0 or cjk_chars / max(total_alpha, 1) > 0.3):
        return "zh"
    if total_alpha > 0:
        return "en"
    return "unknown"


def preprocess_essay(text: str) -> dict[str, Any]:
    """作文文本预处理统一入口。

    返回:
        {
            "normalized": str,      # 规范化后的文本
            "sentences": list[str], # 分句结果
            "language": str,        # 检测到的语言
            "paragraphs": list[str],# 按换行分段结果
        }
    """
    normalized = normalize_text(text)
    sentences = segment_sentences(normalized)
    language = detect_language(normalized)
    paragraphs = [p.strip() for p in normalized.split("\n") if p.strip()]
    return {
        "normalized": normalized,
        "sentences": sentences,
        "language": language,
        "paragraphs": paragraphs,
    }
