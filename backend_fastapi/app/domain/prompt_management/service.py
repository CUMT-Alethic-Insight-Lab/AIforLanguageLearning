"""Prompt 资产管理服务层。"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from ...db import get_engine
from .models import PromptRegistry

logger = logging.getLogger(__name__)


class PromptManager:
    """Prompt 模板管理器。

    提供版本化 Prompt 的 CRUD 与运行时读取。
    服务层禁止硬编码 Prompt，只读取已发布版本。
    """

    @staticmethod
    def create_prompt(data: dict[str, Any]) -> PromptRegistry:
        """注册新 Prompt 版本。"""
        with Session(get_engine()) as session:
            # 默认新版本号自动递增（简化处理）
            prompt_key = data["prompt_key"]
            existing = session.exec(
                select(PromptRegistry)
                .where(PromptRegistry.prompt_key == prompt_key)
                .order_by(PromptRegistry.id.desc())
            ).first()
            version = data.get("version")
            if not version:
                if existing:
                    # 简单自增版本号
                    parts = existing.version.split(".")
                    try:
                        parts[-1] = str(int(parts[-1]) + 1)
                        version = ".".join(parts)
                    except ValueError:
                        version = existing.version + ".1"
                else:
                    version = "1.0.0"
                data["version"] = version

            record = PromptRegistry(**data)
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info("Created prompt %s version %s", prompt_key, version)
            return record

    @staticmethod
    def get_prompt(
        prompt_key: str,
        version: str | None = None,
        ab_bucket: str = "default",
    ) -> PromptRegistry | None:
        """读取已发布的 Prompt 模板。

        优先返回指定版本；若无，返回该 key + bucket 的最新已发布版本。
        """
        with Session(get_engine()) as session:
            if version:
                return session.exec(
                    select(PromptRegistry)
                    .where(PromptRegistry.prompt_key == prompt_key)
                    .where(PromptRegistry.version == version)
                    .where(PromptRegistry.is_published == True)
                    .where(PromptRegistry.is_deprecated == False)
                ).first()

            return session.exec(
                select(PromptRegistry)
                .where(PromptRegistry.prompt_key == prompt_key)
                .where(PromptRegistry.ab_bucket == ab_bucket)
                .where(PromptRegistry.is_published == True)
                .where(PromptRegistry.is_deprecated == False)
                .order_by(PromptRegistry.id.desc())
            ).first()

    @staticmethod
    def list_prompts(
        prompt_key: str | None = None,
        scene_type: str | None = None,
        tag: str | None = None,
        published_only: bool = True,
        limit: int = 50,
    ) -> list[PromptRegistry]:
        """列出 Prompt 模板。"""
        with Session(get_engine()) as session:
            stmt = select(PromptRegistry)
            if prompt_key:
                stmt = stmt.where(PromptRegistry.prompt_key == prompt_key)
            if scene_type:
                stmt = stmt.where(PromptRegistry.scene_type == scene_type)
            if published_only:
                stmt = stmt.where(PromptRegistry.is_published == True)
                stmt = stmt.where(PromptRegistry.is_deprecated == False)
            if tag:
                # 由于 JSON 数组查询在 SQLite/MySQL 中语法不同，这里做内存过滤
                results = list(session.exec(stmt.order_by(PromptRegistry.id.desc()).limit(limit * 2)))
                return [r for r in results if tag in (r.tags or [])][:limit]
            return list(session.exec(stmt.order_by(PromptRegistry.id.desc()).limit(limit)))

    @staticmethod
    def publish_prompt(prompt_id: int) -> bool:
        """发布 Prompt 版本。"""
        with Session(get_engine()) as session:
            record = session.get(PromptRegistry, prompt_id)
            if not record:
                return False
            record.is_published = True
            session.add(record)
            session.commit()
            return True

    @staticmethod
    def deprecate_prompt(prompt_id: int) -> bool:
        """废弃 Prompt 版本。"""
        with Session(get_engine()) as session:
            record = session.get(PromptRegistry, prompt_id)
            if not record:
                return False
            record.is_deprecated = True
            session.add(record)
            session.commit()
            return True

    @staticmethod
    def update_metrics(prompt_id: int, metrics: dict[str, Any]) -> bool:
        """更新 Prompt 质量指标（用于后续 A/B 分析）。"""
        with Session(get_engine()) as session:
            record = session.get(PromptRegistry, prompt_id)
            if not record:
                return False
            record.metrics = {**(record.metrics or {}), **metrics}
            session.add(record)
            session.commit()
            return True


# 快捷函数，供业务层直接调用
def get_published_prompt(
    prompt_key: str,
    version: str | None = None,
    ab_bucket: str = "default",
) -> PromptRegistry | None:
    return PromptManager.get_prompt(prompt_key, version=version, ab_bucket=ab_bucket)
