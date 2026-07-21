"""Neo4j 客户端"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import Neo4jError

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

    class Neo4jError(Exception):  # type: ignore[no-redef]
        pass


class Neo4jClient:
    """Neo4j 异步客户端"""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.driver: Any | None = None

    async def connect(self) -> "Neo4jClient":
        """建立连接"""
        if not NEO4J_AVAILABLE:
            return self
        self.driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
        )
        return self

    async def close(self) -> None:
        """关闭连接"""
        if self.driver:
            await self.driver.close()
            self.driver = None

    async def __aenter__(self) -> "Neo4jClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def create_word(
        self,
        word: str,
        phonetic: Optional[str] = None,
        meaning: Optional[str] = None,
        difficulty: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """创建词汇节点"""
        if not NEO4J_AVAILABLE or not self.driver:
            return False

        tags = tags or []

        query = """
        MERGE (w:Word {word: $word})
        ON CREATE SET
            w.phonetic = $phonetic,
            w.meaning = $meaning,
            w.difficulty = $difficulty,
            w.tags = $tags,
            w.created_at = datetime()
        RETURN w
        """

        try:
            async with self.driver.session() as session:
                await session.run(
                    query,
                    word=word,
                    phonetic=phonetic,
                    meaning=meaning,
                    difficulty=difficulty,
                    tags=tags,
                )
                return True
        except Exception as e:
            print(f"Neo4j error creating word: {e}")
            return False

    async def get_word(self, word: str) -> Optional[Dict[str, Any]]:
        """获取词汇信息"""
        if not NEO4J_AVAILABLE or not self.driver:
            return None

        query = """
        MATCH (w:Word {word: $word})
        RETURN w.word as word,
               COALESCE(w.phonetic, '') as phonetic,
               COALESCE(w.meaning, '') as meaning,
               COALESCE(w.difficulty, 1) as difficulty,
               COALESCE(w.tags, []) as tags
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(query, word=word)
                record = await result.single()
                return dict(record) if record else None
        except Exception:
            return None

    async def create_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        strength: float = 1.0,
    ) -> bool:
        """创建词汇关系"""
        if not NEO4J_AVAILABLE or not self.driver:
            return False

        await self.create_word(source)
        await self.create_word(target)

        query = f"""
        MATCH (a:Word {{word: $source}}), (b:Word {{word: $target}})
        MERGE (a)-[r:{relation_type.upper()}]->(b)
        ON CREATE SET r.strength = $strength, r.created_at = datetime()
        ON MATCH SET r.strength = $strength
        RETURN r
        """

        try:
            async with self.driver.session() as session:
                await session.run(
                    query,
                    source=source,
                    target=target,
                    strength=strength,
                )
                return True
        except Exception as e:
            print(f"Neo4j error creating relation: {e}")
            return False

    async def get_relations(
        self,
        word: str,
        relation_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取词汇关系"""
        if not NEO4J_AVAILABLE or not self.driver:
            return []

        if relation_type:
            query = f"""
            MATCH (w:Word {{word: $word}})-[r:{relation_type.upper()}]->(related:Word)
            RETURN related.word as word, COALESCE(r.strength, 1.0) as strength,
                   '{relation_type}' as relation_type
            LIMIT $limit
            """
        else:
            query = """
            MATCH (w:Word {word: $word})-[r]->(related:Word)
            RETURN related.word as word, COALESCE(r.strength, 1.0) as strength,
                   type(r) as relation_type
            LIMIT $limit
            """

        try:
            async with self.driver.session() as session:
                result = await session.run(query, word=word, limit=limit)
                records = await result.data()
                return records
        except Exception:
            return []

    async def get_antonyms(self, word: str) -> List[Dict[str, Any]]:
        """获取反义词"""
        return await self.get_relations(word, relation_type="antonym", limit=5)

    async def get_synonyms(self, word: str) -> List[Dict[str, Any]]:
        """获取同义词"""
        return await self.get_relations(word, relation_type="synonym", limit=5)

    async def get_cognates(self, word: str) -> List[Dict[str, Any]]:
        """获取同根词"""
        return await self.get_relations(word, relation_type="cognate", limit=5)

    async def init_schema(self) -> None:
        """初始化数据库Schema"""
        if not NEO4J_AVAILABLE or not self.driver:
            return

        queries = [
            "CREATE CONSTRAINT word_unique IF NOT EXISTS FOR (w:Word) REQUIRE w.word IS UNIQUE",
            "CREATE INDEX word_difficulty IF NOT EXISTS FOR (w:Word) ON (w.difficulty)",
        ]

        async with self.driver.session() as session:
            for query in queries:
                try:
                    await session.run(query)
                except Exception as e:
                    print(f"Schema init warning: {e}")


_neo4j_client: Neo4jClient | None = None


async def get_neo4j_client() -> Neo4jClient:
    """获取Neo4j客户端实例"""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient()
    return _neo4j_client
