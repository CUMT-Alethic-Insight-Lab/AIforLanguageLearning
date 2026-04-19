from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, col, select

from .application.db_learning import create_record
from .db import get_engine, init_db
from .domain import models as _domain_models  # noqa: F401  # registers new tables
from .infrastructure.telemetry.metrics import get_metrics_collector, get_metrics_response
from .infrastructure.telemetry.tracing import TraceMiddleware, get_request_id, get_trace_id
from .interfaces.admin_router import router as admin_router
from .interfaces.auth_router import router as auth_router
from .interfaces.knowledge_graph_router import router as knowledge_graph_router
from .interfaces.analytics_router import router as analytics_router
from .interfaces.prompt_registry_router import router as prompt_registry_router
from .interfaces.realtime_assistant_router import router as realtime_assistant_router
from .interfaces.storage_router import router as storage_router
from .interfaces.tasks_router import router as tasks_router
from .llm import chat_complete, stream_chat
from .logging import configure_logging
from .models import (
    ConversationEvent,
    EssayResult,
    EssaySubmission,
    UserVocabQuery,
)
from .runtime_config import get_runtime_config
from .routers.compat_legacy import router as compat_legacy_router
from .routers.essays import router as essays_router
from .routers.learning import router as learning_router
from .routers.model_routing import router as model_routing_router
from .routers.system import router as system_router
from .routers.vocab import _resolve_lookup_payload, router as vocab_router
from .routers.voice import router as voice_router
from .settings import settings
from .tts import synthesize_tts_wav
from .voice_stream import (
    VoiceStream,
    VoiceStreamConfig,
    try_create_seamless_transcriber,
)

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 确保 sqlite 文件目录存在（默认 ./data/app.db）
    if settings.database_url.startswith("sqlite:///./"):
        db_rel = settings.database_url.removeprefix("sqlite:///./")
        db_dir = os.path.dirname(db_rel)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    init_db()
    yield


app = FastAPI(title="AIFL Backend (FastAPI)", lifespan=lifespan)

# Allow browser-based dev clients (Vite) and Electron renderer (Origin: null) to call the API.
# Without this, `npm run dev` will fail on CORS preflight for endpoints like `/api/voice/generate-prompt`.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8011",
        "http://127.0.0.1:8011",
        "null",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vocab_router)
app.include_router(essays_router)
app.include_router(voice_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(system_router)
app.include_router(learning_router)
app.include_router(model_routing_router)
app.include_router(knowledge_graph_router)
app.include_router(storage_router)
app.include_router(tasks_router)
app.include_router(analytics_router)
app.include_router(prompt_registry_router)
app.include_router(realtime_assistant_router)
if bool(getattr(settings, "enable_legacy_compat_api", True)):
    app.include_router(compat_legacy_router)


async def telemetry_middleware(request, call_next):
    tracer = TraceMiddleware()
    await tracer.process_request(request)
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    metrics = get_metrics_collector()
    metrics.increment_request_count(request.method, request.url.path, response.status_code)
    metrics.observe_request_latency(request.method, request.url.path, duration_ms)
    response.headers["X-Trace-Id"] = get_trace_id()
    response.headers["X-Request-Id"] = get_request_id()
    return response


app.middleware("http")(telemetry_middleware)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "env": settings.app_env}


@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response

    data, content_type = get_metrics_response()
    return Response(content=data, media_type=content_type)


@app.websocket("/ws/v1")
async def ws_v1(ws: WebSocket) -> None:
    await ws.accept()

    INTERNAL_PERSIST_ONLY_TYPES = {"USER_MESSAGE", "AI_MESSAGE"}

    session_id = ws.query_params.get("session_id") or "anonymous"
    conversation_id = ws.query_params.get("conversation_id") or f"conv_{uuid.uuid4().hex[:8]}"
    user_id_raw = ws.query_params.get("user_id")
    session_user_id: int | None
    try:
        session_user_id = int(user_id_raw) if user_id_raw is not None else None
        if session_user_id is not None and session_user_id <= 0:
            session_user_id = None
    except ValueError:
        session_user_id = None
    session_language = ""
    session_scenario = ""

    last_seq_raw = ws.query_params.get("last_seq")
    last_seq: int | None
    try:
        last_seq = int(last_seq_raw) if last_seq_raw is not None else None
    except ValueError:
        last_seq = None

    # seq 以 conversation_events 为准：全局（conversation_id 内）严格递增
    with Session(get_engine()) as session:
        max_seq = session.exec(
            select(ConversationEvent.seq)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(col(ConversationEvent.seq).desc())
        ).first()
    seq = int(max_seq or 0)

    async def send_event(
        event_type: str,
        payload: dict,
        *,
        request_id: str = "ws",
        final: bool = False,
        log: bool = True,
        ts: int = 0,
        force_seq: int | None = None,
    ) -> None:
        nonlocal seq

        if force_seq is not None:
            msg_seq = force_seq
        else:
            seq += 1
            msg_seq = seq

        msg: dict = {
            "type": event_type,
            "seq": msg_seq,
            "ts": ts,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "payload": payload,
        }
        if final:
            msg["final"] = True

        await ws.send_json(msg)

        if log:
            with Session(get_engine()) as session:
                session.add(
                    ConversationEvent(
                        user_id=session_user_id,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        seq=msg_seq,
                        type=event_type,
                        ts=ts,
                        request_id=request_id,
                        final=bool(final),
                        payload=payload,
                    )
                )
                session.commit()

    async def persist_event_only(
        event_type: str,
        payload: dict,
        *,
        request_id: str = "ws",
        final: bool = False,
        ts: int = 0,
    ) -> None:
        """Persist an event without sending it to websocket clients."""

        nonlocal seq

        seq += 1
        msg_seq = seq

        with Session(get_engine()) as session:
            session.add(
                ConversationEvent(
                    user_id=session_user_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    seq=msg_seq,
                    type=event_type,
                    ts=ts,
                    request_id=request_id,
                    final=bool(final),
                    payload=payload,
                )
            )
            session.commit()

    def get_latest_system_prompt() -> str:
        try:
            with Session(get_engine()) as session:
                evt = session.exec(
                    select(ConversationEvent)
                    .where(ConversationEvent.conversation_id == conversation_id)
                    .where(ConversationEvent.type == "CONTEXT_SET")
                    .order_by(col(ConversationEvent.seq).desc())
                ).first()
                if evt is None:
                    return ""
                payload = dict(evt.payload or {})
                sp = payload.get("system_prompt") or payload.get("systemPrompt")
                return str(sp or "")
        except Exception:
            return ""

    def get_latest_context_memory() -> str:
        try:
            with Session(get_engine()) as session:
                evt = session.exec(
                    select(ConversationEvent)
                    .where(ConversationEvent.conversation_id == conversation_id)
                    .where(ConversationEvent.type == "CONTEXT_MEMORY")
                    .order_by(col(ConversationEvent.seq).desc())
                ).first()
                if evt is None:
                    return ""
                payload = dict(evt.payload or {})
                return str(payload.get("memory") or "").strip()
        except Exception:
            return ""

    async def patch_context_memory(*, op: str, text: str, request_id: str) -> str:
        """修改持久化的对话上下文记忆。

        op:
        - append: 追加
        - replace: 覆盖
        - clear: 清空
        """

        current = get_latest_context_memory()
        note = (text or "").strip()
        action = (op or "append").strip().lower()

        if action == "clear":
            merged = ""
        elif action == "replace":
            merged = note
        else:
            merged = (f"{current}\n{note}" if current and note else (note or current)).strip()

        # 防止无限增长：仅保留末尾 2400 字符。
        if len(merged) > 2400:
            merged = merged[-2400:]

        await send_event(
            "CONTEXT_MEMORY",
            {"memory": merged, "op": action},
            request_id=request_id,
            ts=int(time.time() * 1000),
            final=False,
            log=True,
        )
        return merged

    def get_all_chat_history_from_events(*, exclude_request_id: str) -> list[dict[str, str]]:
        """按 seq 升序组装会话历史（优先 USER_MESSAGE / AI_MESSAGE）。"""
        try:
            with Session(get_engine()) as session:
                rows = session.exec(
                    select(ConversationEvent)
                    .where(ConversationEvent.conversation_id == conversation_id)
                    .where(
                        col(ConversationEvent.type).in_(
                            ["USER_MESSAGE", "AI_MESSAGE", "ASR_FINAL", "LLM_RESULT"]
                        )
                    )
                    .order_by(col(ConversationEvent.seq).asc())
                ).all()
        except Exception:
            return []

        messages: list[dict[str, str]] = []
        user_message_request_ids: set[str] = set()
        ai_message_request_ids: set[str] = set()

        for row in rows:
            req_id = str(row.request_id or "")
            if req_id == exclude_request_id:
                continue

            payload = dict(row.payload or {})

            if row.type == "USER_MESSAGE":
                text = str(payload.get("text") or "").strip()
                if text:
                    messages.append({"role": "user", "content": text})
                if req_id:
                    user_message_request_ids.add(req_id)
                continue

            if row.type == "AI_MESSAGE":
                text = str(payload.get("text") or payload.get("markdown") or "").strip()
                if text:
                    messages.append({"role": "assistant", "content": text})
                if req_id:
                    ai_message_request_ids.add(req_id)
                continue

            # 兼容旧历史：当未落 USER_MESSAGE/AI_MESSAGE 时，回退到 ASR_FINAL/LLM_RESULT。
            if row.type == "ASR_FINAL":
                if req_id and req_id in user_message_request_ids:
                    continue
                text = str(payload.get("text") or "").strip()
                if text:
                    messages.append({"role": "user", "content": text})
            elif row.type == "LLM_RESULT":
                if req_id and req_id in ai_message_request_ids:
                    continue
                text = str(payload.get("markdown") or payload.get("text") or "").strip()
                if text:
                    messages.append({"role": "assistant", "content": text})

        return messages

    # 重连恢复：先重放遗漏事件，再继续处理后续消息
    if last_seq is not None:
        with Session(get_engine()) as session:
            rows = session.exec(
                select(ConversationEvent)
                .where(ConversationEvent.conversation_id == conversation_id)
                .where(ConversationEvent.seq > last_seq)
                .order_by(col(ConversationEvent.seq).asc())
            ).all()

        for row in rows:
            if str(row.type or "") in INTERNAL_PERSIST_ONLY_TYPES:
                continue
            await send_event(
                row.type,
                dict(row.payload or {}),
                request_id=row.request_id,
                final=bool(row.final),
                log=False,
                ts=int(row.ts),
                force_seq=int(row.seq),
            )
    else:
        await send_event("TASK_STARTED", {"message": "connected"})

    try:
        voice_streams: dict[str, VoiceStream] = {}
        voice_last_activity_ms: dict[str, int] = {}
        voice_partial_tasks: dict[str, asyncio.Task[None]] = {}
        voice_asr_only: dict[str, bool] = {}
        voice_finalize_tasks: dict[str, asyncio.Task[None]] = {}
        voice_completed: set[str] = set()
        voice_aborted: set[str] = set()

        # 记录每个 request 的回复文本与 TTS 已播报进度，用于“打断续接上下文”。
        voice_reply_text: dict[str, str] = {}
        voice_tts_total_bytes: dict[str, int] = {}
        voice_tts_sent_bytes: dict[str, int] = {}
        voice_tts_sent_chunks: dict[str, int] = {}
        voice_audio_bytes: dict[str, int] = {}
        voice_request_started_ms: dict[str, int] = {}
        voice_user_message_ts_ms: dict[str, int] = {}

        voice_cloud_model = "moonshot-v1-auto"
        voice_local_model = "qwen3.5-9b"
        runtime_cfg = get_runtime_config()
        kimi_cfg = runtime_cfg.get("kimi", {}) if isinstance(runtime_cfg, dict) else {}
        voice_cloud_base_url = str(
            (kimi_cfg.get("base_url") if isinstance(kimi_cfg, dict) else "")
            or os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
        ).strip()
        voice_cloud_api_key = str(
            (kimi_cfg.get("api_key") if isinstance(kimi_cfg, dict) else "")
            or os.getenv("KIMI_API_KEY", "")
        ).strip()

        pending_binary_chunk_for: str | None = None
        asr_transcriber = None
        if settings.enable_asr:
            preferred = str(settings.asr_backend or "").strip() or "seamless"

            if preferred == "seamless":
                asr_transcriber = try_create_seamless_transcriber(
                    model_name=settings.asr_model,
                    device=settings.asr_device,
                    compute_type=settings.asr_compute_type,
                )

            # If ASR is enabled but no backend is available, provide a clear degraded transcriber.
            if asr_transcriber is None:
                def _asr_unavailable(_audio: bytes, _cfg: "VoiceStreamConfig") -> str:
                    return "（ASR 已启用，但当前 Python 环境未安装 ASR 后端依赖：请安装 transformers + torchaudio 以使用 SeamlessM4T）"

                asr_transcriber = _asr_unavailable

        async def _collect_model_reply(
            *,
            request_id: str,
            system_prompt: str,
            user_prompt: str,
            history: list[dict[str, str]],
            source: str,
            model: str,
            emit_tokens: bool = False,
        ) -> dict[str, object]:
            parts: list[str] = []
            endpoint_base_url: str | None = None
            endpoint_api_key: str | None = None
            started_ms = int(time.time() * 1000)
            first_token_latency_ms: int | None = None
            token_count = 0
            if source == "cloud":
                endpoint_base_url = voice_cloud_base_url
                endpoint_api_key = voice_cloud_api_key or None

            try:
                try:
                    stream_iter = stream_chat(
                        system_prompt=system_prompt,
                        user_text=user_prompt,
                        history=history,
                        model=model,
                        base_url=endpoint_base_url,
                        api_key=endpoint_api_key,
                    )
                except TypeError:
                    # 兼容测试里的 monkeypatch（不带 model 参数）。
                    stream_iter = stream_chat(
                        system_prompt=system_prompt,
                        user_text=user_prompt,
                        history=history,
                    )

                async for delta in stream_iter:
                    if request_id in voice_aborted:
                        raise asyncio.CancelledError()
                    if first_token_latency_ms is None:
                        first_token_latency_ms = max(0, int(time.time() * 1000) - started_ms)
                    parts.append(delta)
                    token_count += 1
                    if emit_tokens and delta:
                        await send_event(
                            "LLM_TOKEN",
                            {"text": delta, "source": source, "model": model},
                            request_id=request_id,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                parts = []

            if parts:
                text = ("".join(parts)).strip() or "（LLM 输出为空）"
            else:
                try:
                    try:
                        text = await chat_complete(
                            system_prompt=system_prompt,
                            user_text=user_prompt,
                            history=history,
                            model=model,
                            base_url=endpoint_base_url,
                            api_key=endpoint_api_key,
                        )
                    except TypeError:
                        text = await chat_complete(
                            system_prompt=system_prompt,
                            user_text=user_prompt,
                            history=history,
                        )
                except Exception:
                    text = "（网络不太稳定，请稍后再试）"

            degraded_markers = {"（网络不太稳定，请稍后再试）", "（LLM 输出为空）"}
            success = bool(str(text).strip()) and text not in degraded_markers

            return {
                "text": text,
                "source": source,
                "model": model,
                "success": success,
                "token_count": token_count,
                "first_token_latency_ms": first_token_latency_ms,
                "llm_generation_ms": max(0, int(time.time() * 1000) - started_ms),
            }

        async def _stream_chat_with_fallback(
            *,
            request_id: str,
            system_prompt: str,
            user_prompt: str,
            history: list[dict[str, str]],
        ) -> dict[str, object]:
            candidates: list[tuple[str, str]] = []
            if voice_cloud_api_key:
                candidates.append(("cloud", voice_cloud_model))
            candidates.append(("local", voice_local_model))

            # 只有一方可用时直接调用（保持流式）
            if len(candidates) == 1:
                return await _collect_model_reply(
                    request_id=request_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    history=history,
                    source=candidates[0][0],
                    model=candidates[0][1],
                    emit_tokens=True,
                )

            # 竞速：同时启动两方（不发 token，只收集结果）
            async def _race_task(source: str, model: str) -> dict[str, object]:
                return await _collect_model_reply(
                    request_id=request_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    history=history,
                    source=source,
                    model=model,
                    emit_tokens=False,
                )

            tasks = {
                asyncio.create_task(_race_task(source, model)): (source, model)
                for source, model in candidates
            }

            winner_result: dict[str, object] | None = None
            winner_source = "local"
            winner_model = voice_local_model

            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            for task in done:
                try:
                    result = task.result()
                    if bool(result.get("success", False)) or int(result.get("token_count", 0) or 0) > 0:
                        winner_result = result
                        winner_source, winner_model = tasks[task]
                        break
                except Exception:
                    continue

            # 若先完成的都失败，尝试等待其余任务
            if winner_result is None:
                for task in pending:
                    try:
                        result = await task
                        if bool(result.get("success", False)) or int(result.get("token_count", 0) or 0) > 0:
                            winner_result = result
                            winner_source, winner_model = tasks[task]
                            break
                    except Exception:
                        continue

            if winner_result is not None:
                text = str(winner_result.get("text") or "").strip()
                # 模拟流式发送 token，保持前端体验一致
                if text and text not in {"（网络不太稳定，请稍后再试）", "（LLM 输出为空）"}:
                    # 按句子或短句切分，模拟自然流式输出
                    import re
                    chunks = re.split(r'(?<=[。，！？；：""''】）}])', text)
                    chunks = [c for c in chunks if c.strip()]
                    if not chunks:
                        chunks = [text[i:i + 20] for i in range(0, len(text), 20)]
                    for idx, chunk in enumerate(chunks):
                        if request_id in voice_aborted:
                            break
                        await send_event(
                            "LLM_TOKEN",
                            {"text": chunk, "source": winner_source, "model": winner_model},
                            request_id=request_id,
                        )
                return {
                    **winner_result,
                    "source": winner_source,
                    "model": winner_model,
                }

            return {
                "text": "（网络不太稳定，请稍后再试）",
                "source": "local",
                "model": voice_local_model,
                "success": False,
                "token_count": 0,
                "first_token_latency_ms": None,
                "llm_generation_ms": 0,
            }

        async def _emit_tts_audio(
            *,
            request_id: str,
            text: str,
            started_ms: int,
        ) -> dict[str, int]:
            wav_bytes = await asyncio.to_thread(synthesize_tts_wav, text)
            synthesis_ms = max(0, int(time.time() * 1000) - started_ms)
            voice_tts_total_bytes[request_id] = len(wav_bytes)
            voice_tts_sent_bytes[request_id] = 0
            voice_tts_sent_chunks[request_id] = 0

            chunk_size = (
                int(settings.tts_chunk_size_bytes)
                if int(settings.tts_chunk_size_bytes) > 0
                else 16 * 1024
            )
            chunks = [wav_bytes[i : i + chunk_size] for i in range(0, len(wav_bytes), chunk_size)] or [b""]

            for idx, ch in enumerate(chunks):
                if request_id in voice_aborted:
                    return {
                        "tts_synthesis_ms": synthesis_ms,
                        "tts_first_chunk_latency_ms": synthesis_ms,
                        "tts_total_ms": synthesis_ms,
                        "tts_chunk_count": idx,
                        "tts_audio_bytes": int(voice_tts_sent_bytes.get(request_id, 0)),
                    }

                voice_tts_sent_bytes[request_id] = int(voice_tts_sent_bytes.get(request_id, 0)) + len(ch)
                voice_tts_sent_chunks[request_id] = idx + 1

                await send_event(
                    "TTS_CHUNK",
                    {
                        "format": "wav",
                        "sample_rate": 16000,
                        "channels": 1,
                        "data_b64": base64.b64encode(ch).decode("utf-8"),
                        "index": idx,
                        "is_last": idx == (len(chunks) - 1),
                        "tts_synthesis_ms": synthesis_ms,
                    },
                    request_id=request_id,
                )

            await send_event(
                "TTS_RESULT",
                {
                    "text": text,
                    "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
                    "tts_synthesis_ms": synthesis_ms,
                    "tts_chunk_count": len(chunks),
                    "tts_audio_bytes": len(wav_bytes),
                    "tts_total_ms": max(0, int(time.time() * 1000) - started_ms),
                },
                request_id=request_id,
            )
            return {
                "tts_synthesis_ms": synthesis_ms,
                "tts_first_chunk_latency_ms": synthesis_ms,
                "tts_total_ms": max(0, int(time.time() * 1000) - started_ms),
                "tts_chunk_count": len(chunks),
                "tts_audio_bytes": len(wav_bytes),
            }

        async def abort_voice_request(req_id: str, *, reason: str) -> None:
            # Idempotent: abort only once.
            if req_id in voice_completed:
                return

            # 若是 barge-in 打断，尽量恢复“被打断到哪里”的上下文供下一轮续接。
            has_interruption_context = False
            if reason == "barge_in":
                reply_text = str(voice_reply_text.get(req_id) or "").strip()
                total_bytes = int(voice_tts_total_bytes.get(req_id) or 0)
                sent_bytes = int(voice_tts_sent_bytes.get(req_id) or 0)

                if reply_text and total_bytes > 0 and sent_bytes > 0:
                    ratio = max(0.0, min(1.0, sent_bytes / float(total_bytes)))
                    cut = int(len(reply_text) * ratio)
                    spoken_text = reply_text[:cut].strip()
                    remaining_text = reply_text[cut:].strip()

                    # 限制注入长度，避免 system prompt 过长影响响应质量。
                    spoken_preview = spoken_text[-180:] if spoken_text else ""
                    remaining_preview = remaining_text[:220] if remaining_text else ""

                    interruption_context_note = (
                        "【打断上下文】上一次助手回复在播报中被用户打断。"
                        f"已播报内容（末尾片段）：{spoken_preview or '（几乎未播报）'}；"
                        f"未播报内容（开头片段）：{remaining_preview or '（无）'}。"
                        "请在下一次回复时自然衔接，不要机械重复整段上一条回复。"
                    )
                    await patch_context_memory(
                        op="append",
                        text=interruption_context_note,
                        request_id=f"ctxmem_{uuid.uuid4().hex[:8]}",
                    )
                    has_interruption_context = True

            voice_aborted.add(req_id)

            # Cancel in-flight tasks (partial/finalize).
            t = voice_partial_tasks.pop(req_id, None)
            if t is not None and not t.done():
                t.cancel()

            ft = voice_finalize_tasks.pop(req_id, None)
            if ft is not None and not ft.done():
                ft.cancel()

            # Drop buffers/state.
            voice_streams.pop(req_id, None)
            voice_last_activity_ms.pop(req_id, None)
            voice_asr_only.pop(req_id, None)
            voice_reply_text.pop(req_id, None)
            voice_tts_total_bytes.pop(req_id, None)
            voice_tts_sent_bytes.pop(req_id, None)
            voice_tts_sent_chunks.pop(req_id, None)
            voice_audio_bytes.pop(req_id, None)

            await send_event(
                "TASK_ABORTED",
                {
                    "reason": reason,
                    "has_interruption_context": has_interruption_context,
                },
                request_id=req_id,
            )
            await send_event(
                "TASK_FINISHED",
                {"ok": False, "reason": reason},
                request_id=req_id,
                final=True,
            )
            voice_completed.add(req_id)

        async def cleanup_stale_voice_requests() -> None:
            now_ms = int(time.time() * 1000)
            idle_ms = int(settings.voice_request_idle_seconds) * 1000
            if idle_ms <= 0 or not voice_last_activity_ms:
                return

            stale_ids = [
                rid
                for rid, last_ms in voice_last_activity_ms.items()
                if now_ms - int(last_ms) > idle_ms
            ]
            for rid in stale_ids:
                voice_last_activity_ms.pop(rid, None)
                voice_streams.pop(rid, None)
                voice_asr_only.pop(rid, None)
                voice_audio_bytes.pop(rid, None)
                t = voice_partial_tasks.pop(rid, None)
                if t is not None and not t.done():
                    t.cancel()
                ft = voice_finalize_tasks.pop(rid, None)
                if ft is not None and not ft.done():
                    ft.cancel()
                await send_event(
                    "ERROR",
                    {"code": "TIMEOUT", "message": "voice request idle timeout"},
                    request_id=rid,
                )
                await send_event(
                    "TASK_FINISHED",
                    {"ok": False, "reason": "timeout"},
                    request_id=rid,
                    final=True,
                )

        async def finalize_voice_request(req_id: str, *, reason: str) -> None:
            # Idempotent: only finalize once.
            if req_id in voice_completed:
                return

            if req_id in voice_aborted:
                return

            stream = voice_streams.pop(req_id, None)
            voice_last_activity_ms.pop(req_id, None)
            asr_only = bool(voice_asr_only.pop(req_id, False))
            if stream is None:
                return

            # Wait/stop any in-flight partial.
            t = voice_partial_tasks.pop(req_id, None)
            if t is not None and not t.done():
                try:
                    await asyncio.wait_for(t, timeout=15.0)
                except asyncio.TimeoutError:
                    t.cancel()

            final_text = await stream.transcribe_final()
            final_audio_bytes = int(voice_audio_bytes.pop(req_id, 0))
            audio_duration_ms = int(final_audio_bytes / 32) if final_audio_bytes > 0 else 0
            final_ts = int(time.time() * 1000)
            asr_latency_ms = max(0, final_ts - int(voice_request_started_ms.get(req_id, final_ts)))
            spoken_word_count = max(0, len((final_text or "").split()))
            paraphrase_markers = sum(
                1
                for marker in ["means", "in other words", "that is", "like", "similar to"]
                if marker in (final_text or "").lower()
            )

            await persist_event_only(
                "USER_MESSAGE",
                {
                    "text": final_text,
                    "source": "asr",
                    "language": session_language,
                    "scenario": session_scenario,
                    "audio_duration_ms": audio_duration_ms,
                    "word_count": spoken_word_count,
                    "paraphrase_markers": paraphrase_markers,
                    "asr_latency_ms": asr_latency_ms,
                },
                request_id=req_id,
                final=True,
                ts=final_ts,
            )
            voice_user_message_ts_ms[req_id] = final_ts

            asr_final_payload: dict[str, object] = {
                "reason": reason,
                "bytes": final_audio_bytes,
                "text": final_text,
                "audio_duration_ms": audio_duration_ms,
                "word_count": spoken_word_count,
                "language": session_language,
                "scenario": session_scenario,
                "asr_latency_ms": asr_latency_ms,
            }

            await send_event("ASR_FINAL", asr_final_payload, request_id=req_id)

            if req_id in voice_aborted:
                return

            if asr_only:
                await send_event(
                    "TASK_FINISHED",
                    {"ok": True, "asr_only": True, "reason": reason},
                    request_id=req_id,
                    final=True,
                )
                voice_completed.add(req_id)
                voice_finalize_tasks.pop(req_id, None)
                return

            user_prompt = (final_text or "").strip()
            reply_source = "local"
            if not user_prompt:
                reply_md = "（未检测到语音内容）"
            else:
                system_prompt = get_latest_system_prompt()
                context_memory = get_latest_context_memory()
                if context_memory:
                    if system_prompt:
                        system_prompt = f"{system_prompt}\n\n{context_memory}"
                    else:
                        system_prompt = context_memory

                history = get_all_chat_history_from_events(exclude_request_id=req_id)

                llm_started_ms = int(time.time() * 1000)
                llm_result = await _stream_chat_with_fallback(
                    request_id=req_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    history=history,
                )
                reply_md = str(llm_result.get("text") or "").strip() or "（LLM 输出为空）"
                reply_source = str(llm_result.get("source") or "local")
                llm_latency_ms = max(0, int(time.time() * 1000) - final_ts)

            if req_id in voice_aborted:
                return

            await persist_event_only(
                "AI_MESSAGE",
                {
                    "text": reply_md,
                    "source": reply_source,
                    "language": session_language,
                    "scenario": session_scenario,
                    "response_latency_ms": llm_latency_ms,
                    "llm_first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                    "llm_generation_ms": llm_result.get("llm_generation_ms"),
                },
                request_id=req_id,
                final=True,
                ts=int(time.time() * 1000),
            )

            await send_event(
                "LLM_RESULT",
                {
                    "format": "markdown",
                    "markdown": reply_md,
                    "source": reply_source,
                    "response_latency_ms": llm_latency_ms,
                    "language": session_language,
                    "scenario": session_scenario,
                    "model": llm_result.get("model"),
                    "token_count": llm_result.get("token_count"),
                    "first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                    "llm_generation_ms": llm_result.get("llm_generation_ms"),
                },
                request_id=req_id,
            )

            # 记录本轮完整回复文本，供后续可能的 barge-in 计算“被打断位置”。
            voice_reply_text[req_id] = reply_md

            if req_id in voice_aborted:
                return

            tts_metrics = await _emit_tts_audio(
                request_id=req_id,
                text=reply_md,
                started_ms=int(time.time() * 1000),
            )
            total_roundtrip_ms = max(0, int(time.time() * 1000) - int(voice_request_started_ms.get(req_id, final_ts)))
            await send_event(
                "TASK_FINISHED",
                {
                    "ok": True,
                    "reason": reason,
                    "pipeline_metrics": {
                        "asr_latency_ms": asr_latency_ms,
                        "audio_duration_ms": audio_duration_ms,
                        "llm_latency_ms": llm_latency_ms,
                        "llm_generation_ms": llm_result.get("llm_generation_ms"),
                        "llm_first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                        **tts_metrics,
                        "total_roundtrip_ms": total_roundtrip_ms,
                    },
                },
                request_id=req_id,
                final=True,
            )
            if session_user_id:
                create_record(
                    user_id=session_user_id,
                    record_type="dialogue",
                    content=user_prompt[:200],
                    metadata={
                        "action": "voice_turn",
                        "scenario": session_scenario,
                        "language": session_language,
                        "request_id": req_id,
                        "asr_text": final_text,
                        "assistant_reply": reply_md[:500],
                        "asr_latency_ms": asr_latency_ms,
                        "llm_latency_ms": llm_latency_ms,
                        "total_roundtrip_ms": total_roundtrip_ms,
                        **tts_metrics,
                    },
                )
            voice_completed.add(req_id)
            voice_finalize_tasks.pop(req_id, None)
            voice_reply_text.pop(req_id, None)
            voice_tts_total_bytes.pop(req_id, None)
            voice_tts_sent_bytes.pop(req_id, None)
            voice_tts_sent_chunks.pop(req_id, None)
            voice_audio_bytes.pop(req_id, None)
            voice_request_started_ms.pop(req_id, None)
            voice_user_message_ts_ms.pop(req_id, None)

        while True:
            await cleanup_stale_voice_requests()

            poll_timeout_s: float | None = (
                1.0 if int(settings.voice_request_idle_seconds) > 0 else None
            )
            try:
                if poll_timeout_s is None:
                    raw = await ws.receive()
                else:
                    raw = await asyncio.wait_for(ws.receive(), timeout=poll_timeout_s)
            except asyncio.TimeoutError:
                continue

            if isinstance(raw, dict) and raw.get("type") == "websocket.disconnect":
                break

            # Starlette websocket message shape: {'type': 'websocket.receive', 'text': str|None, 'bytes': bytes|None}
            data: dict | None = None
            if isinstance(raw, dict) and raw.get("type") == "websocket.receive":
                b = raw.get("bytes")
                t = raw.get("text")

                if b is not None:
                    rid = pending_binary_chunk_for
                    pending_binary_chunk_for = None
                    if rid is None:
                        await send_event(
                            "ERROR",
                            {
                                "code": "VALIDATION_ERROR",
                                "message": "unexpected binary frame (send AUDIO_CHUNK_BIN first)",
                            },
                            request_id="ws",
                        )
                        continue

                    if rid in voice_completed or rid in voice_aborted:
                        continue

                    stream = voice_streams.get(rid)
                    if stream is None:
                        await send_event(
                            "ERROR",
                            {
                                "code": "VALIDATION_ERROR",
                                "message": "unknown request_id (call AUDIO_START first)",
                            },
                            request_id=rid,
                        )
                        continue

                    size = await stream.add_chunk_bytes(b)
                    voice_audio_bytes[rid] = int(size)
                    voice_last_activity_ms[rid] = int(time.time() * 1000)

                    existing = voice_partial_tasks.get(rid)
                    if existing is None or existing.done():

                        async def _run_partial_bin(rid2: str, buffer_size: int) -> None:
                            s = voice_streams.get(rid2)
                            if s is None:
                                return
                            try:
                                partial = await s.maybe_transcribe_partial()
                                if partial:
                                    partial_payload: dict[str, object] = {
                                        "bytes": buffer_size,
                                        "text": partial,
                                    }
                                    await send_event(
                                        "ASR_PARTIAL",
                                        partial_payload,
                                        request_id=rid2,
                                    )
                            except Exception as e:
                                await send_event(
                                    "ERROR",
                                    {"code": "ASR_ERROR", "message": str(e)},
                                    request_id=rid2,
                                )

                        voice_partial_tasks[rid] = asyncio.create_task(_run_partial_bin(rid, size))

                    if stream.vad_should_finalize():
                        fin = voice_finalize_tasks.get(rid)
                        if fin is None or fin.done():
                            tsk = voice_partial_tasks.pop(rid, None)
                            if tsk is not None and not tsk.done():
                                tsk.cancel()

                            async def _run_finalize_bin(rid2: str) -> None:
                                try:
                                    await finalize_voice_request(rid2, reason="vad")
                                except Exception as e:
                                    await send_event(
                                        "ERROR",
                                        {"code": "ASR_ERROR", "message": str(e)},
                                        request_id=rid2,
                                    )

                            voice_finalize_tasks[rid] = asyncio.create_task(_run_finalize_bin(rid))
                    continue

                if isinstance(t, str) and t:
                    try:
                        obj = json.loads(t)
                        if isinstance(obj, dict):
                            data = obj
                    except Exception:
                        data = None

            if data is None:
                await send_event(
                    "ERROR",
                    {"code": "VALIDATION_ERROR", "message": "invalid websocket message"},
                    request_id="ws",
                )
                continue

            msg_type = data.get("type") if isinstance(data, dict) else None
            payload = data.get("payload") if isinstance(data, dict) else None

            # Set/update conversation context (system prompt) for voice dialogue.
            if msg_type == "CONTEXT_SET" and isinstance(payload, dict):
                req_id = str(data.get("request_id") or f"ctx_{uuid.uuid4().hex[:8]}")
                ts = int(time.time() * 1000)
                system_prompt = str(payload.get("system_prompt") or payload.get("systemPrompt") or "")
                language = str(payload.get("language") or "")
                scenario = str(payload.get("scenario") or "")
                payload_user_id = payload.get("user_id")
                try:
                    next_user_id = int(payload_user_id) if payload_user_id is not None else None
                    if next_user_id is not None and next_user_id > 0:
                        session_user_id = next_user_id
                except (TypeError, ValueError):
                    pass
                if language:
                    session_language = language
                if scenario:
                    session_scenario = scenario
                await send_event(
                    "CONTEXT_SET",
                    {
                        "system_prompt": system_prompt,
                        "language": session_language,
                        "scenario": session_scenario,
                        "user_id": session_user_id,
                    },
                    request_id=req_id,
                    ts=ts,
                    final=False,
                    log=True,
                )
                continue

            # 修改可持久化上下文记忆。
            # payload:
            # - op: append | replace | clear
            # - text: 需要写入的记忆文本（clear 可省略）
            if msg_type == "CONTEXT_PATCH" and isinstance(payload, dict):
                req_id = str(data.get("request_id") or f"ctxm_{uuid.uuid4().hex[:8]}")
                op = str(payload.get("op") or "append")
                text = str(payload.get("text") or "")
                merged = await patch_context_memory(op=op, text=text, request_id=req_id)
                await send_event(
                    "CONTEXT_PATCHED",
                    {"ok": True, "op": op, "memory": merged},
                    request_id=req_id,
                )
                continue

            # -----------------
            # 语音对话（P0）：前端切片上传音频，后端流式 ASR + 最终 LLM + TTS
            # 客户端消息：
            # - AUDIO_START: {request_id, payload:{sample_rate,channels,encoding}}
            # - AUDIO_CHUNK: {request_id, payload:{data_b64}}
            # - AUDIO_END:   {request_id}
            # 服务端事件：ASR_PARTIAL/ASR_FINAL/LLM_TOKEN/LLM_RESULT/TTS_CHUNK/TTS_RESULT + TASK_FINISHED
            # -----------------
            if msg_type == "AUDIO_START" and isinstance(payload, dict):
                req_id = str(data.get("request_id") or f"req_{uuid.uuid4().hex[:10]}")

                # Barge-in (P1): starting a new utterance aborts any in-flight agent output.
                inflight = [
                    rid
                    for rid, t in list(voice_finalize_tasks.items())
                    if rid != req_id and t is not None and not t.done() and rid not in voice_completed
                ]
                for rid in inflight:
                    await abort_voice_request(rid, reason="barge_in")

                cfg = VoiceStreamConfig(
                    sample_rate=int(payload.get("sample_rate") or 16000),
                    channels=int(payload.get("channels") or 1),
                    encoding=str(payload.get("encoding") or "pcm_s16le"),
                    language=(str(payload.get("language")).strip() or None)
                    if payload.get("language") is not None
                    else None,
                    vad_enabled=bool(payload.get("vad_enabled") or settings.enable_vad),
                    vad_mode=int(payload.get("vad_mode") or settings.vad_mode),
                    vad_silence_ms=int(payload.get("vad_silence_ms") or settings.vad_silence_ms),
                )
                voice_streams[req_id] = VoiceStream(config=cfg, transcriber=asr_transcriber)
                voice_last_activity_ms[req_id] = int(time.time() * 1000)
                voice_request_started_ms[req_id] = voice_last_activity_ms[req_id]
                voice_asr_only[req_id] = bool(payload.get("asr_only") or False)
                voice_audio_bytes[req_id] = 0
                await send_event(
                    "TASK_STARTED",
                    {
                        "task": "voice_audio",
                        "request_id": req_id,
                        "config": cfg.__dict__,
                        "language": session_language or (cfg.language or ""),
                        "scenario": session_scenario,
                        "user_id": session_user_id,
                    },
                    request_id=req_id,
                )
                continue

            if msg_type == "AUDIO_CHUNK" and isinstance(payload, dict):
                req_id = str(data.get("request_id") or "")

                # 若该 request 已完成（VAD/客户端 end），后续 chunk 可能是网络/缓冲尾部：静默忽略。
                if req_id in voice_completed:
                    continue

                stream = voice_streams.get(req_id)
                if stream is None:
                    await send_event(
                        "ERROR",
                        {"code": "VALIDATION_ERROR", "message": "unknown request_id (call AUDIO_START first)"},
                        request_id=req_id or "ws",
                    )
                    continue

                data_b64 = str(payload.get("data_b64") or "")
                size = await stream.add_chunk_b64(data_b64)
                voice_audio_bytes[req_id] = int(size)
                voice_last_activity_ms[req_id] = int(time.time() * 1000)

                # 真实时间流式输入时，不能在这里 await 重型 ASR（会导致 backpressure，客户端 send 卡死）。
                # 改为后台任务：每个 request_id 最多一个进行中的 partial 转写。
                existing = voice_partial_tasks.get(req_id)
                if existing is None or existing.done():

                    async def _run_partial(rid: str, buffer_size: int) -> None:
                        s = voice_streams.get(rid)
                        if s is None:
                            return
                        try:
                            partial = await s.maybe_transcribe_partial()
                            if partial:
                                partial_payload: dict[str, object] = {
                                    "bytes": buffer_size,
                                    "text": partial,
                                }
                                await send_event(
                                    "ASR_PARTIAL",
                                    partial_payload,
                                    request_id=rid,
                                )
                        except Exception as e:
                            await send_event(
                                "ERROR",
                                {"code": "ASR_ERROR", "message": str(e)},
                                request_id=rid,
                            )

                    voice_partial_tasks[req_id] = asyncio.create_task(_run_partial(req_id, size))

                # VAD 自动收句：检测到持续静音后，后台 finalize（无需客户端发 AUDIO_END）。
                if stream.vad_should_finalize():
                    fin = voice_finalize_tasks.get(req_id)
                    if fin is None or fin.done():

                        # 尽量取消未完成的 partial，避免和 finalize 竞争模型。
                        t = voice_partial_tasks.pop(req_id, None)
                        if t is not None and not t.done():
                            t.cancel()

                        async def _run_finalize(rid: str) -> None:
                            try:
                                await finalize_voice_request(rid, reason="vad")
                            except Exception as e:
                                await send_event(
                                    "ERROR",
                                    {"code": "ASR_ERROR", "message": str(e)},
                                    request_id=rid,
                                )

                        voice_finalize_tasks[req_id] = asyncio.create_task(_run_finalize(req_id))
                continue

            # Binary audio chunk mode: client sends a JSON header then the next WS binary frame.
            # Client message:
            # - AUDIO_CHUNK_BIN: {request_id, payload:{}} followed by a binary frame with raw bytes.
            if msg_type == "AUDIO_CHUNK_BIN":
                req_id = str(data.get("request_id") or "")
                if not req_id:
                    await send_event(
                        "ERROR",
                        {"code": "VALIDATION_ERROR", "message": "missing request_id"},
                        request_id="ws",
                    )
                    continue
                pending_binary_chunk_for = req_id
                continue

            if msg_type == "AUDIO_END":
                req_id = str(data.get("request_id") or "")
                # 如果已被 VAD 自动 finalize，客户端再发 AUDIO_END 视为幂等重复：忽略。
                if req_id in voice_completed:
                    continue

                if req_id in voice_aborted:
                    continue

                stream = voice_streams.get(req_id)
                if stream is None:
                    await send_event(
                        "ERROR",
                        {"code": "VALIDATION_ERROR", "message": "unknown request_id (call AUDIO_START first)"},
                        request_id=req_id or "ws",
                    )
                    await send_event("TASK_FINISHED", {"ok": False}, request_id=req_id or "ws", final=True)
                    continue

                fin = voice_finalize_tasks.get(req_id)
                if fin is None or fin.done():

                    # 尽量取消未完成的 partial，避免和 finalize 竞争模型。
                    t = voice_partial_tasks.pop(req_id, None)
                    if t is not None and not t.done():
                        t.cancel()

                    async def _run_finalize(rid: str) -> None:
                        try:
                            await finalize_voice_request(rid, reason="client_end")
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            await send_event(
                                "ERROR",
                                {"code": "ASR_ERROR", "message": str(e)},
                                request_id=rid,
                            )

                    voice_finalize_tasks[req_id] = asyncio.create_task(_run_finalize(req_id))
                continue

            # 文本直连模式：绕过 ASR，直接走 LLM 竞速 + TTS，便于快速测试对话体验。
            if msg_type == "TEXT" and isinstance(payload, dict):
                req_id = str(data.get("request_id") or f"text_{uuid.uuid4().hex[:8]}")
                user_text = str(payload.get("text") or "").strip()

                if not user_text:
                    await send_event(
                        "ERROR",
                        {"code": "VALIDATION_ERROR", "message": "text is empty"},
                        request_id=req_id,
                    )
                    continue

                text_ts = int(time.time() * 1000)
                await persist_event_only(
                    "USER_MESSAGE",
                    {
                        "text": user_text,
                        "source": "text",
                        "language": session_language,
                        "scenario": session_scenario,
                        "word_count": len(user_text.split()),
                        "paraphrase_markers": sum(
                            1
                            for marker in ["means", "in other words", "that is", "like", "similar to"]
                            if marker in user_text.lower()
                        ),
                    },
                    request_id=req_id,
                    final=True,
                    ts=text_ts,
                )
                voice_user_message_ts_ms[req_id] = text_ts

                system_prompt = get_latest_system_prompt()
                context_memory = get_latest_context_memory()
                if context_memory:
                    if system_prompt:
                        system_prompt = f"{system_prompt}\n\n{context_memory}"
                    else:
                        system_prompt = context_memory

                history = get_all_chat_history_from_events(exclude_request_id=req_id)

                llm_result = await _stream_chat_with_fallback(
                    request_id=req_id,
                    system_prompt=system_prompt,
                    user_prompt=user_text,
                    history=history,
                )
                reply_md = str(llm_result.get("text") or "").strip() or "（LLM 输出为空）"
                reply_source = str(llm_result.get("source") or "local")
                llm_latency_ms = max(0, int(time.time() * 1000) - text_ts)

                await persist_event_only(
                    "AI_MESSAGE",
                    {
                        "text": reply_md,
                        "source": reply_source,
                        "language": session_language,
                        "scenario": session_scenario,
                        "response_latency_ms": llm_latency_ms,
                        "llm_first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                        "llm_generation_ms": llm_result.get("llm_generation_ms"),
                    },
                    request_id=req_id,
                    final=True,
                    ts=int(time.time() * 1000),
                )

                await send_event(
                    "LLM_RESULT",
                    {
                        "format": "markdown",
                        "markdown": reply_md,
                        "source": reply_source,
                        "response_latency_ms": llm_latency_ms,
                        "language": session_language,
                        "scenario": session_scenario,
                        "model": llm_result.get("model"),
                        "token_count": llm_result.get("token_count"),
                        "first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                        "llm_generation_ms": llm_result.get("llm_generation_ms"),
                    },
                    request_id=req_id,
                )

                tts_metrics = await _emit_tts_audio(
                    request_id=req_id,
                    text=reply_md,
                    started_ms=int(time.time() * 1000),
                )
                total_roundtrip_ms = max(0, int(time.time() * 1000) - text_ts)
                await send_event(
                    "TASK_FINISHED",
                    {
                        "ok": True,
                        "reason": "text",
                        "pipeline_metrics": {
                            "llm_latency_ms": llm_latency_ms,
                            "llm_generation_ms": llm_result.get("llm_generation_ms"),
                            "llm_first_token_latency_ms": llm_result.get("first_token_latency_ms"),
                            **tts_metrics,
                            "total_roundtrip_ms": total_roundtrip_ms,
                        },
                    },
                    request_id=req_id,
                    final=True,
                )
                if session_user_id:
                    create_record(
                        user_id=session_user_id,
                        record_type="dialogue",
                        content=user_text[:200],
                        metadata={
                            "action": "text_turn",
                            "scenario": session_scenario,
                            "language": session_language,
                            "request_id": req_id,
                            "assistant_reply": reply_md[:500],
                            "llm_latency_ms": llm_latency_ms,
                            "total_roundtrip_ms": total_roundtrip_ms,
                            **tts_metrics,
                        },
                    )
                continue

            if msg_type == "LOOKUP_VOCAB" and isinstance(payload, dict):
                term = str(payload.get("term") or "").strip()
                req_id = str(data.get("request_id") or "ws") if isinstance(data, dict) else "ws"
                await send_event("VOCAB_LOOKUP_STARTED", {"term": term}, request_id=req_id)

                if not term:
                    await send_event("ERROR", {"code": "invalid_request", "message": "term is empty"})
                    await send_event("TASK_FINISHED", {"ok": False}, request_id=req_id, final=True)
                    continue

                with Session(get_engine()) as session:
                    lookup_response, lookup_meta = await _resolve_lookup_payload(
                        term=term,
                        fuzzy=True,
                        include_relations=True,
                        user_id=session_user_id,
                        source="manual",
                        session=session,
                    )
                    session.add(
                        UserVocabQuery(
                            user_id=session_user_id,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            term=lookup_response.term,
                            source="manual",
                            result=lookup_response.definition,
                            meta_data={
                                **lookup_meta,
                                "origin": "voice_lookup",
                                "language": session_language,
                                "scenario": session_scenario,
                            },
                        )
                    )
                    session.commit()

                await send_event(
                    "VOCAB_RESULT",
                    lookup_response.model_dump(),
                    request_id=req_id,
                )

                await send_event("TASK_FINISHED", {"ok": True}, request_id=req_id, final=True)
                continue

            if msg_type == "GRADE_ESSAY" and isinstance(payload, dict):
                ocr_text = str(payload.get("ocr_text") or "").strip()
                language = str(payload.get("language") or "en").strip() or "en"
                req_id = str(data.get("request_id") or f"req_{uuid.uuid4().hex[:10]}")

                if not ocr_text:
                    await send_event(
                        "ERROR",
                        {"code": "invalid_request", "message": "ocr_text is empty"},
                        request_id=req_id,
                    )
                    await send_event("TASK_FINISHED", {"ok": False}, request_id=req_id, final=True)
                    continue

                # 先持久化 submission，确保事件里可以带 submission_id
                with Session(get_engine()) as session:
                    submission = EssaySubmission(
                        user_id=session_user_id,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        request_id=req_id,
                        ocr_text=ocr_text,
                        language=language,
                    )
                    session.add(submission)
                    session.commit()
                    session.refresh(submission)

                submission_id = submission.id
                if submission_id is None:
                    await send_event(
                        "ERROR",
                        {"code": "internal_error", "message": "failed to create submission"},
                        request_id=req_id,
                    )
                    await send_event("TASK_FINISHED", {"ok": False}, request_id=req_id, final=True)
                    continue

                await send_event(
                    "TASK_STARTED",
                    {"task": "essay_grade", "submission_id": submission_id, "language": language},
                    request_id=req_id,
                )

                from .application.essay_grading import run_grading_pipeline

                result = await run_grading_pipeline(ocr_text=ocr_text, language=language)
                score = int(round(result["total_score"] * 10))
                score = max(0, min(100, score))

                with Session(get_engine()) as session:
                    session.add(
                        EssayResult(
                            submission_id=int(submission_id),
                            score=score,
                            result=result,
                        )
                    )
                    session.commit()

                if session_user_id:
                    create_record(
                        user_id=session_user_id,
                        record_type="essay",
                        content=ocr_text[:200],
                        metadata={
                            "action": "grade_essay",
                            "submission_id": submission_id,
                            "language": language,
                            "score": score,
                        },
                    )

                await send_event(
                    "ANALYSIS_RESULT",
                    {
                        "kind": "essay_grade",
                        "submission_id": submission_id,
                        "score": score,
                        "result": result,
                    },
                    request_id=req_id,
                )
                await send_event(
                    "TASK_FINISHED",
                    {"ok": True, "submission_id": submission_id},
                    request_id=req_id,
                    final=True,
                )
                continue

            # 默认：回显，证明链路可用
            await send_event("ECHO", {"received": data})
    except WebSocketDisconnect:
        return
