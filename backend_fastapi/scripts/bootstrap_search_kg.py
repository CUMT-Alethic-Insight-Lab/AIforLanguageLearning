"""批量初始化 ES 和 Neo4j 基础数据

用法:
    cd backend_fastapi
    .venv\Scripts\python.exe scripts/bootstrap_search_kg.py

功能:
1. 向 ES `aifl_vocabulary` 索引灌入 50+ 基础英语词汇
2. 向 Neo4j 导入词汇节点和基础关系（同义、反义、上位词）
"""

from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(0, "")  # allow imports from backend_fastapi root

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 基础词汇数据（50 个高频词，覆盖 A1-B1 级别）
# ---------------------------------------------------------------------------
BASE_VOCAB: list[dict] = [
    {"word": "hello", "definition": "问候语，用于见面或打电话时打招呼", "language": "en", "tags": ["greeting", "A1"]},
    {"word": "world", "definition": "世界；地球；全人类", "language": "en", "tags": ["noun", "A1"]},
    {"word": "apple", "definition": "苹果；苹果树", "language": "en", "tags": ["fruit", "noun", "A1"]},
    {"word": "book", "definition": "书；书籍；本子", "language": "en", "tags": ["noun", "A1"]},
    {"word": "water", "definition": "水；水域；海水", "language": "en", "tags": ["noun", "A1"]},
    {"word": "happy", "definition": "快乐的；幸福的；满意的", "language": "en", "tags": ["adjective", "A1", "emotion"]},
    {"word": "good", "definition": "好的；优秀的；有益的", "language": "en", "tags": ["adjective", "A1"]},
    {"word": "bad", "definition": "坏的；糟糕的；有害的", "language": "en", "tags": ["adjective", "A1"]},
    {"word": "big", "definition": "大的；重要的；成功的", "language": "en", "tags": ["adjective", "A1"]},
    {"word": "small", "definition": "小的；少的；不重要的", "language": "en", "tags": ["adjective", "A1"]},
    {"word": "run", "definition": "跑；奔跑；经营", "language": "en", "tags": ["verb", "A1"]},
    {"word": "walk", "definition": "走；步行；散步", "language": "en", "tags": ["verb", "A1"]},
    {"word": "eat", "definition": "吃；吃饭；侵蚀", "language": "en", "tags": ["verb", "A1"]},
    {"word": "drink", "definition": "喝；饮；喝酒", "language": "en", "tags": ["verb", "A1"]},
    {"word": "read", "definition": "读；阅读；理解", "language": "en", "tags": ["verb", "A1"]},
    {"word": "write", "definition": "写；写作；填写", "language": "en", "tags": ["verb", "A1"]},
    {"word": "speak", "definition": "说；讲；发言", "language": "en", "tags": ["verb", "A1"]},
    {"word": "listen", "definition": "听；倾听；听信", "language": "en", "tags": ["verb", "A1"]},
    {"word": "see", "definition": "看见；看到；理解", "language": "en", "tags": ["verb", "A1"]},
    {"word": "look", "definition": "看；看起来；注视", "language": "en", "tags": ["verb", "A1"]},
    {"word": "know", "definition": "知道；认识；了解", "language": "en", "tags": ["verb", "A1"]},
    {"word": "think", "definition": "想；思考；认为", "language": "en", "tags": ["verb", "A1"]},
    {"word": "make", "definition": "做；制造；使成为", "language": "en", "tags": ["verb", "A1"]},
    {"word": "take", "definition": "拿；取；花费", "language": "en", "tags": ["verb", "A1"]},
    {"word": "come", "definition": "来；来到；到达", "language": "en", "tags": ["verb", "A1"]},
    {"word": "go", "definition": "去；走；变得", "language": "en", "tags": ["verb", "A1"]},
    {"word": "get", "definition": "得到；获得；变成", "language": "en", "tags": ["verb", "A1"]},
    {"word": "give", "definition": "给；给予；赠送", "language": "en", "tags": ["verb", "A1"]},
    {"word": "find", "definition": "找到；发现；感到", "language": "en", "tags": ["verb", "A1"]},
    {"word": "tell", "definition": "告诉；说；吩咐", "language": "en", "tags": ["verb", "A1"]},
    {"word": "ask", "definition": "问；询问；请求", "language": "en", "tags": ["verb", "A1"]},
    {"word": "work", "definition": "工作；运作；起作用", "language": "en", "tags": ["verb", "A1"]},
    {"word": "play", "definition": "玩；演奏；扮演", "language": "en", "tags": ["verb", "A1"]},
    {"word": "help", "definition": "帮助；援助；有助于", "language": "en", "tags": ["verb", "A1"]},
    {"word": "show", "definition": "展示；显示；表明", "language": "en", "tags": ["verb", "A1"]},
    {"word": "try", "definition": "尝试；努力；试用", "language": "en", "tags": ["verb", "A1"]},
    {"word": "need", "definition": "需要；必须；需求", "language": "en", "tags": ["verb", "A1"]},
    {"word": "feel", "definition": "感觉；觉得；触摸", "language": "en", "tags": ["verb", "A1"]},
    {"word": "become", "definition": "变成；成为；适合", "language": "en", "tags": ["verb", "A2"]},
    {"word": "leave", "definition": "离开；留下；遗留", "language": "en", "tags": ["verb", "A2"]},
    {"word": "put", "definition": "放；放置；写下", "language": "en", "tags": ["verb", "A1"]},
    {"word": "mean", "definition": "意思是；意味着；打算", "language": "en", "tags": ["verb", "A1"]},
    {"word": "keep", "definition": "保持；保留；继续", "language": "en", "tags": ["verb", "A2"]},
    {"word": "let", "definition": "让；允许；出租", "language": "en", "tags": ["verb", "A1"]},
    {"word": "begin", "definition": "开始；启动；起源于", "language": "en", "tags": ["verb", "A1"]},
    {"word": "seem", "definition": "似乎；好像；看起来", "language": "en", "tags": ["verb", "A2"]},
    {"word": "talk", "definition": "说话；交谈；讨论", "language": "en", "tags": ["verb", "A1"]},
    {"word": "turn", "definition": "转动；转向；变成", "language": "en", "tags": ["verb", "A1"]},
    {"word": "start", "definition": "开始；启动；创办", "language": "en", "tags": ["verb", "A1"]},
    {"word": "show", "definition": "展示；显示；演出", "language": "en", "tags": ["verb", "A1"]},
    {"word": "hear", "definition": "听见；听说；审理", "language": "en", "tags": ["verb", "A1"]},
]

# ---------------------------------------------------------------------------
# Neo4j 关系数据（同义、反义、上位词）
# ---------------------------------------------------------------------------
WORD_RELATIONS: list[tuple[str, str, str]] = [
    ("hello", "hi", "SYNONYM"),
    ("happy", "glad", "SYNONYM"),
    ("big", "large", "SYNONYM"),
    ("small", "little", "SYNONYM"),
    ("good", "bad", "ANTONYM"),
    ("big", "small", "ANTONYM"),
    ("happy", "sad", "ANTONYM"),
    ("run", "walk", "ANTONYM"),
    ("apple", "fruit", "HYPERNYM"),
    ("book", "read", "RELATED_TO"),
    ("water", "drink", "RELATED_TO"),
    ("speak", "talk", "SYNONYM"),
    ("see", "look", "SYNONYM"),
    ("begin", "start", "SYNONYM"),
    ("make", "create", "SYNONYM"),
]


async def bootstrap_es() -> int:
    """向 ES 灌入基础词汇。返回成功数。"""
    from app.infrastructure.persistence.search.es_client import (
        ensure_index,
        get_es_client,
        index_document,
    )

    client = await get_es_client().connect()
    await ensure_index(client)

    ok = 0
    for doc in BASE_VOCAB:
        word = doc["word"]
        if await index_document(doc, doc_id=word, client=client):
            ok += 1
            logger.info(f"  ES indexed: {word}")
        else:
            logger.warning(f"  ES failed: {word}")

    await get_es_client().close()
    logger.info(f"ES bootstrap finished: {ok}/{len(BASE_VOCAB)} documents indexed")
    return ok


async def bootstrap_neo4j() -> tuple[int, int]:
    """向 Neo4j 导入词汇节点和关系。返回 (节点数, 关系数)。"""
    from app.domain.knowledge_graph.client import Neo4jClient

    # Neo4j 社区版 5.15 已关闭认证
    neo = Neo4jClient("bolt://localhost:7687", "neo4j", "")
    await neo.connect()
    await neo.init_schema()

    nodes_ok = 0
    for doc in BASE_VOCAB:
        word = doc["word"]
        try:
            await neo.create_word(word)
            nodes_ok += 1
            logger.info(f"  Neo4j node created: {word}")
        except Exception as e:
            logger.warning(f"  Neo4j node failed: {word} ({e})")

    rels_ok = 0
    for source, target, rel_type in WORD_RELATIONS:
        try:
            await neo.create_relation(source, target, rel_type)
            rels_ok += 1
            logger.info(f"  Neo4j relation: {source}-[{rel_type}]->{target}")
        except Exception as e:
            logger.warning(f"  Neo4j relation failed: {source}-[{rel_type}]->{target} ({e})")

    await neo.close()
    logger.info(f"Neo4j bootstrap finished: {nodes_ok} nodes, {rels_ok} relations")
    return nodes_ok, rels_ok


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Bootstrapping ES + Neo4j with base vocabulary")
    logger.info("=" * 50)

    es_ok = await bootstrap_es()
    neo_nodes, neo_rels = await bootstrap_neo4j()

    logger.info("=" * 50)
    logger.info(f"Summary: ES={es_ok} docs, Neo4j={neo_nodes} nodes + {neo_rels} relations")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
