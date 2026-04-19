"""对话事件统一持久化服务（能力复用层）。

消除 essays.py 与 main.py WebSocket 中重复的事件持久化逻辑，
提供基于外部 Session 的单事务写入和独立事务写入两种模式。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, select

from app.models import ConversationEvent


def next_seq(session: Session, conversation_id: str) -> int:
    """获取指定 conversation 的下一个事件序号。"""
    max_seq = session.exec(
        select(ConversationEvent.seq)
        .where(ConversationEvent.conversation_id == conversation_id)
        .order_by(col(ConversationEvent.seq).desc())
    ).first()
    return int(max_seq or 0) + 1


def append_event(
    session: Session,
    *,
    user_id: int | None = None,
    session_id: str,
    conversation_id: str,
    request_id: str,
    event_type: str,
    payload: dict[str, Any],
    ts: int,
    final: bool = False,
) -> int:
    """在已有 Session 中追加 ConversationEvent（调用者负责 commit）。

    适用于需要与 submission/result 等操作保持同一事务边界的场景（如 HTTP 同步批改）。
    """
    seq = next_seq(session, conversation_id)
    session.add(
        ConversationEvent(
            user_id=user_id,
            session_id=session_id,
            conversation_id=conversation_id,
            seq=seq,
            type=event_type,
            ts=ts,
            request_id=request_id,
            final=bool(final),
            payload=dict(payload or {}),
        )
    )
    return seq
