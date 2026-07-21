"""知识图谱数据模型"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """词汇关系类型"""

    SYNONYM = "synonym"  # 同义词
    ANTONYM = "antonym"  # 反义词
    COGNATE = "cognate"  # 同根词
    SIMILAR_FORM = "similar_form"  # 形近词/音近词
    BELONGS_TO = "belongs_to"  # 属于标签


class WordNode(BaseModel):
    """词汇节点"""

    word: str = Field(..., description="词汇")
    phonetic: Optional[str] = Field(None, description="音标")
    meaning: Optional[str] = Field(None, description="释义")
    difficulty: Optional[int] = Field(None, ge=1, le=6, description="难度等级 1-6")
    tags: List[str] = Field(default_factory=list, description="标签列表")


class WordRelation(BaseModel):
    """词汇关系"""

    source: str = Field(..., description="源词汇")
    target: str = Field(..., description="目标词汇")
    relation_type: RelationType = Field(..., description="关系类型")
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="关系强度")


class RelationQueryResult(BaseModel):
    """关系查询结果"""

    word: str
    relations: List[WordRelation]
    total: int


class UserProfile(BaseModel):
    """用户画像"""

    user_id: str
    level: int = Field(default=1, ge=1, le=6, description="用户等级")
    weak_points: List[str] = Field(default_factory=list, description="薄弱词汇点")
    learned_words: List[str] = Field(default_factory=list, description="已学词汇")
    preferred_tags: List[str] = Field(default_factory=list, description="偏好标签")


class RecommendationResult(BaseModel):
    """推荐结果"""

    word: str
    reason: str = Field(..., description="推荐理由")
    score: float = Field(..., ge=0.0, le=1.0, description="推荐分数")
    relation_type: Optional[RelationType] = None


class VocabularyRecommendation(BaseModel):
    """词汇推荐响应"""

    user_id: str
    recommendations: List[RecommendationResult]
    total: int
