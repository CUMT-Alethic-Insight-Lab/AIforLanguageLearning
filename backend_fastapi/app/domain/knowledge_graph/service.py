"""知识图谱服务层"""

from __future__ import annotations

import heapq
from typing import Any, Dict, List, Optional

from .client import Neo4jClient, get_neo4j_client
from .models import (
    RecommendationResult,
    RelationQueryResult,
    RelationType,
    VocabularyRecommendation,
    WordRelation,
)

# 可选依赖
LIGHTFM_AVAILABLE = False
FAISS_AVAILABLE = False


class KnowledgeGraphService:
    """知识图谱服务 - 核心业务逻辑层"""

    COMMON_PREFIXES = {
        "un": "否定",
        "re": "再次",
        "pre": "之前",
        "dis": "否定",
        "mis": "错误",
        "over": "过度",
        "under": "不足",
        "sub": "下面",
        "super": "超级",
        "inter": "之间",
        "anti": "反对",
        "non": "非",
        "in": "否定/内部",
        "im": "否定",
        "il": "否定",
        "ir": "否定",
    }

    COMMON_SUFFIXES = {
        "ness": "名词(性质)",
        "ment": "名词(行为)",
        "tion": "名词(动作)",
        "sion": "名词(动作)",
        "ity": "名词(状态)",
        "er": "名词(人/物)",
        "or": "名词(人)",
        "ist": "名词(专家)",
        "ism": "名词(主义)",
        "ful": "形容词(充满)",
        "less": "形容词(无)",
        "ous": "形容词(具有)",
        "ive": "形容词(倾向)",
        "able": "形容词(能够)",
        "ible": "形容词(能够)",
        "ly": "副词",
        "ward": "副词(方向)",
        "wise": "副词(方式)",
        "ize": "动词(使成为)",
        "ise": "动词(使成为)",
        "ify": "动词(使成为)",
        "en": "动词(使成为)",
    }

    def __init__(self) -> None:
        self._client: Optional[Neo4jClient] = None

    async def _get_client(self) -> Neo4jClient:
        """获取或创建客户端"""
        if self._client is None:
            self._client = await get_neo4j_client()
            try:
                await self._client.connect()
                await self._client.init_schema()
            except Exception:
                # Neo4j server unavailable; gracefully degrade
                pass
        return self._client

    # ==================== 词汇关系查询 ====================

    async def get_word_relations(
        self,
        word: str,
        relation_type: Optional[str] = None,
        limit: int = 10,
    ) -> RelationQueryResult:
        """获取词汇关系"""
        client = await self._get_client()
        await client.create_word(word)
        relations_data = await client.get_relations(word, relation_type, limit)

        relations: List[WordRelation] = []
        for r in relations_data:
            try:
                rel_type = RelationType(r["relation_type"].lower())
            except ValueError:
                rel_type = RelationType.SIMILAR_FORM
            relations.append(
                WordRelation(
                    source=word,
                    target=r["word"],
                    relation_type=rel_type,
                    strength=r.get("strength", 1.0),
                )
            )

        return RelationQueryResult(word=word, relations=relations, total=len(relations))

    async def get_antonyms(self, word: str) -> List[str]:
        """获取反义词列表"""
        result = await self.get_word_relations(word, relation_type="antonym", limit=5)
        return [r.target for r in result.relations]

    async def get_synonyms(self, word: str) -> List[str]:
        """获取同义词列表"""
        result = await self.get_word_relations(word, relation_type="synonym", limit=5)
        return [r.target for r in result.relations]

    async def get_cognates(self, word: str) -> List[str]:
        """获取同根词"""
        result = await self.get_word_relations(word, relation_type="cognate", limit=5)
        return [r.target for r in result.relations]

    # ==================== 词汇关系构建 ====================

    async def add_word_relation(
        self,
        source: str,
        target: str,
        relation_type: RelationType,
        strength: float = 1.0,
    ) -> bool:
        """添加词汇关系"""
        client = await self._get_client()
        return await client.create_relation(
            source=source,
            target=target,
            relation_type=relation_type.value,
            strength=strength,
        )

    async def add_word(
        self,
        word: str,
        phonetic: Optional[str] = None,
        meaning: Optional[str] = None,
        difficulty: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """添加词汇节点"""
        client = await self._get_client()
        return await client.create_word(
            word=word,
            phonetic=phonetic,
            meaning=meaning,
            difficulty=difficulty,
            tags=tags,
        )

    # ==================== 推荐系统 ====================

    async def recommend_vocabulary(
        self,
        user_id: str,
        n: int = 10,
        user_level: int = 1,
        weak_points: Optional[List[str]] = None,
        learned_words: Optional[List[str]] = None,
    ) -> VocabularyRecommendation:
        """词汇推荐"""
        weak_points = weak_points or []
        learned_words = learned_words or []
        recommendations: List[RecommendationResult] = []

        # 策略1: 基于薄弱点推荐
        if weak_points:
            for weak_word in weak_points[:3]:
                relations = await self.get_word_relations(weak_word, limit=10)
                for rel in relations.relations:
                    target = rel.target
                    if target not in learned_words and target not in [r.word for r in recommendations]:
                        if rel.relation_type == RelationType.SYNONYM:
                            score = 0.90
                            reason = f"'{weak_word}'的同义词，帮助巩固薄弱点"
                        elif rel.relation_type == RelationType.ANTONYM:
                            score = 0.85
                            reason = f"'{weak_word}'的反义词，对比学习"
                        elif rel.relation_type == RelationType.COGNATE:
                            score = 0.80
                            reason = f"'{weak_word}'的同根词，词根词缀学习"
                        else:
                            score = 0.70
                            reason = f"与'{weak_word}'相关的词汇"
                        recommendations.append(
                            RecommendationResult(
                                word=target,
                                reason=reason,
                                score=score * rel.strength,
                                relation_type=rel.relation_type,
                            )
                        )

        # 策略2: 基于已学词汇扩展
        if learned_words and len(recommendations) < n:
            for learned in learned_words[-3:]:
                relations = await self.get_word_relations(learned, limit=5)
                for rel in relations.relations:
                    target = rel.target
                    if target not in learned_words and target not in [r.word for r in recommendations]:
                        recommendations.append(
                            RecommendationResult(
                                word=target,
                                reason=f"与你学过的'{learned}'是{self._translate_relation(rel.relation_type)}",
                                score=0.75 * rel.strength,
                                relation_type=rel.relation_type,
                            )
                        )

        # 兜底: 预定义词库
        if len(recommendations) < n:
            word_pools = {
                1: ["cat", "dog", "book", "pen", "apple", "sun", "run", "fun"],
                2: ["happy", "school", "friend", "family", "water", "music", "dance"],
                3: ["beautiful", "important", "different", "interesting", "necessary", "comfortable"],
                4: ["pronunciation", "vocabulary", "grammar", "sentence", "paragraph", "literature"],
                5: ["metaphor", "allegory", "rhetoric", "syntax", "semantics", "philosophy"],
                6: ["onomatopoeia", "personification", "hyperbole", "alliteration", "euphemism"],
            }
            words = word_pools.get(user_level, word_pools[1])
            for word in words:
                if word not in learned_words and word not in [r.word for r in recommendations]:
                    recommendations.append(
                        RecommendationResult(
                            word=word,
                            reason=f"适合你当前{user_level}级的词汇",
                            score=0.55,
                        )
                    )
                    if len(recommendations) >= n:
                        break

        recommendations.sort(key=lambda x: x.score, reverse=True)
        recommendations = recommendations[:n]

        return VocabularyRecommendation(
            user_id=user_id,
            recommendations=recommendations,
            total=len(recommendations),
        )

    def _translate_relation(self, relation_type: RelationType) -> str:
        translations = {
            RelationType.SYNONYM: "同义词",
            RelationType.ANTONYM: "反义词",
            RelationType.COGNATE: "同根词",
            RelationType.SIMILAR_FORM: "形近词",
            RelationType.BELONGS_TO: "属于",
        }
        return translations.get(relation_type, "相关词")

    # ==================== 同根词识别 ====================

    def analyze_cognates(self, word: str) -> List[Dict[str, Any]]:
        """分析词汇的同根词（基于词根词缀规则）"""
        cognates: List[Dict[str, Any]] = []
        word_lower = word.lower()

        for prefix, meaning in self.COMMON_PREFIXES.items():
            if word_lower.startswith(prefix) and len(word_lower) > len(prefix) + 2:
                root = word_lower[len(prefix) :]
                cognates.append(
                    {
                        "word": root,
                        "type": "prefix",
                        "affix": prefix,
                        "meaning": meaning,
                    }
                )

        for suffix, meaning in self.COMMON_SUFFIXES.items():
            if word_lower.endswith(suffix) and len(word_lower) > len(suffix) + 2:
                root = word_lower[: -len(suffix)]
                cognates.append(
                    {
                        "word": root,
                        "type": "suffix",
                        "affix": suffix,
                        "meaning": meaning,
                    }
                )

        return cognates

    async def auto_build_cognate_relations(self, word: str) -> List[str]:
        """自动构建同根词关系"""
        cognates = self.analyze_cognates(word)
        added: List[str] = []
        for cog in cognates:
            cognate_word = cog["word"]
            await self.add_word_relation(
                source=word,
                target=cognate_word,
                relation_type=RelationType.COGNATE,
                strength=0.9,
            )
            added.append(cognate_word)
        return added

    # ==================== 词汇学习路径生成 ====================

    async def generate_learning_path(
        self,
        start_word: str,
        target_word: str,
        max_depth: int = 5,
    ) -> List[Dict[str, Any]]:
        """生成词汇学习路径（A*算法）"""
        await self._get_client()

        open_set: List[tuple[float, str]] = [(0.0, start_word)]
        came_from: Dict[str, str] = {}
        g_score: Dict[str, float] = {start_word: 0.0}
        f_score: Dict[str, float] = {start_word: self._heuristic(start_word, target_word)}
        visited: set[str] = set()

        while open_set and len(visited) < max_depth * 10:
            _current_f, current = heapq.heappop(open_set)

            if current == target_word:
                path: List[str] = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start_word)
                path.reverse()

                result: List[Dict[str, Any]] = []
                for i in range(len(path) - 1):
                    relations = await self.get_word_relations(path[i], limit=5)
                    for rel in relations.relations:
                        if rel.target == path[i + 1]:
                            result.append(
                                {
                                    "from": path[i],
                                    "to": path[i + 1],
                                    "relation": rel.relation_type.value,
                                    "strength": rel.strength,
                                }
                            )
                            break
                return result

            if current in visited:
                continue
            visited.add(current)

            relations = await self.get_word_relations(current, limit=10)
            for rel in relations.relations:
                neighbor = rel.target
                tentative_g = g_score[current] + (1 - rel.strength)
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._heuristic(neighbor, target_word)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return []

    def _heuristic(self, word1: str, word2: str) -> float:
        """启发函数：使用编辑距离"""
        m, n = len(word1), len(word2)
        if m < n:
            return self._heuristic(word2, word1)
        if n == 0:
            return float(m)

        previous_row = list(range(n + 1))
        for i, c1 in enumerate(word1):
            current_row = [i + 1]
            for j, c2 in enumerate(word2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1.lower() != c2.lower())
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[n] / max(len(word1), len(word2))

    async def batch_import_relations(self, relations: List[WordRelation]) -> Dict[str, int]:
        """批量导入词汇关系"""
        success = 0
        failed = 0
        for rel in relations:
            try:
                result = await self.add_word_relation(
                    source=rel.source,
                    target=rel.target,
                    relation_type=rel.relation_type,
                    strength=rel.strength,
                )
                if result:
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"success": success, "failed": failed}


_kg_service: Optional[KnowledgeGraphService] = None


async def get_kg_service() -> KnowledgeGraphService:
    """获取知识图谱服务实例"""
    global _kg_service
    if _kg_service is None:
        _kg_service = KnowledgeGraphService()
    return _kg_service
