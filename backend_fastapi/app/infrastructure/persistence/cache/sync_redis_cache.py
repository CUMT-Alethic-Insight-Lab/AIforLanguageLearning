"""同步 Redis 缓存辅助（供 Celery 等同步上下文使用）。

与 RedisCache（异步）互补，提供同步 get/set/delete。
Redis 不可用时静默降级，不阻塞主业务流程。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SyncRedisCache:
    """同步 Redis 缓存包装。"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        default_ttl: int = 3600,
        key_prefix: str = "aifl:",
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self._client: Any | None = None
        self._connected = False

    def _get_client(self) -> Any | None:
        """懒加载同步 Redis 客户端。"""
        if self._client is not None:
            return self._client
        try:
            import redis as _redis

            self._client = _redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            self._client.ping()
            self._connected = True
            return self._client
        except Exception as e:
            logger.warning(f"SyncRedis not available: {e}")
            self._connected = False
            return None

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def get(self, key: str) -> Any | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            full_key = self._make_key(key)
            raw = client.get(full_key)
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.error(f"SyncRedis get error: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        client = self._get_client()
        if client is None:
            return False
        try:
            full_key = self._make_key(key)
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            expiration = ttl or self.default_ttl
            client.setex(full_key, expiration, serialized)
            return True
        except Exception as e:
            logger.error(f"SyncRedis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        client = self._get_client()
        if client is None:
            return False
        try:
            full_key = self._make_key(key)
            result = client.delete(full_key)
            return result > 0
        except Exception as e:
            logger.error(f"SyncRedis delete error: {e}")
            return False


def get_sync_redis_cache() -> SyncRedisCache:
    """从 settings 读取配置并返回 SyncRedisCache 实例。"""
    from app.settings import settings

    # 简单解析 redis://host:port/db 格式
    url = settings.redis_url
    host, port, db, password = "localhost", 6379, 0, None
    try:
        if url.startswith("redis://"):
            rest = url[8:]
            if "@" in rest:
                auth, rest = rest.split("@", 1)
                if ":" in auth:
                    password = auth.split(":", 1)[1]
            if "/" in rest:
                rest, db_str = rest.rsplit("/", 1)
                db = int(db_str)
            if ":" in rest:
                host, port_str = rest.rsplit(":", 1)
                port = int(port_str)
            else:
                host = rest
    except Exception as e:
        logger.warning(f"Failed to parse redis_url '{url}', using defaults: {e}")

    return SyncRedisCache(host=host, port=port, db=db, password=password)


def essay_cache_key(essay_text: str) -> str:
    """根据作文文本生成缓存 key。"""
    normalized = essay_text.strip().lower().replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"essay_result:{digest}"
