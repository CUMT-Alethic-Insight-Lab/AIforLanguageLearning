"""作文评分算法与预处理单元测试"""

from __future__ import annotations

import pytest

from app.domain.essay_preprocessing import (
    detect_language,
    normalize_text,
    preprocess_essay,
    segment_sentences,
)
from app.domain.essay_scoring import (
    build_essay_result,
    calculate_essay_score,
    convert_llm_scores_to_dimensions,
)


class TestEssayPreprocessing:
    def test_normalize_text_whitespace(self):
        raw = "Hello   world\t\t!\n\n\nNext line."
        got = normalize_text(raw)
        assert "  " not in got
        assert got == "Hello world !\nNext line."

    def test_normalize_text_unicode(self):
        # 全角字符应被 NFKC 规范化
        raw = "Ｈｅｌｌｏ　ｗｏｒｌｄ"
        got = normalize_text(raw)
        assert "Hello" in got

    def test_segment_sentences_basic(self):
        text = "Hello world. How are you? I am fine! Great."
        sents = segment_sentences(text)
        assert len(sents) == 4
        assert sents[0] == "Hello world."
        assert sents[1] == "How are you?"
        assert sents[2] == "I am fine!"
        assert sents[3] == "Great."

    def test_detect_language_english(self):
        assert detect_language("Hello world, this is a test.") == "en"

    def test_detect_language_chinese(self):
        assert detect_language("你好世界，这是一个测试。") == "zh"

    def test_detect_language_mixed(self):
        # 中文字符比例高应判定为 zh
        assert detect_language("你好 world，测试 test.") == "zh"

    def test_preprocess_essay_structure(self):
        text = "First paragraph.\n\nSecond paragraph! Is it ok?"
        result = preprocess_essay(text)
        assert result["language"] in ("en", "zh")
        assert len(result["sentences"]) >= 2
        assert len(result["paragraphs"]) == 2
        assert "First paragraph." in result["normalized"]


class TestEssayScoring:
    def test_calculate_essay_score_basic(self):
        result = calculate_essay_score(
            content_score=8.0,
            structure_score=7.0,
            vocabulary_score=7.5,
            grammar_score=6.0,
            fluency_score=8.5,
            logic_score=7.0,
        )
        assert result["total_score"] == pytest.approx(7.40, 0.01)
        assert result["grade"] == "B+"
        dims = result["dimensions"]
        assert dims["content"]["weight"] == 0.25
        assert dims["vocabulary"]["weight"] == 0.15
        assert dims["grammar"]["score"] == 6.0

    def test_calculate_essay_score_clamping(self):
        # 测试越界输入被截断到 0-10
        result = calculate_essay_score(
            content_score=15.0,
            structure_score=-2.0,
            vocabulary_score=5.0,
            grammar_score=5.0,
            fluency_score=5.0,
            logic_score=5.0,
        )
        assert result["dimensions"]["content"]["score"] == 10.0
        assert result["dimensions"]["structure"]["score"] == 0.0

    def test_map_grade_boundaries(self):
        # 边界值测试（总分 = sum(score * weight)）
        def score_all(value: int):
            return calculate_essay_score(
                content_score=value,
                structure_score=value,
                vocabulary_score=value,
                grammar_score=value,
                fluency_score=value,
                logic_score=value,
            )

        assert score_all(10)["grade"] == "A+"
        assert score_all(8)["grade"] == "A"
        assert score_all(7)["grade"] == "B+"
        assert score_all(6)["grade"] == "B"
        assert score_all(5)["grade"] == "C"
        assert score_all(4)["grade"] == "D"

    def test_convert_llm_scores_to_dimensions(self):
        llm_scores = {
            "content": 80,
            "structure": 70,
            "vocabulary": 75,
            "fluency": 85,
            "grammar": 60,
            "logic": 65,
        }
        dim = convert_llm_scores_to_dimensions(llm_scores)
        assert dim["content"] == 8.0
        assert dim["structure"] == 7.0
        assert dim["vocabulary"] == 7.5
        assert dim["fluency"] == 8.5
        assert dim["grammar"] == 6.0
        assert dim["logic"] == 6.5

    def test_build_essay_result_structure(self):
        result = build_essay_result(
            content_score=8.0,
            structure_score=7.0,
            vocabulary_score=7.5,
            grammar_score=6.0,
            fluency_score=8.5,
            logic_score=7.0,
            feedback="整体良好",
            suggestions=["注意语法"],
            corrected_text="I have a pen.",
            llm_raw={"score": 75},
        )
        assert "dimensions" in result
        assert "total_score" in result
        assert "grade" in result
        assert result["feedback"] == "整体良好"
        assert result["suggestions"] == ["注意语法"]
        assert result["corrected_text"] == "I have a pen."
        assert result["llm_raw"] == {"score": 75}
