"""知识图谱模块 - 词汇关系网络和推荐系统

核心功能:
1. 词汇关系存储 (同义词、反义词、同根词、形近词)
2. 词汇关系查询
3. 个性化词汇推荐

技术栈:
- Neo4j: 图数据库存储词汇关系
- LightFM: 协同过滤推荐 (可选)
- FAISS: 向量相似度检索 (可选)
"""

from __future__ import annotations

from .client import Neo4jClient, get_neo4j_client
from .models import RecommendationResult, RelationType, WordNode, WordRelation
from .service import KnowledgeGraphService, get_kg_service

__all__ = [
    "get_neo4j_client",
    "Neo4jClient",
    "WordRelation",
    "WordNode",
    "RecommendationResult",
    "RelationType",
    "KnowledgeGraphService",
    "get_kg_service",
]
