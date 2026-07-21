"""上下文存储模块（已废弃，不在主链路中使用）

⚠️  WARNING: 此模块不被任何主链路代码 import，属于死代码。
    SQLiteContextStore.save() 写入 type="MESSAGE" 事件，
    WS handler 的 get_all_chat_history_from_events() 只读取
    USER_MESSAGE / AI_MESSAGE / ASR_FINAL / LLM_RESULT 类型，
    两者完全不通。保留仅供参考，请勿在新功能中使用。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from .db import get_engine

if TYPE_CHECKING:
    from .model_router import ConversationContext

logger = logging.getLogger(__name__)


class ContextStore:
    """上下文存储基类"""

    def save(self, context: "ConversationContext") -> bool:
        """保存上下文"""
        raise NotImplementedError

    def load(self, conversation_id: str) -> "ConversationContext | None":
        """加载上下文"""
        raise NotImplementedError

    def delete(self, conversation_id: str) -> bool:
        """删除上下文"""
        raise NotImplementedError

    def list_conversations(self, session_id: str | None = None) -> list[str]:
        """列出现有对话ID"""
        raise NotImplementedError


class SQLiteContextStore(ContextStore):
    """SQLite上下文存储"""

    def __init__(self) -> None:
        self._engine = get_engine()

    def save(self, context: "ConversationContext") -> bool:
        """保存上下文到SQLite"""
        try:
            from .models import ConversationEvent

            with Session(self._engine) as session:
                existing = session.exec(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == context.conversation_id
                    )
                ).all()
                existing_seqs = {e.seq for e in existing}

                for i, msg in enumerate(context.messages):
                    if i in existing_seqs:
                        continue
                    event = ConversationEvent(
                        conversation_id=context.conversation_id,
                        session_id=context.session_id,
                        seq=i,
                        type="MESSAGE",
                        ts=int(msg.timestamp * 1000),
                        payload={
                            "role": msg.role,
                            "content": msg.content,
                            "token_count": msg.token_count,
                        },
                    )
                    session.add(event)

                session.commit()
                logger.debug(
                    f"Saved context {context.conversation_id} with {len(context.messages)} messages"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to save context {context.conversation_id}: {e}")
            return False

    def load(self, conversation_id: str) -> "ConversationContext | None":
        """从SQLite加载上下文"""
        try:
            from .model_router import ConversationContext, ConversationMessage
            from .models import ConversationEvent

            with Session(self._engine) as session:
                events = session.exec(
                    select(ConversationEvent)
                    .where(ConversationEvent.conversation_id == conversation_id)
                    .order_by(ConversationEvent.seq)
                ).all()

                if not events:
                    return None

                first_event = events[0]
                context = ConversationContext(
                    conversation_id=conversation_id,
                    session_id=first_event.session_id,
                )

                for event in events:
                    if event.type == "MESSAGE" and isinstance(event.payload, dict):
                        msg = ConversationMessage(
                            role=event.payload.get("role", "user"),
                            content=event.payload.get("content", ""),
                            timestamp=event.ts / 1000,
                            token_count=event.payload.get("token_count", 0),
                        )
                        context.messages.append(msg)

                logger.debug(
                    f"Loaded context {conversation_id} with {len(context.messages)} messages"
                )
                return context

        except Exception as e:
            logger.error(f"Failed to load context {conversation_id}: {e}")
            return None

    def delete(self, conversation_id: str) -> bool:
        """删除上下文"""
        try:
            from .models import ConversationEvent

            with Session(self._engine) as session:
                events = session.exec(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == conversation_id
                    )
                ).all()
                for event in events:
                    session.delete(event)
                session.commit()
                logger.debug(f"Deleted context {conversation_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to delete context {conversation_id}: {e}")
            return False

    def list_conversations(self, session_id: str | None = None) -> list[str]:
        """列出现有对话ID"""
        try:
            from .models import ConversationEvent

            with Session(self._engine) as session:
                query = select(ConversationEvent.conversation_id).distinct()
                if session_id:
                    query = query.where(ConversationEvent.session_id == session_id)
                results = session.exec(query).all()
                return list(results)

        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
            return []


class RedisContextStore(ContextStore):
    """Redis上下文存储（可选）"""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._try_connect()

    def _try_connect(self) -> bool:
        """尝试连接Redis"""
        try:
            import redis

            url = self._redis_url or "redis://localhost:6379/0"
            self._redis = redis.from_url(url, decode_responses=True)
            self._redis.ping()
            logger.info("Redis context store connected")
            return True
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            self._redis = None
            return False

    def save(self, context: "ConversationContext") -> bool:
        if not self._redis:
            return False
        try:
            key = self._get_key(context.conversation_id)
            data = {
                "conversation_id": context.conversation_id,
                "session_id": context.session_id,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "token_count": msg.token_count,
                    }
                    for msg in context.messages
                ],
            }
            self._redis.setex(key, 7 * 24 * 3600, json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Failed to save context to Redis: {e}")
            return False

    def load(self, conversation_id: str) -> "ConversationContext | None":
        if not self._redis:
            return None
        try:
            from .model_router import ConversationContext, ConversationMessage

            key = self._get_key(conversation_id)
            raw = self._redis.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            context = ConversationContext(
                conversation_id=data["conversation_id"],
                session_id=data.get("session_id", ""),
            )
            for msg_data in data.get("messages", []):
                msg = ConversationMessage(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    timestamp=msg_data.get("timestamp", 0),
                    token_count=msg_data.get("token_count", 0),
                )
                context.messages.append(msg)
            return context
        except Exception as e:
            logger.error(f"Failed to load context from Redis: {e}")
            return None

    def delete(self, conversation_id: str) -> bool:
        if not self._redis:
            return False
        try:
            key = self._get_key(conversation_id)
            self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete context from Redis: {e}")
            return False

    def list_conversations(self, session_id: str | None = None) -> list[str]:
        if not self._redis:
            return []
        try:
            pattern = self._get_key("*")
            keys = self._redis.keys(pattern)
            conversation_ids = [k.replace("aifl:context:", "") for k in keys]
            if session_id:
                filtered = []
                for cid in conversation_ids:
                    context = self.load(cid)
                    if context and context.session_id == session_id:
                        filtered.append(cid)
                return filtered
            return conversation_ids
        except Exception as e:
            logger.error(f"Failed to list conversations from Redis: {e}")
            return []

    def _get_key(self, conversation_id: str) -> str:
        return f"aifl:context:{conversation_id}"


class HybridContextStore(ContextStore):
    """混合存储：Redis优先，失败时回退到SQLite"""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_store = RedisContextStore(redis_url)
        self._sqlite_store = SQLiteContextStore()

    def save(self, context: "ConversationContext") -> bool:
        redis_ok = self._redis_store.save(context)
        sqlite_ok = self._sqlite_store.save(context)
        return redis_ok or sqlite_ok

    def load(self, conversation_id: str) -> "ConversationContext | None":
        context = self._redis_store.load(conversation_id)
        if context:
            return context
        return self._sqlite_store.load(conversation_id)

    def delete(self, conversation_id: str) -> bool:
        redis_ok = self._redis_store.delete(conversation_id)
        sqlite_ok = self._sqlite_store.delete(conversation_id)
        return redis_ok or sqlite_ok

    def list_conversations(self, session_id: str | None = None) -> list[str]:
        redis_ids = self._redis_store.list_conversations(session_id)
        sqlite_ids = self._sqlite_store.list_conversations(session_id)
        return list(dict.fromkeys(redis_ids + sqlite_ids))


# 全局上下文存储实例
_context_store: ContextStore | None = None


def get_context_store() -> ContextStore:
    """获取全局上下文存储实例"""
    global _context_store
    if _context_store is None:
        _context_store = HybridContextStore()
    return _context_store


def set_context_store(store: ContextStore) -> None:
    """设置全局上下文存储实例（主要用于测试）"""
    global _context_store
    _context_store = store
