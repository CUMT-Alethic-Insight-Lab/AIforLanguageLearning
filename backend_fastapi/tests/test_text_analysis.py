"""文本分析工具测试（A4/A7/A8）。"""

from __future__ import annotations

from app.application.analytics._text_analysis import (
    analyze_morph_transfer,
    analyze_sentence_diversity,
    estimate_advanced_vocab_substitution,
)


def test_analyze_morph_transfer_basic() -> None:
    essay = "I am unhappy because the building is uncomfortable."
    learned = {"happy", "build", "comfort"}
    result = analyze_morph_transfer(essay, learned)
    assert result["transfer_ratio"] is not None
    assert result["new_words_with_roots"] >= 1


def test_analyze_morph_transfer_no_learned() -> None:
    result = analyze_morph_transfer("hello world", set())
    assert result["transfer_ratio"] is None


def test_estimate_advanced_vocab_with_dimension() -> None:
    essay_result = {"dimensions": {"vocabulary": 75}}
    result = estimate_advanced_vocab_substitution("some text", essay_result)
    assert result["substitution_rate"] == 0.75
    assert result["source"] == "essay_dimension_vocabulary"


def test_estimate_advanced_vocab_heuristic() -> None:
    result = estimate_advanced_vocab_substitution(
        "The government announced a new transportation infrastructure development.",
        None,
    )
    assert result["substitution_rate"] is not None
    assert result["source"] == "text_heuristic"


def test_analyze_sentence_diversity() -> None:
    text = "This is a simple sentence. It is very short. Because I like writing, I added another clause."
    result = analyze_sentence_diversity(text)
    assert result["diversity_index"] is not None
    assert result["sentence_count"] >= 3
    assert result["complex_sentence_ratio"] > 0


def test_analyze_sentence_diversity_empty() -> None:
    result = analyze_sentence_diversity("")
    assert result["diversity_index"] is None
