"""推荐引擎增强层。

当前定位：在现有 KnowledgeGraphService（规则+Neo4j）基础上，增加
1. 用户行为统计推荐（已落地）
2. LightFM / FAISS 基础设施占位（规划中，接口先行）

设计原则：
- 不破坏现有 recommend_vocabulary() 调用链
- 新增增强层可由调用方按需启用
- LightFM/FAISS 为可选依赖，缺失时自动降级到规则推荐
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import RecommendationResult, VocabularyRecommendation

logger = logging.getLogger(__name__)

# 可选依赖占位
try:
    import numpy as np  # noqa: F401
    NUMPY_AVAILABLE = True
except Exception:
    NUMPY_AVAILABLE = False

try:
    from lightfm import LightFM  # noqa: F401
    LIGHTFM_AVAILABLE = True
except Exception:
    LIGHTFM_AVAILABLE = False

try:
    import faiss  # noqa: F401
    FAISS_AVAILABLE = True
except Exception:
    FAISS_AVAILABLE = False


class RecommendationEngine:
    """增强型推荐引擎。

    支持三级推荐策略：
    1. 规则层：Neo4j 知识图谱 + 用户画像（已有）
    2. 统计层：用户行为序列统计（本文件新增）
    3. 模型层：LightFM 协同过滤 + FAISS 向量检索（占位接口）
    """

    def __init__(self) -> None:
        self._lightfm_model: Any = None
        self._faiss_index: Any = None
        self._item_vectors: Optional[Dict[str, List[float]]] = None

    # ── 统计层：用户行为序列推荐 ──

    def behavior_based_recommendations(
        self,
        user_history: List[Dict[str, Any]],
        candidate_pool: List[str],
        n: int = 10,
    ) -> List[RecommendationResult]:
        """基于用户行为历史的统计推荐。

        Args:
            user_history: 用户学习记录列表，每项含 type, content, meta_data
            candidate_pool: 候选词汇列表
            n: 返回数量

        Returns:
            按相关性排序的推荐结果
        """
        if not user_history or not candidate_pool:
            return []

        # 统计用户高频主题标签
        topic_freq: Dict[str, int] = {}
        for record in user_history:
            meta = record.get("meta_data") or {}
            for topic in meta.get("topics") or []:
                topic_freq[topic] = topic_freq.get(topic, 0) + 1
            # 从 content 中提取场景关键词
            content = str(record.get("content") or "").lower()
            for topic in ("travel", "business", "daily", "academic", "social", "food"):
                if topic in content:
                    topic_freq[topic] = topic_freq.get(topic, 0) + 1

        if not topic_freq:
            return []

        # 对候选池按主题匹配度排序（简单 Jaccard 代理）
        scored: List[tuple[float, str]] = []
        for word in candidate_pool:
            # 启发式：假设 candidate_pool 中的词带有隐式主题
            # 实际生产环境应接入词汇标签库
            word_lower = word.lower()
            matched = 0
            for topic, freq in topic_freq.items():
                if topic in word_lower or word_lower in topic:
                    matched += freq
            if matched > 0:
                scored.append((matched, word))

        scored.sort(key=lambda x: x[0], reverse=True)
        recommendations: List[RecommendationResult] = []
        for score, word in scored[:n]:
            recommendations.append(
                RecommendationResult(
                    word=word,
                    reason=f"基于你近期对 {max(topic_freq, key=topic_freq.get)} 主题的兴趣推荐",
                    score=min(1.0, 0.5 + score * 0.05),
                )
            )
        return recommendations

    # ── 模型层：LightFM 占位接口 ──

    def fit_lightfm(
        self,
        interactions: Any,
        user_features: Optional[Any] = None,
        item_features: Optional[Any] = None,
        epochs: int = 30,
    ) -> bool:
        """训练 LightFM 模型（占位接口）。

        当 lightfm 未安装时，返回 False 并记录警告。
        """
        if not LIGHTFM_AVAILABLE:
            logger.warning("LightFM not installed; skipping fit_lightfm().")
            return False

        try:
            self._lightfm_model = LightFM(loss="warp")
            self._lightfm_model.fit(
                interactions,
                user_features=user_features,
                item_features=item_features,
                epochs=epochs,
                num_threads=4,
            )
            logger.info("LightFM model fitted successfully.")
            return True
        except Exception as exc:
            logger.error("LightFM fit failed: %s", exc)
            return False

    def lightfm_recommend(
        self,
        user_id: int,
        user_ids_map: Dict[int, int],
        item_ids_map: Dict[str, int],
        n: int = 10,
    ) -> List[RecommendationResult]:
        """使用 LightFM 生成推荐（占位接口）。

        模型未训练或 lightfm 不可用时返回空列表。
        """
        if not LIGHTFM_AVAILABLE or self._lightfm_model is None:
            return []

        try:
            import numpy as np
            user_idx = user_ids_map.get(user_id)
            if user_idx is None:
                return []

            n_items = len(item_ids_map)
            scores = self._lightfm_model.predict(
                user_ids=np.array([user_idx]),
                item_ids=np.arange(n_items),
            )
            top_indices = np.argsort(-scores)[:n]
            id_to_item = {v: k for k, v in item_ids_map.items()}
            recommendations: List[RecommendationResult] = []
            for idx in top_indices:
                item = id_to_item.get(int(idx))
                if item:
                    recommendations.append(
                        RecommendationResult(
                            word=item,
                            reason="LightFM 协同过滤推荐",
                            score=min(1.0, max(0.0, float(scores[idx]))),
                        )
                    )
            return recommendations
        except Exception as exc:
            logger.error("LightFM recommend failed: %s", exc)
            return []

    # ── 模型层：FAISS 向量检索占位接口 ──

    def build_faiss_index(
        self,
        item_vectors: Dict[str, List[float]],
        dim: int = 64,
    ) -> bool:
        """构建 FAISS 向量索引（占位接口）。

        当 faiss 未安装时，返回 False 并记录警告。
        """
        if not FAISS_AVAILABLE:
            logger.warning("FAISS not installed; skipping build_faiss_index().")
            return False

        try:
            import faiss
            import numpy as np

            self._item_vectors = item_vectors
            vectors = np.array(list(item_vectors.values()), dtype="float32")
            index = faiss.IndexFlatIP(dim)  # 内积相似度
            if vectors.shape[0] > 0:
                faiss.normalize_L2(vectors)
                index.add(vectors)
            self._faiss_index = index
            logger.info("FAISS index built with %s items.", vectors.shape[0])
            return True
        except Exception as exc:
            logger.error("FAISS index build failed: %s", exc)
            return False

    def faiss_search(
        self,
        query_vector: List[float],
        item_ids_map: Dict[str, int],
        n: int = 10,
    ) -> List[RecommendationResult]:
        """使用 FAISS 进行向量近邻检索（占位接口）。

        索引未构建或 faiss 不可用时返回空列表。
        """
        if not FAISS_AVAILABLE or self._faiss_index is None:
            return []

        try:
            import numpy as np
            q = np.array([query_vector], dtype="float32")
            faiss.normalize_L2(q)
            distances, indices = self._faiss_index.search(q, n)
            id_to_item = {v: k for k, v in item_ids_map.items()}
            recommendations: List[RecommendationResult] = []
            for dist, idx in zip(distances[0], indices[0]):
                item = id_to_item.get(int(idx))
                if item:
                    recommendations.append(
                        RecommendationResult(
                            word=item,
                            reason="FAISS 向量近邻推荐",
                            score=min(1.0, float(dist)),
                        )
                    )
            return recommendations
        except Exception as exc:
            logger.error("FAISS search failed: %s", exc)
            return []

    # ── 融合层：多路召回合并 ──

    def merge_recommendations(
        self,
        *recommendation_lists: List[RecommendationResult],
        n: int = 10,
    ) -> VocabularyRecommendation:
        """合并多路推荐结果，去重并按分数排序。

        当前使用简单加权：规则层 0.4 + 统计层 0.3 + 模型层 0.3
        """
        merged: Dict[str, RecommendationResult] = {}
        weights = [0.4, 0.3, 0.3]

        for idx, recs in enumerate(recommendation_lists):
            weight = weights[idx] if idx < len(weights) else 0.2
            for rec in recs:
                existing = merged.get(rec.word)
                if existing is None:
                    merged[rec.word] = RecommendationResult(
                        word=rec.word,
                        reason=rec.reason,
                        score=rec.score * weight,
                        relation_type=rec.relation_type,
                    )
                else:
                    merged[rec.word] = RecommendationResult(
                        word=rec.word,
                        reason=f"{existing.reason}; {rec.reason}",
                        score=min(1.0, existing.score + rec.score * weight),
                        relation_type=existing.relation_type,
                    )

        sorted_recs = sorted(merged.values(), key=lambda x: x.score, reverse=True)[:n]
        return VocabularyRecommendation(
            user_id="merged",
            recommendations=sorted_recs,
            total=len(sorted_recs),
        )


# 全局单例
_engine_instance: Optional[RecommendationEngine] = None


def get_recommendation_engine() -> RecommendationEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RecommendationEngine()
    return _engine_instance
