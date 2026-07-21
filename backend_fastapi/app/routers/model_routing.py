"""模型路由API - 模块E对外接口

提供场景扩写、模型配置、上下文管理等功能
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..model_router import (
    SceneType,
    chat_with_context,
    expand_scenario,
    get_model_router,
)
from ..runtime_config import get_runtime_config, update_runtime_config

router = APIRouter(prefix="/api/v1/model-routing", tags=["model-routing"])


# ========== 请求/响应模型 ==========

class ScenarioExpansionRequest(BaseModel):
    """场景扩写请求"""
    description: str = Field(..., min_length=1, max_length=500, description="用户场景描述")
    language: str = Field(default="en", description="目标语言")


class ScenarioExpansionResponse(BaseModel):
    """场景扩写响应"""
    success: bool
    expanded_scenario: str = Field(default="", description="扩写后的场景描述")
    system_prompt: str = Field(default="", description="可直接使用的System Prompt")


class ChatRequest(BaseModel):
    """对话请求"""
    conversation_id: str = Field(..., min_length=1, description="对话ID")
    message: str = Field(..., min_length=1, description="用户消息")
    session_id: str = Field(default="", description="会话ID")
    system_prompt: str = Field(default="", description="系统提示词")


class ModelConfigRequest(BaseModel):
    """模型配置请求"""
    scene: str = Field(..., description="场景类型 (chat/vocab/essay/scenario_expansion)")
    model_id: str = Field(..., description="模型ID")


class ModelConfigResponse(BaseModel):
    """模型配置响应"""
    success: bool
    scene: str
    model_id: str


class RoutingStatusResponse(BaseModel):
    """路由状态响应"""
    scenes: dict[str, dict[str, Any]] = Field(default_factory=dict, description="场景到实际主路由与fallback链的映射")
    endpoints: dict[str, list[dict[str, Any]]] = Field(default_factory=dict, description="可用端点")


class ContextClearRequest(BaseModel):
    """清除上下文请求"""
    conversation_id: str = Field(..., description="要清除的对话ID")


class ContextClearResponse(BaseModel):
    """清除上下文响应"""
    success: bool
    conversation_id: str


# ========== API端点 ==========

@router.post("/expand-scenario", response_model=ScenarioExpansionResponse)
async def api_expand_scenario(req: ScenarioExpansionRequest) -> ScenarioExpansionResponse:
    """
    场景扩写API
    
    将用户的简短场景描述扩写为详细的口语练习场景设定。
    使用Kimi API进行扩写，输出可直接作为Qwen对话的System Prompt。
    """
    try:
        expanded = await expand_scenario(req.description, req.language)
        return ScenarioExpansionResponse(
            success=True,
            expanded_scenario=expanded,
            system_prompt=expanded  # 扩写结果可直接作为system prompt
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"场景扩写失败: {str(e)}")


@router.post("/chat")
async def api_chat(req: ChatRequest):
    """
    流式对话API
    
    带上下文管理的对话接口，使用本地Qwen模型。
    自动维护对话历史，支持Token超限压缩。
    """
    from fastapi.responses import StreamingResponse
    
    async def generate():
        try:
            async for chunk in chat_with_context(
                conversation_id=req.conversation_id,
                user_message=req.message,
                session_id=req.session_id,
                system_prompt=req.system_prompt
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/status", response_model=RoutingStatusResponse)
async def api_routing_status() -> RoutingStatusResponse:
    """
    获取路由状态
    
    返回当前场景到模型的映射配置和可用端点信息。
    """
    router = get_model_router()
    # 获取端点信息（脱敏）
    endpoints_info = {}
    for provider, eps in router._endpoints.items():
        endpoints_info[provider.value] = [
            {
                "base_url": ep.base_url,
                "model_id": ep.model_id,
                "priority": ep.priority,
                # 不返回api_key
            }
            for ep in eps
        ]

    scene_status: dict[str, dict[str, Any]] = {}
    for scene in SceneType:
        decision = router.route(scene)
        scene_status[scene.value] = {
            "provider": decision.primary_endpoint.provider.value,
            "model_id": decision.primary_endpoint.model_id,
            "fallbacks": [
                {
                    "provider": ep.provider.value,
                    "model_id": ep.model_id,
                }
                for ep in decision.fallback_endpoints
            ],
        }
    
    return RoutingStatusResponse(
        scenes=scene_status,
        endpoints=endpoints_info
    )


@router.post("/config", response_model=ModelConfigResponse)
async def api_set_model_config(req: ModelConfigRequest) -> ModelConfigResponse:
    """
    设置场景模型配置
    
    为特定场景指定使用的模型。
    """
    # 验证场景类型
    try:
        SceneType(req.scene)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的场景类型: {req.scene}")
    
    # 更新运行时配置
    current = get_runtime_config()
    scene_models = current.get("models", {}).get("scene", {})
    scene_models[req.scene] = req.model_id
    
    update_runtime_config({
        "models": {
            "scene": scene_models
        }
    })
    
    return ModelConfigResponse(
        success=True,
        scene=req.scene,
        model_id=req.model_id
    )


@router.post("/context/clear", response_model=ContextClearResponse)
async def api_clear_context(req: ContextClearRequest) -> ContextClearResponse:
    """
    清除对话上下文
    
    清除指定对话ID的上下文缓存。
    """
    router = get_model_router()
    router.clear_context(req.conversation_id)
    
    return ContextClearResponse(
        success=True,
        conversation_id=req.conversation_id
    )


@router.get("/context/{conversation_id}")
async def api_get_context(conversation_id: str) -> dict[str, Any]:
    """
    获取对话上下文
    
    返回指定对话的当前上下文状态（用于调试）。
    """
    router = get_model_router()
    context = router._contexts.get(conversation_id)
    
    if not context:
        raise HTTPException(status_code=404, detail="对话上下文不存在")
    
    return {
        "conversation_id": context.conversation_id,
        "session_id": context.session_id,
        "message_count": len(context.messages),
        "total_tokens": context.get_total_tokens(),
        "should_compress": context.should_compress(),
        "messages": [
            {"role": m.role, "content": m.content[:100] + "..." if len(m.content) > 100 else m.content}
            for m in context.messages
        ]
    }
