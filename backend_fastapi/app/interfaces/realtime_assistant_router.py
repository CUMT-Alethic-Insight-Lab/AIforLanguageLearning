"""实时助教 WebSocket 与 HTTP 路由。

基于 RealtimeAssistantSession 的完整业务链路：
- 屏幕帧 → 变化检测 → OCR → LLM 多模态 → TTS → 建议推送
- ASR 结果 → 主动建议检测 → LLM → TTS → 建议推送
- 显式请求 → LLM → TTS → 建议推送
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..domain.realtime_assistant import SessionManager
from ..settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/realtime-assistant", tags=["Real-time Assistant"])

# 全局会话管理器（单进程内有效；多进程需配合 Redis/共享存储）
_session_manager = SessionManager()


@router.websocket("/ws")
async def realtime_assistant_ws(websocket: WebSocket) -> None:
    """实时助教 WebSocket 通道。

    前端事件（JSON）：
    - {"type": "screen_frame", "image_base64": "...", "timestamp": 1234567890}
    - {"type": "mouse_lasso", "region": {"x1":0,"y1":0,"x2":100,"y2":100}, "image_base64": "..."}
    - {"type": "asr_result", "text": "...", "is_final": true, "timestamp": 1234567890}
    - {"type": "explicit_request", "text": "...", "image_base64": "..."}
    - {"type": "heartbeat"}

    后端响应：
    - {"type": "suggestion", "priority": "high|medium|low", "content": "...", "has_audio": true, "audio_base64": "...", "audio_format": "wav"}
    - {"type": "ack", "event_type": "..."}
    - {"type": "error", "message": "..."}
    """
    await websocket.accept()

    # 解析 user_id（与 /ws/v1 保持一致：query param）
    user_id_raw = websocket.query_params.get("user_id")
    user_id: int | None = None
    try:
        user_id = int(user_id_raw) if user_id_raw else None
    except ValueError:
        pass

    if user_id is None or user_id <= 0:
        await websocket.send_json({"type": "error", "message": "缺少有效的 user_id"})
        await websocket.close()
        return

    if not settings.rta_enabled:
        await websocket.send_json({"type": "error", "message": "实时助教功能已禁用"})
        await websocket.close()
        return

    username = websocket.query_params.get("username") or f"user_{user_id}"
    session = _session_manager.create_session(user_id, username)

    logger.info("RTA WebSocket connected user=%s", user_id)

    try:
        while True:
            message = await websocket.receive_text()
            _session_manager.record_message(user_id)

            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            response: dict[str, Any] | None = None

            if event_type == "screen_frame":
                image_base64 = event.get("image_base64", "")
                response = await session.on_screen_frame(image_base64)

            elif event_type == "mouse_lasso":
                region = event.get("region")
                image_base64 = event.get("image_base64")
                response = await session.on_mouse_lasso(region, image_base64)

            elif event_type == "asr_result":
                text = event.get("text", "")
                is_final = bool(event.get("is_final", False))
                response = await session.on_asr_result(text, is_final)

            elif event_type == "explicit_request":
                text = event.get("text", "")
                image_base64 = event.get("image_base64")
                response = await session.on_explicit_request(text, image_base64)

            elif event_type == "heartbeat":
                response = {"type": "ack", "event_type": "heartbeat"}

            else:
                # 透传未知事件（兼容未来扩展）
                response = {"type": "ack", "event_type": event_type}

            if response:
                await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("RTA WebSocket disconnected user=%s", user_id)
    except Exception as exc:
        logger.error("RTA WebSocket error user=%s: %s", user_id, exc, exc_info=True)
    finally:
        _session_manager.remove_session(user_id)
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/status", response_model=dict[str, Any])
def get_status() -> dict[str, Any]:
    """获取实时助教模块状态与活跃会话统计。"""
    stats = _session_manager.get_stats()
    return {
        "module": "realtime_assistant",
        "enabled": settings.rta_enabled,
        "status": "ready" if settings.rta_enabled else "disabled",
        "config": {
            "llm_model": settings.rta_llm_model,
            "cooldown_seconds": settings.rta_cooldown_seconds,
            "max_context_turns": settings.rta_max_context_turns,
            "tts_enabled": settings.rta_tts_enabled,
        },
        "sessions": stats,
    }
