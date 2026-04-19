from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from ..application.essay_grading import run_grading_pipeline
from ..application.event_service import append_event
from ..db import get_session
from ..infrastructure.messaging.tasks import grade_essay_task
from ..models import ConversationEvent, EssayResult, EssaySubmission
from ..ocr import ocr_image_base64

router = APIRouter(prefix="/v1/essays", tags=["essays"])


class EssaySubmitRequest(BaseModel):
    content: str | None = None
    image_key: str | None = None
    language: str = "en"
    session_id: str = "anonymous"
    conversation_id: str | None = None
    request_id: str | None = None
    user_id: int | None = None


class EssaySubmitResponse(BaseModel):
    success: bool = True
    data: dict[str, Any]


class EssayGradeRequest(BaseModel):
    text: str | None = None
    image: str | None = None
    language: str = "en"
    session_id: str = "anonymous"
    conversation_id: str | None = None
    request_id: str | None = None


class EssayGradeResponse(BaseModel):
    submission_id: int
    session_id: str
    conversation_id: str
    request_id: str
    score: int
    result: dict[str, Any]


class EssayGetResponse(BaseModel):
    submission_id: int
    session_id: str
    conversation_id: str
    request_id: str
    ocr_text: str
    language: str
    score: int | None
    result: dict[str, Any]
    status: str = "completed"


class EssayGradeOcrRequest(BaseModel):
    image: str
    language: str = "english"
    session_id: str = "anonymous"
    conversation_id: str | None = None
    request_id: str | None = None


async def _grade_and_persist(
    *,
    ocr_text: str,
    language: str,
    session_id: str,
    conversation_id: str,
    request_id: str,
    session: Session,
    user_id: int | None = None,
) -> EssayGradeResponse:
    ts = int(time.time() * 1000)

    submission = EssaySubmission(
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        ocr_text=ocr_text,
        language=language,
    )
    session.add(submission)
    session.commit()
    session.refresh(submission)

    submission_id = submission.id
    if submission_id is None:
        raise HTTPException(status_code=500, detail="failed to create submission")

    append_event(
        session,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        event_type="TASK_STARTED",
        payload={"task": "essay_grade", "submission_id": submission_id, "language": language},
        ts=ts,
        final=False,
    )
    session.commit()

    # 统一批改流水线（预处理 + LLM + 标准化评分）
    result_json = await run_grading_pipeline(ocr_text=ocr_text, language=language)
    score_int = int(round(result_json["total_score"] * 10))
    score_int = max(0, min(100, score_int))

    essay_result = EssayResult(
        submission_id=int(submission_id),
        score=score_int,
        result=result_json,
    )
    session.add(essay_result)

    append_event(
        session,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        event_type="ANALYSIS_RESULT",
        payload={
            "kind": "essay_grade",
            "submission_id": submission_id,
            "score": score_int,
            "result": result_json,
        },
        ts=ts,
        final=False,
    )
    append_event(
        session,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        event_type="TASK_FINISHED",
        payload={"ok": True, "submission_id": submission_id},
        ts=ts,
        final=True,
    )

    session.commit()

    return EssayGradeResponse(
        submission_id=int(submission_id),
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        score=score_int,
        result=result_json,
    )


@router.post("/grade", response_model=EssayGradeResponse)
async def grade(req: EssayGradeRequest, session: Session = Depends(get_session)) -> EssayGradeResponse:
    # 优先使用 text，如果提供了 image 则 OCR 提取文本
    text = (req.text or "").strip()
    image = (req.image or "").strip()

    if not text and not image:
        raise HTTPException(status_code=400, detail="text or image is required")

    if text:
        ocr_text = text
    else:
        ocr_text = ocr_image_base64(image, language=req.language)
        ocr_text = str(ocr_text or "").strip()
        if not ocr_text:
            raise HTTPException(status_code=400, detail="ocr failed or empty text")

    session_id = (req.session_id or "anonymous").strip() or "anonymous"
    conversation_id = (req.conversation_id or f"conv_{uuid.uuid4().hex[:8]}").strip()
    request_id = (req.request_id or f"req_{uuid.uuid4().hex[:10]}").strip()
    language = (req.language or "").strip() or "en"
    return await _grade_and_persist(
        ocr_text=ocr_text,
        language=language,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        session=session,
    )


@router.post("/grade-ocr", response_model=EssayGradeResponse)
async def grade_ocr(req: EssayGradeOcrRequest, session: Session = Depends(get_session)) -> EssayGradeResponse:
    text = ocr_image_base64(req.image, language=req.language)
    text = str(text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="ocr failed or empty text")

    session_id = (req.session_id or "anonymous").strip() or "anonymous"
    conversation_id = (req.conversation_id or f"conv_{uuid.uuid4().hex[:8]}").strip()
    request_id = (req.request_id or f"req_{uuid.uuid4().hex[:10]}").strip()
    language = (req.language or "").strip() or "english"

    return await _grade_and_persist(
        ocr_text=text,
        language=language,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        session=session,
    )


@router.post("", response_model=EssaySubmitResponse)
async def submit_essay(req: EssaySubmitRequest, session: Session = Depends(get_session)) -> EssaySubmitResponse:
    content = (req.content or "").strip()
    image_key = (req.image_key or "").strip()

    if not content and not image_key:
        raise HTTPException(status_code=400, detail="content or image_key is required")

    session_id = (req.session_id or "anonymous").strip() or "anonymous"
    conversation_id = (req.conversation_id or f"conv_{uuid.uuid4().hex[:8]}").strip()
    request_id = (req.request_id or f"req_{uuid.uuid4().hex[:10]}").strip()
    language = (req.language or "").strip() or "en"

    ts = int(time.time() * 1000)

    submission = EssaySubmission(
        user_id=req.user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        ocr_text=content if content else "",
        language=language,
    )
    session.add(submission)
    session.commit()
    session.refresh(submission)

    submission_id = submission.id
    if submission_id is None:
        raise HTTPException(status_code=500, detail="failed to create submission")

    append_event(
        session,
        user_id=req.user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        event_type="TASK_STARTED",
        payload={"task": "essay_grade", "submission_id": submission_id, "language": language},
        ts=ts,
        final=False,
    )
    session.commit()

    task_payload = content if content else image_key
    task_result = grade_essay_task.delay(str(submission_id), task_payload)

    return EssaySubmitResponse(
        data={
            "submission_id": submission_id,
            "task_id": task_result.id,
            "status": "submitted",
        }
    )


@router.get("/{submission_id}", response_model=EssayGetResponse)
def get_essay(submission_id: int, session: Session = Depends(get_session)) -> EssayGetResponse:
    submission = session.get(EssaySubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")

    sid = submission.id
    if sid is None:
        raise HTTPException(status_code=500, detail="invalid submission")

    essay_result = session.exec(
        select(EssayResult)
        .where(EssayResult.submission_id == submission_id)
        .order_by(col(EssayResult.id).desc())
    ).first()

    status = "completed" if essay_result is not None else "grading"

    return EssayGetResponse(
        submission_id=int(sid),
        session_id=str(submission.session_id or ""),
        conversation_id=str(submission.conversation_id or ""),
        request_id=str(submission.request_id or ""),
        ocr_text=str(submission.ocr_text or ""),
        language=str(submission.language or ""),
        score=int(essay_result.score) if essay_result is not None and essay_result.score is not None else None,
        result=dict(essay_result.result or {}) if essay_result is not None else {},
        status=status,
    )
