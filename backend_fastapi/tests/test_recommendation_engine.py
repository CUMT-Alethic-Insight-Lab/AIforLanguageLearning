"""推荐引擎增强层测试。"""

from __future__ import annotations

import pytest

from app.domain.knowledge_graph.recommendation_engine import RecommendationEngine


def test_behavior_based_recommendations_basic() -> None:
    engine = RecommendationEngine()
    history = [
        {"type": "dialogue", "content": "airport check-in travel", "meta_data": {"topics": ["travel"]}},
        {"type": "vocabulary", "content": "boarding pass travel", "meta_data": {"topics": ["travel"]}},
    ]
    pool = ["travel_guide", "restaurant", "travel_kit", "visa", "customs"]
    recs = engine.behavior_based_recommendations(history, pool, n=3)
    assert len(recs) > 0
    assert all(r.word in pool for r in recs)


def test_behavior_based_empty() -> None:
    engine = RecommendationEngine()
    recs = engine.behavior_based_recommendations([], ["a", "b"], n=2)
    assert recs == []


def test_lightfm_not_available() -> None:
    engine = RecommendationEngine()
    assert engine.fit_lightfm(None) is False
    assert engine.lightfm_recommend(1, {}, {}, n=5) == []


def test_faiss_not_available() -> None:
    engine = RecommendationEngine()
    assert engine.build_faiss_index({}, dim=64) is False
    assert engine.faiss_search([0.1] * 64, {}, n=5) == []


def test_merge_recommendations() -> None:
    from app.domain.knowledge_graph.models import RecommendationResult
    engine = RecommendationEngine()
    recs1 = [RecommendationResult(word="apple", reason="rule", score=0.9)]
    recs2 = [RecommendationResult(word="apple", reason="stat", score=0.8)]
    merged = engine.merge_recommendations(recs1, recs2, n=5)
    assert merged.total == 1
    assert merged.recommendations[0].word == "apple"
    # 加权合并: 0.9*0.4 + 0.8*0.3 = 0.36 + 0.24 = 0.6
    assert merged.recommendations[0].score == pytest.approx(0.6, rel=1e-9)
