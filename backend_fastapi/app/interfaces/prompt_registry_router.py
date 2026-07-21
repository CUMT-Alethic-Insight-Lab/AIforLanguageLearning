"""Prompt 资产管理 API 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..domain.prompt_management.service import PromptManager

router = APIRouter(prefix="/api/v1/prompts", tags=["Prompt Management"])


@router.post("", response_model=dict[str, Any])
def create_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """注册新 Prompt 版本。"""
    record = PromptManager.create_prompt(payload)
    return {
        "id": record.id,
        "prompt_key": record.prompt_key,
        "version": record.version,
        "created_at": record.created_at.isoformat(),
    }


@router.get("/{prompt_key}", response_model=dict[str, Any] | None)
def get_prompt(
    prompt_key: str,
    version: str | None = Query(None),
    ab_bucket: str = Query("default"),
) -> dict[str, Any] | None:
    """获取已发布的 Prompt 模板。"""
    record = PromptManager.get_prompt(prompt_key, version=version, ab_bucket=ab_bucket)
    if not record:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {
        "id": record.id,
        "prompt_key": record.prompt_key,
        "version": record.version,
        "system_prompt": record.system_prompt,
        "user_template": record.user_template,
        "variables": record.variables,
        "scene_type": record.scene_type,
        "model_hint": record.model_hint,
        "temperature": record.temperature,
        "max_tokens": record.max_tokens,
        "tags": record.tags,
        "metrics": record.metrics,
    }


@router.get("", response_model=list[dict[str, Any]])
def list_prompts(
    prompt_key: str | None = Query(None),
    scene_type: str | None = Query(None),
    tag: str | None = Query(None),
    published_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """列出 Prompt 模板。"""
    records = PromptManager.list_prompts(
        prompt_key=prompt_key,
        scene_type=scene_type,
        tag=tag,
        published_only=published_only,
        limit=limit,
    )
    return [
        {
            "id": r.id,
            "prompt_key": r.prompt_key,
            "version": r.version,
            "owner": r.owner,
            "ab_bucket": r.ab_bucket,
            "scene_type": r.scene_type,
            "is_published": r.is_published,
            "is_deprecated": r.is_deprecated,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.post("/{prompt_id}/publish", response_model=dict[str, Any])
def publish_prompt(prompt_id: int) -> dict[str, Any]:
    """发布 Prompt 版本。"""
    success = PromptManager.publish_prompt(prompt_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"prompt_id": prompt_id, "status": "published"}


@router.post("/{prompt_id}/deprecate", response_model=dict[str, Any])
def deprecate_prompt(prompt_id: int) -> dict[str, Any]:
    """废弃 Prompt 版本。"""
    success = PromptManager.deprecate_prompt(prompt_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"prompt_id": prompt_id, "status": "deprecated"}
