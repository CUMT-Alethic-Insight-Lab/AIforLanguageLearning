"""Celery 异步任务定义"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from .celery_app import app

logger = logging.getLogger(__name__)


def _run_async_coro(coro: Any) -> Any:
    """在同步上下文中运行异步协程，兼容 Celery eager / 已有事件循环的场景。"""
    if not inspect.iscoroutine(coro):
        return coro
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@app.task(bind=True, max_retries=3)
def grade_essay_task(self, essay_id: str, content: str) -> dict[str, Any]:
    """作文批改异步任务。

    流程：
    1. 若 content 是图片 key（不含空格且含 /），从 MinIO 下载并 OCR 提取文本
    2. 调用统一批改流水线（预处理 + LLM + 多维度评分标准化）
    3. 写入 EssayResult（幂等性保护）
    """
    try:
        return _do_grade_essay(essay_id, content)
    except Exception as exc:
        logger.error(f"grade_essay_task error: {exc}")
        raise self.retry(exc=exc, countdown=60)


def _do_grade_essay(essay_id: str, content: str) -> dict[str, Any]:
    import base64

    import httpx
    from sqlmodel import Session

    from app.db import get_engine
    from app.domain.essay_preprocessing import preprocess_essay
    from app.infrastructure.storage.minio_storage import get_minio_storage
    from app.models import EssayResult, EssaySubmission
    from app.ocr import ocr_image_base64

    essay_text = content
    image_key = ""

    # 简单启发式：若 content 不含空格且包含 /，认为是 MinIO object key
    if " " not in content and "/" in content:
        image_key = content
        try:
            storage = get_minio_storage()
            bucket = "essays"
            presigned_url = _run_async_coro(
                storage.generate_presigned_url(bucket, image_key, expires=3600)
            )
            resp = httpx.get(presigned_url, timeout=30.0)
            resp.raise_for_status()
            image_b64 = base64.b64encode(resp.content).decode("utf-8")
            essay_text = ocr_image_base64(image_b64, language="english")
            if not essay_text:
                logger.error(f"OCR failed for image key {image_key}")
                essay_text = ""
        except Exception as exc:
            logger.error(f"Download/OCR error for image key {image_key}: {exc}")
            essay_text = ""

    if not essay_text:
        # 记录失败状态，避免无限重试
        with Session(get_engine()) as session:
            submission = session.get(EssaySubmission, int(essay_id))
            if submission is not None and image_key:
                submission.ocr_text = "(OCR failed)"
                session.add(submission)
                session.commit()
        return {
            "essay_id": essay_id,
            "status": "failed",
            "reason": "empty_ocr" if image_key else "empty_content",
        }

    # 文本预处理
    preprocessed = preprocess_essay(essay_text)
    essay_text = preprocessed["normalized"]

    # 截断超长文本，控制 Token 成本
    max_words = 2000
    words = essay_text.split()
    if len(words) > max_words:
        essay_text = " ".join(words[:max_words]) + "\n\n[Text truncated due to length limit]"

    # 统一批改流水线（同步封装）
    from app.application.essay_grading import run_grading_pipeline_sync
    from app.infrastructure.persistence.cache.sync_redis_cache import essay_cache_key, get_sync_redis_cache

    # Redis 去重缓存：相同作文文本直接复用已有结果
    cache = get_sync_redis_cache()
    cache_key = essay_cache_key(essay_text)
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        logger.info(f"Essay cache hit for submission {essay_id}, skipping LLM")
        result_json = cached_result
    else:
        llm_language = preprocessed["language"] if preprocessed["language"] in ("zh", "en") else "en"
        result_json = run_grading_pipeline_sync(ocr_text=essay_text, language=llm_language)
        cache.set(cache_key, result_json, ttl=3600)

    total_score = result_json["total_score"]
    score_int = int(round(total_score * 10))
    score_int = max(0, min(100, score_int))

    # 幂等性：先检查是否已有结果
    with Session(get_engine()) as session:
        submission = session.get(EssaySubmission, int(essay_id))
        if submission is None:
            return {"essay_id": essay_id, "status": "failed", "reason": "submission_not_found"}

        existing = session.exec(
            __import__("sqlmodel").select(EssayResult).where(EssayResult.submission_id == int(essay_id))
        ).first()
        if existing is not None:
            logger.info(f"EssayResult already exists for submission {essay_id}, skipping")
            return {"essay_id": essay_id, "status": "already_graded", "result": result_json}

        if image_key:
            submission.ocr_text = essay_text
            session.add(submission)

        essay_result = EssayResult(
            submission_id=int(essay_id),
            score=score_int,
            result=result_json,
        )
        session.add(essay_result)
        session.commit()

    logger.info(f"Graded essay {essay_id}, score={score_int}")
    return {"essay_id": essay_id, "score": score_int, "result": result_json}


@app.task(bind=True, max_retries=3)
def generate_daily_vocab_task(
    self,
    user_id: str,
    theme: str = "daily life",
    difficulty: str = "intermediate",
    count: int = 20,
) -> dict[str, Any]:
    """每日词汇生成异步任务"""
    try:
        themed_words: dict[str, list[str]] = {
            "business english": [
                "agenda",
                "negotiate",
                "deadline",
                "proposal",
                "stakeholder",
                "invoice",
                "quarterly",
                "delegate",
                "strategy",
                "presentation",
            ],
            "travel": [
                "itinerary",
                "boarding pass",
                "customs",
                "reservation",
                "departure",
                "destination",
                "luggage",
                "transit",
                "landmark",
                "souvenir",
            ],
            "daily life": [
                "routine",
                "schedule",
                "grocery",
                "commute",
                "laundry",
                "exercise",
                "appointment",
                "weekend",
                "neighbor",
                "budget",
            ],
            "academic": [
                "hypothesis",
                "analyze",
                "evidence",
                "citation",
                "lecture",
                "curriculum",
                "seminar",
                "research",
                "thesis",
                "argument",
            ],
        }
        difficulty_prefix: dict[str, str] = {
            "beginner": "基础",
            "elementary": "基础",
            "intermediate": "进阶",
            "advanced": "高阶",
        }

        normalized_theme = str(theme or "daily life").strip().lower()
        normalized_difficulty = str(difficulty or "intermediate").strip().lower()
        pool = themed_words.get(normalized_theme) or themed_words["daily life"]
        words = pool[: max(1, min(int(count or 20), len(pool)))]

        try:
            numeric_user_id = int(user_id)
        except (TypeError, ValueError):
            numeric_user_id = 0

        if numeric_user_id > 0:
            from ...application.db_learning import create_record
            from ...application.db_vocabulary import add_word

            for word in words:
                add_word(
                    user_id=numeric_user_id,
                    word=word,
                    definition=f"{difficulty_prefix.get(normalized_difficulty, '进阶')}词汇：{word}",
                )
            create_record(
                user_id=numeric_user_id,
                record_type="vocabulary",
                content=f"theme={normalized_theme}",
                metadata={
                    "action": "generate_vocab",
                    "theme": normalized_theme,
                    "difficulty": normalized_difficulty,
                    "count": len(words),
                    "words": words,
                },
            )

        result = {
            "user_id": user_id,
            "theme": normalized_theme,
            "difficulty": normalized_difficulty,
            "words": words,
        }
        logger.info("Generated daily vocab for user %s theme=%s count=%s", user_id, normalized_theme, len(words))
        return result
    except Exception as exc:
        logger.error(f"generate_daily_vocab_task error: {exc}")
        raise self.retry(exc=exc, countdown=60)
