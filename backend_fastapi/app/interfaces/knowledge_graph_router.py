"""知识图谱 API 路由"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..domain.knowledge_graph import (
    RelationType,
    get_kg_service,
)

router = APIRouter(prefix="/api/v1/knowledge-graph", tags=["knowledge-graph"])


# ========== 请求/响应模型 ==========


class WordRelationsRequest(BaseModel):
    word: str = Field(..., description="查询的词汇")
    relation_type: Literal["synonym", "antonym", "cognate", "similar_form", "all"] = Field(
        default="all", description="关系类型"
    )
    limit: int = Field(default=10, ge=1, le=50, description="返回数量限制")


class WordRelationItem(BaseModel):
    word: str
    relation_type: str
    strength: float
    meaning: str | None = None


class WordRelationsResponse(BaseModel):
    word: str
    relations: list[WordRelationItem]
    total: int


class VocabRecommendRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    count: int = Field(default=10, ge=1, le=20, description="推荐数量")
    user_level: int = Field(default=1, ge=1, le=6, description="用户等级 1-6")
    weak_points: list[str] = Field(default_factory=list, description="薄弱词汇点")
    learned_words: list[str] = Field(default_factory=list, description="已学词汇")


class VocabRecommendItem(BaseModel):
    word: str
    reason: str
    score: float
    relation_type: str | None = None


class VocabRecommendResponse(BaseModel):
    user_id: str
    recommendations: list[VocabRecommendItem]
    total: int


class AddRelationRequest(BaseModel):
    source: str = Field(..., description="源词汇")
    target: str = Field(..., description="目标词汇")
    relation_type: Literal["synonym", "antonym", "cognate", "similar_form"] = Field(
        ..., description="关系类型"
    )
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="关系强度")


class AddRelationResponse(BaseModel):
    success: bool
    message: str


class CognateAnalysisRequest(BaseModel):
    word: str = Field(..., description="要分析的词汇")


class CognateItem(BaseModel):
    word: str
    type: str
    affix: str
    meaning: str


class CognateAnalysisResponse(BaseModel):
    word: str
    cognates: list[CognateItem]
    total: int


class LearningPathRequest(BaseModel):
    start_word: str = Field(..., description="起始词汇")
    target_word: str = Field(..., description="目标词汇")
    max_depth: int = Field(default=5, ge=1, le=10, description="最大搜索深度")


# ========== API 端点 ==========


@router.post("/relations", response_model=WordRelationsResponse)
async def get_word_relations(req: WordRelationsRequest) -> WordRelationsResponse:
    """获取词汇关系"""
    word = (req.word or "").strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")

    kg_service = await get_kg_service()
    relation_type = None if req.relation_type == "all" else req.relation_type
    result = await kg_service.get_word_relations(
        word=word,
        relation_type=relation_type,
        limit=req.limit,
    )

    relations = [
        WordRelationItem(
            word=r.target,
            relation_type=r.relation_type.value,
            strength=r.strength,
            meaning=None,
        )
        for r in result.relations
    ]

    return WordRelationsResponse(word=word, relations=relations, total=result.total)


@router.get("/relations/{word}", response_model=WordRelationsResponse)
async def get_word_relations_get(
    word: str,
    relation_type: Literal["synonym", "antonym", "cognate", "similar_form", "all"] = "all",
    limit: int = 10,
) -> WordRelationsResponse:
    """GET 方式获取词汇关系"""
    return await get_word_relations(
        WordRelationsRequest(word=word, relation_type=relation_type, limit=limit)
    )


@router.post("/recommend", response_model=VocabRecommendResponse)
async def recommend_vocabulary(req: VocabRecommendRequest) -> VocabRecommendResponse:
    """词汇推荐"""
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    kg_service = await get_kg_service()
    result = await kg_service.recommend_vocabulary(
        user_id=req.user_id,
        n=req.count,
        user_level=req.user_level,
        weak_points=req.weak_points,
        learned_words=req.learned_words,
    )

    recommendations = [
        VocabRecommendItem(
            word=r.word,
            reason=r.reason,
            score=r.score,
            relation_type=r.relation_type.value if r.relation_type else None,
        )
        for r in result.recommendations
    ]

    return VocabRecommendResponse(
        user_id=req.user_id,
        recommendations=recommendations,
        total=result.total,
    )


@router.post("/relations/add", response_model=AddRelationResponse)
async def add_word_relation(req: AddRelationRequest) -> AddRelationResponse:
    """添加词汇关系"""
    kg_service = await get_kg_service()
    relation_type = RelationType(req.relation_type)
    success = await kg_service.add_word_relation(
        source=req.source,
        target=req.target,
        relation_type=relation_type,
        strength=req.strength,
    )
    return AddRelationResponse(
        success=success,
        message="Relation added successfully" if success else "Failed to add relation",
    )


@router.post("/cognates/analyze", response_model=CognateAnalysisResponse)
async def analyze_cognates(req: CognateAnalysisRequest) -> CognateAnalysisResponse:
    """分析词汇的同根词"""
    word = (req.word or "").strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")

    kg_service = await get_kg_service()
    cognates = kg_service.analyze_cognates(word)
    items = [
        CognateItem(
            word=c["word"],
            type=c["type"],
            affix=c["affix"],
            meaning=c["meaning"],
        )
        for c in cognates
    ]
    return CognateAnalysisResponse(word=word, cognates=items, total=len(items))


@router.post("/learning-path", response_model=list[dict[str, Any]])
async def get_learning_path(req: LearningPathRequest) -> list[dict[str, Any]]:
    """生成词汇学习路径"""
    start = (req.start_word or "").strip().lower()
    target = (req.target_word or "").strip().lower()
    if not start or not target:
        raise HTTPException(status_code=400, detail="start_word and target_word are required")

    kg_service = await get_kg_service()
    path = await kg_service.generate_learning_path(
        start_word=start,
        target_word=target,
        max_depth=req.max_depth,
    )
    return path
