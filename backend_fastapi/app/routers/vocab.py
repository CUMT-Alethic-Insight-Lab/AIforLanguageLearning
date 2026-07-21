from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..application.db_learning import create_record
from ..application.db_vocabulary import add_word, get_due_words, review_word
from ..db import get_session
from ..domain.knowledge_graph import get_kg_service
from ..domain.models import User, VocabularyItem
from ..infrastructure.dependencies import get_current_user, get_optional_user
from ..infrastructure.messaging.tasks import generate_daily_vocab_task
from ..infrastructure.persistence.search.es_client import search_vocabulary
from ..llm import generate_definition, generate_vocab_fields
from ..models import PublicVocabEntry, UserVocabQuery
from ..ocr import ocr_image_base64

router = APIRouter(prefix="/v1/vocab", tags=["vocab"])


class VocabLookupRequest(BaseModel):
    term: str
    source: Literal["manual", "ocr"] = "manual"
    session_id: str = ""
    conversation_id: str = ""
    user_id: int | None = None
    fuzzy: bool = True
    include_relations: bool = True
    save_to_vocab: bool = True


class VocabDefinition(BaseModel):
    meaning: str = ""
    example: str = ""
    example_translation: str = ""


class LookupRecommendation(BaseModel):
    word: str
    reason: str = ""
    score: float | None = None
    relation_type: str | None = None


class VocabLookupResponse(BaseModel):
    term: str
    definition: str
    from_public_vocab: bool
    meaning: str = ""
    example: str = ""
    example_translation: str = ""
    definitions: list[VocabDefinition] = Field(default_factory=list)
    recommendations: list[LookupRecommendation] = Field(default_factory=list)
    cefr_level: str = ""
    difficulty_level: int | None = None
    exam_tags: list[str] = Field(default_factory=list)
    school_stage: str = ""
    cached: bool = False


class VocabLookupOcrRequest(BaseModel):
    image: str
    language: str = "english"
    session_id: str = ""
    conversation_id: str = ""
    user_id: int | None = None
    include_relations: bool = True
    save_to_vocab: bool = True


class VocabLookupOcrResponse(BaseModel):
    term: str
    ocr_text: str
    meaning: str
    example: str
    example_translation: str
    definitions: list[VocabDefinition] = Field(default_factory=list)
    recommendations: list[LookupRecommendation] = Field(default_factory=list)
    cefr_level: str = ""
    difficulty_level: int | None = None
    exam_tags: list[str] = Field(default_factory=list)
    school_stage: str = ""


class VocabGenerateRequest(BaseModel):
    theme: str
    difficulty: str = "intermediate"
    count: int = Field(default=20, ge=1, le=50)


class VocabGenerateResponse(BaseModel):
    success: bool
    data: dict[str, Any]


class VocabReviewWord(BaseModel):
    id: int
    word: str
    definition: str
    pronunciation: str
    example: str
    mastery_level: int
    next_review_at: str


class VocabReviewListResponse(BaseModel):
    success: bool
    data: dict[str, Any]


class VocabReviewSubmitRequest(BaseModel):
    vocab_id: int
    quality: int | None = Field(default=None, ge=0, le=5)
    correct: bool | None = None


class VocabReviewSubmitResponse(BaseModel):
    success: bool
    data: dict[str, Any]


def _resolve_user_id(current_user: User | None, requested_user_id: int | None) -> int | None:
    """Return the user_id from the authenticated user, or None if anonymous.

    P0 fix: the ``requested_user_id`` parameter is retained for signature
    compatibility but is *never* used as a fallback — unauthenticated clients
    cannot inject an arbitrary user_id via the request body.
    """
    if current_user is not None and current_user.id is not None:
        return int(current_user.id)
    return None


def _parse_definition_block(term: str, definition: str, structured_defs: list[dict[str, Any]] | None) -> tuple[str, str, str, list[VocabDefinition]]:
    normalized: list[VocabDefinition] = []
    for item in structured_defs or []:
        if not isinstance(item, dict):
            continue
        meaning = str(item.get("meaning") or "").strip()
        example = str(item.get("example") or "").strip()
        example_translation = str(item.get("example_translation") or "").strip()
        if meaning or example or example_translation:
            normalized.append(
                VocabDefinition(
                    meaning=meaning or "暂无",
                    example=example,
                    example_translation=example_translation,
                )
            )

    meaning = normalized[0].meaning if normalized else ""
    example = normalized[0].example if normalized else ""
    example_translation = normalized[0].example_translation if normalized else ""

    if normalized:
        return meaning, example, example_translation, normalized

    text = str(definition or "").strip()
    parsed_meaning = ""
    parsed_example = ""
    parsed_translation = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if not parsed_meaning and line.startswith("释义："):
            parsed_meaning = line.removeprefix("释义：").strip()
            continue
        if not parsed_example and line.startswith("例句："):
            parsed_example = line.removeprefix("例句：").strip()
            continue
        if not parsed_translation and (line.startswith("例句翻译：") or line.startswith("翻译：")):
            parsed_translation = line.split("：", 1)[-1].strip()
            continue

    if not parsed_meaning and lines:
        parsed_meaning = lines[0]
    if not parsed_example and len(lines) > 1:
        parsed_example = lines[1]

    return (
        parsed_meaning or "暂无",
        parsed_example,
        parsed_translation,
        [VocabDefinition(meaning=parsed_meaning or "暂无", example=parsed_example, example_translation=parsed_translation)],
    )


def _estimate_vocab_metadata(term: str, definitions: list[VocabDefinition]) -> tuple[str, int, list[str], str]:
    cleaned = (term or "").strip()
    syllable_like = max(1, sum(1 for ch in cleaned.lower() if ch in "aeiou"))
    base = 1
    if " " in cleaned:
        base += 1
    if len(cleaned) >= 7:
        base += 1
    if len(cleaned) >= 10:
        base += 1
    if len(definitions) >= 2:
        base += 1
    if syllable_like >= 4:
        base += 1
    difficulty = max(1, min(6, base))
    cefr = {1: "A1", 2: "A2", 3: "B1", 4: "B2", 5: "C1", 6: "C2"}[difficulty]
    school_stage = {
        1: "小学",
        2: "初中",
        3: "高中",
        4: "大学",
        5: "大学及以上",
        6: "学术/专业",
    }[difficulty]
    exam_tags: list[str] = []
    if difficulty <= 2:
        exam_tags.append("基础词汇")
    elif difficulty <= 4:
        exam_tags.append("能力进阶")
    else:
        exam_tags.append("高阶表达")
    if " " in cleaned:
        exam_tags.append("短语")
    return cefr, difficulty, exam_tags, school_stage


async def _build_recommendations(
    *,
    term: str,
    user_id: int | None,
    include_relations: bool,
    session: Session,
) -> list[LookupRecommendation]:
    if not include_relations:
        return []

    out: list[LookupRecommendation] = []
    seen: set[str] = set()
    relation_labels = {
        "synonym": "同义词",
        "antonym": "反义词",
        "cognate": "同根词",
        "similar_form": "形近词",
    }

    kg_service = None

    try:
        kg_service = await get_kg_service()
        related = await kg_service.get_word_relations(term.lower(), limit=5)
        for item in related.relations:
            target = str(item.target or "").strip()
            if not target or target in seen:
                continue
            relation_type = item.relation_type.value
            out.append(
                LookupRecommendation(
                    word=target,
                    relation_type=relation_type,
                    score=round(float(item.strength), 4),
                    reason=f"与 {term} 构成{relation_labels.get(relation_type, '相关')}关系",
                )
            )
            seen.add(target)
    except Exception:
        pass

    if user_id is not None and len(out) < 5:
        try:
            for item in get_due_words(user_id, limit=5):
                word = str(item.word or "").strip()
                if not word or word.lower() == term.lower() or word in seen:
                    continue
                out.append(
                    LookupRecommendation(
                        word=word,
                        relation_type="review_due",
                        score=1.0,
                        reason="这个词已到复习时间，建议顺手回顾",
                    )
                )
                seen.add(word)
                if len(out) >= 5:
                    break
        except Exception:
            pass

    if user_id is not None and len(out) < 5 and kg_service is not None:
        learned_words = list(
            session.exec(
                select(VocabularyItem.word)
                .where(VocabularyItem.user_id == user_id)
                .order_by(VocabularyItem.updated_at.desc())
                .limit(20)
            ).all()
        )
        try:
            recommended = await kg_service.recommend_vocabulary(
                user_id=str(user_id),
                n=max(1, 5 - len(out)),
                weak_points=[term],
                learned_words=[str(x or "").strip() for x in learned_words if str(x or "").strip()],
            )
            for item in recommended.recommendations:
                word = str(item.word or "").strip()
                if not word or word in seen:
                    continue
                out.append(
                    LookupRecommendation(
                        word=word,
                        reason=str(item.reason or "").strip(),
                        score=round(float(item.score), 4),
                        relation_type=item.relation_type.value if item.relation_type else None,
                    )
                )
                seen.add(word)
        except Exception:
            pass

    return out[:5]


async def _resolve_lookup_payload(
    *,
    term: str,
    fuzzy: bool,
    include_relations: bool,
    user_id: int | None,
    source: str,
    session: Session,
) -> tuple[VocabLookupResponse, dict[str, Any]]:
    normalized_term = (term or "").strip()
    if not normalized_term:
        raise HTTPException(status_code=400, detail="term is required")

    entry = session.exec(
        select(PublicVocabEntry).where(PublicVocabEntry.term == normalized_term)
    ).first()

    definition = ""
    structured: dict[str, Any] = {}
    from_public_vocab = False
    cached = False

    if entry is not None and entry.definition:
        definition = entry.definition
        from_public_vocab = True
    else:
        es_hits = await search_vocabulary(normalized_term, fuzzy=fuzzy, size=5)
        best_hit = next(
            (
                hit for hit in es_hits
                if isinstance(hit, dict) and str(hit.get("word") or "").strip().lower() == normalized_term.lower()
            ),
            None,
        ) or (es_hits[0] if es_hits else None)
        if isinstance(best_hit, dict):
            definition = str(best_hit.get("definition") or "").strip()
            cached = True

        structured = await generate_vocab_fields(normalized_term)
        if not definition:
            definition = str(structured.get("meaning") or "").strip()
            if not definition:
                definition = await generate_definition(normalized_term)

    meaning, example, example_translation, definitions = _parse_definition_block(
        normalized_term,
        definition,
        structured.get("definitions") if isinstance(structured, dict) else None,
    )
    cefr_level, difficulty_level, exam_tags, school_stage = _estimate_vocab_metadata(
        normalized_term, definitions
    )
    recommendations = await _build_recommendations(
        term=normalized_term,
        user_id=user_id,
        include_relations=include_relations,
        session=session,
    )

    response = VocabLookupResponse(
        term=normalized_term,
        definition=definition or f"释义：{meaning}",
        from_public_vocab=from_public_vocab,
        meaning=meaning,
        example=example,
        example_translation=example_translation,
        definitions=definitions,
        recommendations=recommendations,
        cefr_level=cefr_level,
        difficulty_level=difficulty_level,
        exam_tags=exam_tags,
        school_stage=school_stage,
        cached=cached,
    )
    metadata = {
        "definitions": [item.model_dump() for item in definitions],
        "recommendations": [item.model_dump() for item in recommendations],
        "cefr_level": cefr_level,
        "difficulty_level": difficulty_level,
        "exam_tags": exam_tags,
        "school_stage": school_stage,
        "fuzzy": fuzzy,
        "source": source,
        "from_public_vocab": from_public_vocab,
        "cached": cached,
    }
    return response, metadata


@router.post("/lookup", response_model=VocabLookupResponse)
async def lookup_vocab(
    req: VocabLookupRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_user),
) -> VocabLookupResponse:
    user_id = _resolve_user_id(current_user, req.user_id)
    response, metadata = await _resolve_lookup_payload(
        term=req.term,
        fuzzy=req.fuzzy,
        include_relations=req.include_relations,
        user_id=user_id,
        source=req.source,
        session=session,
    )

    session.add(
        UserVocabQuery(
            user_id=user_id,
            session_id=req.session_id,
            conversation_id=req.conversation_id,
            term=response.term,
            source=req.source,
            result=response.definition,
            meta_data=metadata,
        )
    )
    session.commit()

    if user_id is not None and req.save_to_vocab:
        add_word(
            user_id=user_id,
            word=response.term,
            definition=response.meaning or response.definition,
            example=response.example,
        )
        create_record(
            user_id=user_id,
            record_type="vocabulary",
            content=response.term,
            metadata={
                "action": "lookup",
                "source": req.source,
                "cefr_level": response.cefr_level,
                "difficulty_level": response.difficulty_level,
                "recommendation_count": len(response.recommendations),
            },
        )

    return response


@router.post("/search", response_model=VocabLookupResponse)
async def search_vocab(
    req: VocabLookupRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_user),
) -> VocabLookupResponse:
    return await lookup_vocab(req, session, current_user)


@router.post("/lookup-ocr", response_model=VocabLookupOcrResponse)
async def lookup_vocab_ocr(
    req: VocabLookupOcrRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_user),
) -> VocabLookupOcrResponse:
    ocr_text = ocr_image_base64(req.image, language=req.language)
    if not ocr_text:
        raise HTTPException(status_code=400, detail="OCR failed or empty text")

    term = ocr_text.splitlines()[0].strip() if ocr_text.splitlines() else ocr_text.strip()
    if not term:
        raise HTTPException(status_code=400, detail="OCR text is empty")

    user_id = _resolve_user_id(current_user, req.user_id)
    response, metadata = await _resolve_lookup_payload(
        term=term,
        fuzzy=True,
        include_relations=req.include_relations,
        user_id=user_id,
        source="ocr",
        session=session,
    )
    session.add(
        UserVocabQuery(
            user_id=user_id,
            session_id=req.session_id,
            conversation_id=req.conversation_id,
            term=response.term,
            source="ocr",
            result=response.meaning or response.example or "",
            meta_data={"ocr_text": ocr_text, **metadata},
        )
    )
    session.commit()

    if user_id is not None and req.save_to_vocab:
        add_word(
            user_id=user_id,
            word=response.term,
            definition=response.meaning or response.definition,
            example=response.example,
        )
        create_record(
            user_id=user_id,
            record_type="vocabulary",
            content=response.term,
            metadata={
                "action": "lookup_ocr",
                "ocr_text": ocr_text,
                "cefr_level": response.cefr_level,
                "difficulty_level": response.difficulty_level,
            },
        )

    return VocabLookupOcrResponse(
        term=response.term,
        ocr_text=ocr_text,
        meaning=response.meaning or "暂无",
        example=response.example,
        example_translation=response.example_translation,
        definitions=response.definitions,
        recommendations=response.recommendations,
        cefr_level=response.cefr_level,
        difficulty_level=response.difficulty_level,
        exam_tags=response.exam_tags,
        school_stage=response.school_stage,
    )


@router.post("/generate", response_model=VocabGenerateResponse)
async def generate_vocab(
    req: VocabGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> VocabGenerateResponse:
    theme = (req.theme or "").strip()
    if not theme:
        raise HTTPException(status_code=400, detail="theme is required")

    task = generate_daily_vocab_task.delay(str(current_user.id or 0), theme, req.difficulty, req.count)
    return VocabGenerateResponse(
        success=True,
        data={
            "task_id": str(getattr(task, "id", "")),
            "status": "submitted",
            "theme": theme,
            "difficulty": req.difficulty,
            "count": req.count,
        },
    )


@router.get("/review", response_model=VocabReviewListResponse)
async def list_due_vocab_for_review(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> VocabReviewListResponse:
    words = get_due_words(current_user.id or 0, limit=limit)
    payload = [
        VocabReviewWord(
            id=int(word.id or 0),
            word=word.word,
            definition=word.definition,
            pronunciation=word.pronunciation,
            example=word.example,
            mastery_level=word.mastery_level,
            next_review_at=word.next_review_at.isoformat(),
        ).model_dump()
        for word in words
    ]
    return VocabReviewListResponse(
        success=True,
        data={
            "due_today": len(words),
            "words": payload,
        },
    )


@router.post("/review", response_model=VocabReviewSubmitResponse)
async def submit_vocab_review(
    req: VocabReviewSubmitRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> VocabReviewSubmitResponse:
    # 先校验所有权，防止 IDOR（越权修改他人复习记录）
    existing = session.get(VocabularyItem, req.vocab_id)
    if existing is None or existing.user_id != (current_user.id or 0):
        raise HTTPException(status_code=404, detail="vocab item not found")

    item = review_word(
        req.vocab_id,
        correct=req.correct if req.correct is not None else int(req.quality or 0) >= 3,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="vocab item not found")

    create_record(
        user_id=current_user.id or 0,
        record_type="vocabulary",
        content=item.word,
        metadata={
            "action": "review",
            "vocab_id": req.vocab_id,
            "quality": req.quality,
            "correct": req.correct if req.correct is not None else int(req.quality or 0) >= 3,
            "mastery_level": item.mastery_level,
        },
    )

    return VocabReviewSubmitResponse(
        success=True,
        data={
            "id": item.id,
            "word": item.word,
            "mastery_level": item.mastery_level,
            "next_review_at": item.next_review_at.isoformat(),
        },
    )
