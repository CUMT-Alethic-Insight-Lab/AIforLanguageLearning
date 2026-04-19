"""Analytics RAG storage backed by optional Elasticsearch."""

from __future__ import annotations

import logging
from typing import Any

try:
    from elasticsearch import AsyncElasticsearch
    ELASTICSEARCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    AsyncElasticsearch = Any  # type: ignore[assignment]
    ELASTICSEARCH_AVAILABLE = False

from .es_client import get_es_client

logger = logging.getLogger(__name__)

INDEX_NAME = "aifl_analytics_rag"

MAPPINGS: dict[str, Any] = {
    "properties": {
        "artifact_type": {"type": "keyword"},
        "scope": {"type": "keyword"},
        "class_id": {"type": "keyword"},
        "user_id": {"type": "keyword"},
        "agent_type": {"type": "keyword"},
        "title": {"type": "text"},
        "content": {"type": "text"},
        "tags": {"type": "keyword"},
        "created_at": {"type": "date"},
    }
}


async def ensure_analytics_rag_index(client: AsyncElasticsearch | None = None) -> bool:
    try:
        if not ELASTICSEARCH_AVAILABLE:
            return False
        if client is None:
            client = await get_es_client().connect()
        exists = await client.indices.exists(index=INDEX_NAME)
        if not exists:
            await client.indices.create(index=INDEX_NAME, mappings=MAPPINGS)
        return True
    except Exception as exc:  # pragma: no cover - network/dependency dependent
        logger.warning("analytics rag ensure_index failed: %s", exc)
        return False


async def index_analytics_document(
    doc: dict[str, Any],
    *,
    doc_id: str | None = None,
    client: AsyncElasticsearch | None = None,
) -> bool:
    try:
        if not ELASTICSEARCH_AVAILABLE:
            return False
        if client is None:
            client = await get_es_client().connect()
        await ensure_analytics_rag_index(client)
        await client.index(index=INDEX_NAME, id=doc_id, document=doc)
        return True
    except Exception as exc:  # pragma: no cover - network/dependency dependent
        logger.warning("analytics rag index failed: %s", exc)
        return False


async def search_analytics_documents(
    query: str,
    *,
    class_id: str | None = None,
    user_id: int | None = None,
    artifact_types: list[str] | None = None,
    size: int = 8,
    client: AsyncElasticsearch | None = None,
) -> list[dict[str, Any]]:
    try:
        if not ELASTICSEARCH_AVAILABLE:
            return []
        if client is None:
            client = await get_es_client().connect()
        should: list[dict[str, Any]] = [
            {"match": {"content": {"query": query, "boost": 2}}},
            {"match": {"title": {"query": query, "boost": 1.5}}},
        ]
        filters: list[dict[str, Any]] = []
        if class_id:
            filters.append({"term": {"class_id": class_id}})
        if user_id is not None:
            filters.append({"term": {"user_id": str(user_id)}})
        if artifact_types:
            filters.append({"terms": {"artifact_type": artifact_types}})

        resp = await client.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "should": should,
                    "filter": filters,
                    "minimum_should_match": 1,
                }
            },
            size=size,
        )
        return [
            {"score": hit.get("_score"), **(hit.get("_source") or {})}
            for hit in resp.get("hits", {}).get("hits", [])
        ]
    except Exception as exc:  # pragma: no cover - network/dependency dependent
        logger.warning("analytics rag search failed: %s", exc)
        return []
