from __future__ import annotations

from datetime import datetime, timedelta


def calculate_next_review(mastery_level: int, correct: bool) -> tuple[int, datetime]:
    """根据掌握程度和回答正确性计算新的掌握等级和下次复习时间。

    实现简化的 SM-2 类似算法：
    - 答对：等级 +1，间隔按 2^(等级-1) 天递增（1天, 2天, 4天, 8天, 16天, 32天...）
    - 答错：等级 -1（最低 0），10 分钟后再次复习

    Args:
        mastery_level: 当前掌握等级
        correct: 是否回答正确

    Returns:
        (new_mastery_level, next_review_at)
    """
    now = datetime.utcnow()
    if correct:
        new_level = mastery_level + 1
        days = 2 ** (new_level - 1) if new_level > 0 else 1
        next_review = now + timedelta(days=days)
    else:
        new_level = max(0, mastery_level - 1)
        next_review = now + timedelta(minutes=10)
    return new_level, next_review


def update_mastery(mastery_level: int, correct: bool) -> tuple[int, datetime]:
    """calculate_next_review 的别名，保持语义清晰。"""
    return calculate_next_review(mastery_level, correct)
