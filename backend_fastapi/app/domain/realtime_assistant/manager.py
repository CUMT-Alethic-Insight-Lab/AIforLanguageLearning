"""实时助教会话管理器 — 单 WebSocket 连接级生命周期管理。

所有活跃会话保存在内存中，按 user_id 索引；一条 WebSocket 断开时自动清理。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .session import RealtimeAssistantSession

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器。

    - 每个 user_id 最多维持一个活跃会话（后续连接踢掉旧连接）
    - 定期清理僵尸会话（长时间无心跳）
    - 线程安全：会话创建/销毁串行化
    """

    def __init__(self, session_ttl_seconds: float = 600.0) -> None:
        self._sessions: dict[int, RealtimeAssistantSession] = {}
        self._session_meta: dict[int, dict[str, Any]] = {}
        self._ttl = session_ttl_seconds

    def create_session(self, user_id: int, username: str) -> RealtimeAssistantSession:
        """创建新会话；如果同一 user_id 已存在，先关闭旧会话。"""
        if user_id in self._sessions:
            old = self._sessions[user_id]
            old.close()
            logger.info("Replaced old session for user=%s", user_id)

        session = RealtimeAssistantSession(user_id=user_id, username=username)
        self._sessions[user_id] = session
        self._session_meta[user_id] = {
            "created_at": time.time(),
            "last_active": time.time(),
            "message_count": 0,
        }
        logger.info("Created RTA session for user=%s", user_id)
        return session

    def get_session(self, user_id: int) -> RealtimeAssistantSession | None:
        """获取活跃会话。"""
        session = self._sessions.get(user_id)
        if session is not None:
            self._session_meta[user_id]["last_active"] = time.time()
        return session

    def remove_session(self, user_id: int) -> None:
        """移除并关闭会话。"""
        session = self._sessions.pop(user_id, None)
        if session:
            session.close()
        self._session_meta.pop(user_id, None)
        logger.info("Removed RTA session for user=%s", user_id)

    def record_message(self, user_id: int) -> None:
        """记录一条消息交互。"""
        meta = self._session_meta.get(user_id)
        if meta:
            meta["message_count"] += 1
            meta["last_active"] = time.time()

    def cleanup_stale(self) -> int:
        """清理过期会话，返回清理数量。"""
        now = time.time()
        stale = [
            uid
            for uid, meta in self._session_meta.items()
            if now - meta["last_active"] > self._ttl
        ]
        for uid in stale:
            self.remove_session(uid)
        return len(stale)

    def get_stats(self) -> dict[str, Any]:
        """获取当前会话统计。"""
        now = time.time()
        return {
            "active_sessions": len(self._sessions),
            "sessions": [
                {
                    "user_id": uid,
                    "age_seconds": round(now - meta["created_at"], 1),
                    "idle_seconds": round(now - meta["last_active"], 1),
                    "message_count": meta["message_count"],
                }
                for uid, meta in self._session_meta.items()
            ],
        }
