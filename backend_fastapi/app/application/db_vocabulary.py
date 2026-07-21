from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from ..db import get_engine
from ..domain.models import VocabularyItem
from ..domain.srs.sm2 import calculate_next_review


def add_word(
    user_id: int,
    word: str,
    definition: str = "",
    pronunciation: str = "",
    example: str = "",
) -> VocabularyItem:
    with Session(get_engine()) as session:
        existing = session.exec(
            select(VocabularyItem).where(
                VocabularyItem.user_id == user_id, VocabularyItem.word == word
            )
        ).first()
        now = datetime.utcnow()
        if existing:
            existing.definition = definition
            existing.pronunciation = pronunciation
            existing.example = example
            existing.updated_at = now
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        item = VocabularyItem(
            user_id=user_id,
            word=word,
            definition=definition,
            pronunciation=pronunciation,
            example=example,
            mastery_level=0,
            next_review_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return item


def get_due_words(user_id: int, limit: int = 20) -> list[VocabularyItem]:
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        return list(
            session.exec(
                select(VocabularyItem)
                .where(VocabularyItem.user_id == user_id)
                .where(VocabularyItem.next_review_at <= now)
                .order_by(col(VocabularyItem.mastery_level))
                .order_by(col(VocabularyItem.next_review_at))
                .limit(limit)
            ).all()
        )


def review_word(item_id: int, correct: bool) -> VocabularyItem | None:
    with Session(get_engine()) as session:
        item = session.get(VocabularyItem, item_id)
        if not item:
            return None
        new_level, next_review = calculate_next_review(item.mastery_level, correct)
        item.mastery_level = new_level
        item.next_review_at = next_review
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        return item
