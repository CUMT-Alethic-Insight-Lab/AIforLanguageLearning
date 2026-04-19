"""轻量文本分析工具（用于 A4/A7/A8 维度计算）。

无需外部 NLP 服务，纯规则实现。
"""

from __future__ import annotations

import math
import re
from typing import Any

# 常用词根词缀（与 KnowledgeGraphService 保持一致，避免循环依赖）
COMMON_PREFIXES = {
    "un", "re", "pre", "dis", "mis", "over", "under", "sub", "super",
    "inter", "anti", "non", "in", "im", "il", "ir", "de", "ex", "co",
}
COMMON_SUFFIXES = {
    "ness", "ment", "tion", "sion", "ity", "er", "or", "ist", "ism",
    "ful", "less", "ous", "ive", "able", "ible", "ly", "ward", "wise",
    "ize", "ise", "ify", "en", "ed", "ing", "al", "ial", "ic",
}

# CEFR 高级词汇启发式特征
_ADVANCED_PATTERNS = re.compile(
    r"\b(\w{10,}|\w+(?:tion|sion|ment|ness|ity|ous|ive|able|ible|ize|ise|ify))\b",
    re.IGNORECASE,
)

# 复合句/从句标记词
_SUBORDINATE_MARKERS = {
    "which", "that", "because", "although", "though", "if", "when", "while",
    "where", "before", "after", "since", "until", "unless", "whether",
    "who", "whom", "whose", "what", "whatever", "whoever", "whomever",
}


def _tokenize_words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-zA-Z]{2,}", text or "")]


def analyze_morph_transfer(
    essay_text: str,
    learned_words: set[str],
) -> dict[str, Any]:
    """分析构词法迁移能力。

    返回:
        {
            "transfer_ratio": float | None,  # 含已学词根的新词比例
            "new_words_with_roots": int,
            "total_unique_words": int,
        }
    """
    words = _tokenize_words(essay_text)
    if not words:
        return {"transfer_ratio": None, "new_words_with_roots": 0, "total_unique_words": 0}

    unique = set(words)
    learned_lower = {w.lower() for w in learned_words}
    if not learned_lower:
        return {"transfer_ratio": None, "new_words_with_roots": 0, "total_unique_words": len(unique)}

    new_words_with_roots = 0
    for word in unique:
        if word in learned_lower:
            continue
        # 检查是否包含已学词根（简单前缀/后缀匹配）
        has_root = False
        for prefix in COMMON_PREFIXES:
            root = word[len(prefix):] if word.startswith(prefix) else ""
            if root and root in learned_lower and len(root) >= 3:
                has_root = True
                break
        if not has_root:
            for suffix in COMMON_SUFFIXES:
                root = word[: -len(suffix)] if word.endswith(suffix) else ""
                if root and root in learned_lower and len(root) >= 3:
                    has_root = True
                    break
        if has_root:
            new_words_with_roots += 1

    total_unique = len(unique)
    return {
        "transfer_ratio": round(new_words_with_roots / total_unique, 4) if total_unique else None,
        "new_words_with_roots": new_words_with_roots,
        "total_unique_words": total_unique,
    }


def estimate_advanced_vocab_substitution(
    essay_text: str,
    essay_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """估计高级词汇替代率。

    优先使用 EssayResult.dimensions.vocabulary 分数；
    若无，则基于文本中高级形态词汇比例做代理。
    """
    dims = (essay_result or {}).get("dimensions") or {}
    vocab_score = dims.get("vocabulary")
    if isinstance(vocab_score, (int, float)) and vocab_score > 0:
        # 假设满分 100，归一化到 0-1
        return {
            "substitution_rate": round(min(1.0, float(vocab_score) / 100.0), 4),
            "source": "essay_dimension_vocabulary",
        }

    words = _tokenize_words(essay_text)
    if not words:
        return {"substitution_rate": None, "source": "text_heuristic"}

    total = len(words)
    advanced = len(_ADVANCED_PATTERNS.findall(" ".join(words)))
    # 高级词比例，假设 15% 为良好水平，归一化
    rate = min(1.0, advanced / max(total * 0.15, 1.0))
    return {
        "substitution_rate": round(rate, 4),
        "source": "text_heuristic",
        "advanced_word_count": advanced,
        "total_word_count": total,
    }


def analyze_sentence_diversity(essay_text: str) -> dict[str, Any]:
    """分析句式多样性指数。

    基于句长标准差和复合句占比。
    返回 0-1 之间的多样性指数。
    """
    text = (essay_text or "").strip()
    if not text:
        return {"diversity_index": None, "sentence_count": 0}

    # 分句（简单按句号/问号/感叹号）
    raw_sentences = re.split(r"[.!?。！？]+", text)
    sentences = [s.strip() for s in raw_sentences if len(s.strip()) >= 5]
    if len(sentences) < 2:
        return {"diversity_index": None, "sentence_count": len(sentences)}

    # 句长（按词数）
    lengths: list[int] = []
    for sent in sentences:
        words = re.findall(r"[a-zA-Z]+", sent)
        lengths.append(len(words))

    if not lengths or all(l == 0 for l in lengths):
        return {"diversity_index": None, "sentence_count": len(sentences)}

    avg_len = sum(lengths) / len(lengths)
    variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
    std_len = math.sqrt(variance)

    # 句长多样性：标准差 / 平均句长，理想值约 0.3-0.6
    length_diversity = min(1.0, std_len / max(avg_len * 0.5, 1.0))

    # 复合句检测
    complex_count = 0
    for sent in sentences:
        words = set(_tokenize_words(sent))
        if words & _SUBORDINATE_MARKERS:
            complex_count += 1

    complex_ratio = complex_count / len(sentences)

    # 综合指数
    diversity_index = length_diversity * 0.5 + complex_ratio * 0.5
    return {
        "diversity_index": round(diversity_index, 4),
        "sentence_count": len(sentences),
        "avg_sentence_length": round(avg_len, 2),
        "sentence_length_std": round(std_len, 2),
        "complex_sentence_ratio": round(complex_ratio, 4),
        "length_diversity": round(length_diversity, 4),
    }
