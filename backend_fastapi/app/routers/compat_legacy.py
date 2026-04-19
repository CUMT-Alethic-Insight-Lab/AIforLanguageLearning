from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..llm import generate_vocab_fields
from ..ocr import ocr_image_base64
from .essays import EssayGradeRequest, grade
from .learning import LearningAnalyzeRequest, learning_analyze, learning_stats
from .vocab import VocabLookupRequest, lookup_vocab

router = APIRouter(tags=["compat-legacy"])


class CompatVocabRequest(BaseModel):
    word: str


class CompatOCRRequest(BaseModel):
    image: str
    language: str = "english"


class CompatEssayRequest(BaseModel):
    text: str | None = None
    image: str | None = None
    language: str = "english"


class CompatAnalyzeRequest(BaseModel):
    dimension: str


def _to_compat_vocab_data(term: str, fields: dict[str, Any], *, ocr_text: str = "") -> dict[str, Any]:
    meaning = str(fields.get("meaning") or "").strip() or "暂无"
    example = str(fields.get("example") or "").strip()
    example_translation = str(fields.get("example_translation") or "").strip()

    raw_defs = fields.get("definitions")
    defs: list[dict[str, Any]] = []
    if isinstance(raw_defs, list):
        for item in raw_defs:
            if not isinstance(item, dict):
                continue
            defs.append(
                {
                    "meaning": str(item.get("meaning") or "").strip(),
                    "example": str(item.get("example") or "").strip(),
                    "exampleTranslation": str(item.get("example_translation") or "").strip(),
                }
            )
        defs = [x for x in defs if x.get("meaning") or x.get("example") or x.get("exampleTranslation")]

    data: dict[str, Any] = {
        "word": term,
        "definitions": defs
        if defs
        else [
            {
                "meaning": meaning,
                "example": example,
                "exampleTranslation": example_translation,
            }
        ],
        "meaning": meaning,
    }
    if ocr_text:
        data["ocrText"] = ocr_text
    return data


@router.post("/api/query/vocabulary")
async def compat_query_vocabulary(req: CompatVocabRequest, session: Session = Depends(get_session)) -> dict:
    term = str(req.word or "").strip()
    if not term:
        return {"success": False, "error": "word is required"}

    await lookup_vocab(VocabLookupRequest(term=term, source="manual"), session, current_user=None)
    fields = await generate_vocab_fields(term)
    return {"success": True, "data": _to_compat_vocab_data(term, fields)}


@router.post("/api/query/ocr")
async def compat_query_ocr(req: CompatOCRRequest, session: Session = Depends(get_session)) -> dict:
    ocr_text = ocr_image_base64(req.image, language=req.language)
    if not ocr_text:
        return {"success": False, "error": "OCR failed or OCR backend unavailable"}

    term = ocr_text.splitlines()[0].strip() if ocr_text.splitlines() else ocr_text.strip()
    if not term:
        return {"success": False, "error": "OCR text is empty"}

    await lookup_vocab(VocabLookupRequest(term=term, source="ocr"), session, current_user=None)
    fields = await generate_vocab_fields(term)
    return {"success": True, "data": _to_compat_vocab_data(term, fields, ocr_text=ocr_text)}


@router.post("/api/essay/correct")
async def compat_essay_correct(req: CompatEssayRequest, session: Session = Depends(get_session)) -> dict:
    text = str(req.text or "").strip()
    if (not text) and req.image:
        text = ocr_image_base64(req.image, language=req.language)

    if not text:
        return {"success": False, "error": "text is required (or OCR failed)"}

    result = await grade(
        EssayGradeRequest(
            text=text,
            language=(req.language or "english"),
            session_id="",
        ),
        session,
    )
    out = result.result
    score = int(out.get("score") or 0)

    scores_obj = out.get("scores") if isinstance(out.get("scores"), dict) else {}
    scores = {
        "vocabulary": int(scores_obj.get("vocabulary", score)),
        "grammar": int(scores_obj.get("grammar", score)),
        "fluency": int(scores_obj.get("fluency", score)),
        "logic": int(scores_obj.get("logic", score)),
        "content": int(scores_obj.get("content", score)),
        "structure": int(scores_obj.get("structure", score)),
        "total": int(scores_obj.get("total", score)),
    }

    data = {
        "original": text,
        "correction": str(out.get("rewritten") or ""),
        "scores": scores,
        "feedback": str(out.get("feedback") or ""),
        "suggestions": [x for x in (out.get("suggestions") or []) if isinstance(x, str)],
        "questions": [x for x in (out.get("questions") or []) if isinstance(x, str)],
        "improvements": [x for x in (out.get("improvements") or []) if isinstance(x, str)],
        "evaluation": str(out.get("evaluation") or ""),
    }
    return {"success": True, "data": data}


@router.get("/api/learning/stats")
async def compat_learning_stats(session: Session = Depends(get_session)) -> dict:
    stats = await learning_stats(session)
    return {
        "success": True,
        "data": {
            "vocabulary": int(stats.vocabulary),
            "essay": int(stats.essay),
            "dialogue": int(stats.dialogue),
            "analysis": int(stats.analysis),
        },
    }


@router.post("/api/learning/analyze")
async def compat_learning_analyze(req: CompatAnalyzeRequest, session: Session = Depends(get_session)) -> dict:
    out = await learning_analyze(LearningAnalyzeRequest(dimension=req.dimension), session)
    return {
        "success": True,
        "data": {
            "dimension": out.dimension,
            "score": out.score,
            "trend": out.trend,
            "insights": out.insights,
            "recommendations": out.recommendations,
            "visualization": out.visualization,
        },
    }
