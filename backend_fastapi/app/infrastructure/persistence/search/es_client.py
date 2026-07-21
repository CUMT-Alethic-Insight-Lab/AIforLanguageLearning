"""Elasticsearch 异步客户端封装"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from elasticsearch import AsyncElasticsearch
    ELASTICSEARCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    AsyncElasticsearch = Any  # type: ignore[assignment]
    ELASTICSEARCH_AVAILABLE = False

logger = logging.getLogger(__name__)

INDEX_NAME = "aifl_vocabulary"

MAPPINGS: dict[str, Any] = {
    "properties": {
        "word": {
            "type": "text",
            "analyzer": "standard",
            "fields": {"keyword": {"type": "keyword"}},
        },
        "definition": {"type": "text"},
        "language": {"type": "keyword"},
        "tags": {"type": "keyword"},
    }
}


class ESClient:
    """Elasticsearch 客户端管理器"""

    def __init__(self, hosts: list[str] | None = None):
        self.hosts = hosts or ["http://localhost:9200"]
        self._client: AsyncElasticsearch | None = None
        self._loop_id: int | None = None

    async def connect(self) -> AsyncElasticsearch:
        if not ELASTICSEARCH_AVAILABLE:
            raise RuntimeError("elasticsearch package is not installed")
        current_loop_id = id(asyncio.get_running_loop())
        if self._client is None or self._loop_id != current_loop_id:
            if self._client is not None:
                try:
                    await self._client.close()
                except Exception:
                    pass
            self._client = AsyncElasticsearch(
                self.hosts,
                request_timeout=2,
                retry_on_timeout=False,
                max_retries=0,
            )
            self._loop_id = current_loop_id
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._loop_id = None

    @property
    def client(self) -> AsyncElasticsearch | None:
        return self._client


_es_client: ESClient | None = None


def get_es_client() -> ESClient:
    global _es_client
    if _es_client is None:
        _es_client = ESClient()
    return _es_client


async def ensure_index(client: AsyncElasticsearch | None = None) -> bool:
    """检查并创建 vocabulary 索引"""
    try:
        if client is None:
            client = (await get_es_client().connect())
        exists = await client.indices.exists(index=INDEX_NAME)
        if not exists:
            await client.indices.create(index=INDEX_NAME, mappings=MAPPINGS)
            logger.info(f"Created ES index: {INDEX_NAME}")
        return True
    except Exception as e:
        logger.error(f"ES ensure_index error: {e}")
        return False


async def index_document(
    doc: dict[str, Any],
    doc_id: str | None = None,
    client: AsyncElasticsearch | None = None,
) -> bool:
    """索引单个文档"""
    try:
        if client is None:
            client = (await get_es_client().connect())
        await client.index(index=INDEX_NAME, id=doc_id, document=doc)
        return True
    except Exception as e:
        logger.error(f"ES index_document error: {e}")
        return False


async def search_vocabulary(
    query: str,
    fuzzy: bool = True,
    size: int = 20,
    client: AsyncElasticsearch | None = None,
) -> list[dict[str, Any]]:
    """词汇全文搜索"""
    try:
        if client is None:
            client = (await get_es_client().connect())
        q: dict[str, Any] = {
            "multi_match": {
                "query": query,
                "fields": ["word^3", "definition", "tags"],
                "fuzziness": "AUTO" if fuzzy else "0",
            }
        }
        resp = await client.search(index=INDEX_NAME, query=q, size=size)
        return [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.error(f"ES search_vocabulary error: {e}")
        return []
