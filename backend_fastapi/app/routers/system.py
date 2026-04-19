from __future__ import annotations

import importlib
import sys
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from ..llm import list_available_llm_models
from ..runtime_config import get_runtime_config, update_runtime_config
from ..settings import settings

router = APIRouter(prefix="/api/system", tags=["system"])


def _normalize_http_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""

    path = (parsed.path or "").rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _clamp_int(value: Any, *, low: int, high: int, default: int) -> int:
    try:
        iv = int(value)
    except Exception:
        return default
    if iv < low:
        return low
    if iv > high:
        return high
    return iv


def _normalize_ws_host(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    value = value.replace("ws://", "").replace("wss://", "")
    value = value.rstrip("/")
    value = value.replace("localhost:8011", "localhost:8012")
    value = value.replace("127.0.0.1:8011", "127.0.0.1:8012")
    value = value.replace("localhost:8000", "localhost:8012")
    value = value.replace("127.0.0.1:8000", "127.0.0.1:8012")
    return value


def _normalize_backend_url(raw: str) -> str:
    value = _normalize_http_url(raw)
    if not value:
        return ""
    value = value.replace("http://localhost:8011", "http://localhost:8012")
    value = value.replace("http://127.0.0.1:8011", "http://127.0.0.1:8012")
    value = value.replace("http://localhost:8000", "http://localhost:8012")
    value = value.replace("http://127.0.0.1:8000", "http://127.0.0.1:8012")
    return value


class SystemConfig(BaseModel):
    port: int
    llmEndpoint: str
    models: dict[str, Any]
    prompts: dict[str, Any]
    ocr: dict[str, Any]
    tts: dict[str, Any]
    asr: dict[str, Any]
    python: dict[str, Any]
    appConfig: dict[str, Any]


class SystemConfigResponse(BaseModel):
    success: bool
    data: SystemConfig


@router.get("/config", response_model=SystemConfigResponse)
async def get_config() -> SystemConfigResponse:
    # 返回运行态可视化配置：
    # - settings.py 的基础配置
    # - runtime_config 的可变覆盖（场景模型、Prompt 覆盖）
    # - LLM 服务可用模型列表（来自 LM Studio /models）
    def _has_module(module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    prompt_dir = Path(__file__).resolve().parent.parent / "prompts"
    prompt_templates = sorted([p.name for p in prompt_dir.glob("*.j2")])

    has_seamless = _has_module("transformers")
    has_paddleocr = _has_module("paddleocr")

    runtime = get_runtime_config()
    app_cfg = ((runtime.get("appConfig") or {}))
    scene_models = (((runtime.get("models") or {}).get("scene") or {}))
    overrides = (((runtime.get("prompts") or {}).get("overrides") or {}))

    available_models = await list_available_llm_models()
    primary_model = str(((runtime.get("models") or {}).get("primary") or "")).strip()
    if not primary_model and available_models:
        primary_model = available_models[0]

    cfg = SystemConfig(
        port=int(settings.port),
        llmEndpoint=str(settings.llm_base_url),
        models={
            "default": str(settings.llm_model),
            "primary": primary_model,
            "available": available_models,
            "scene": {
                "chat": str(scene_models.get("chat") or ""),
                "vocab": str(scene_models.get("vocab") or ""),
                "essay": str(scene_models.get("essay") or ""),
            },
        },
        prompts={
            "templates": prompt_templates,
            "overrides": overrides,
        },
        ocr={
            "backend": "paddleocr",
            "runtime": {
                "available": bool(has_paddleocr),
            },
        },
        tts={
            "backend": str(settings.tts_backend),
            "kokoro": {
                "langCode": str(settings.kokoro_lang_code),
                "voice": str(settings.kokoro_voice),
                "speed": float(settings.kokoro_speed),
            },
            "edge": {
                "voice": str(settings.edge_tts_voice),
                "speed": str(settings.edge_tts_speed),
            },

        },
        asr={
            "enabled": bool(settings.enable_asr),
            "backend": str(settings.asr_backend),
            "model": str(settings.asr_model),
            "device": str(settings.asr_device),
            "computeType": str(settings.asr_compute_type),
            "vad": {
                "enabled": bool(settings.enable_vad),
                "mode": int(settings.vad_mode),
                "silenceMs": int(settings.vad_silence_ms),
            },
            "runtime": {
                "available": bool(has_seamless),
                "hasSeamless": bool(has_seamless),
            },
        },
        python={
            "executable": str(sys.executable),
            "version": str(sys.version).split(" ")[0],
        },
        appConfig={
            "general": {
                "theme": str(((app_cfg.get("general") or {}).get("theme") or "dark")),
                "language": str(((app_cfg.get("general") or {}).get("language") or "zh-CN")),
                "autoUpdate": bool(((app_cfg.get("general") or {}).get("autoUpdate", True))),
            },
            "audio": {
                "inputDevice": str(((app_cfg.get("audio") or {}).get("inputDevice") or "default")),
                "outputDevice": str(((app_cfg.get("audio") or {}).get("outputDevice") or "default")),
                "volume": int(_clamp_int(((app_cfg.get("audio") or {}).get("volume")), low=0, high=100, default=80)),
            },
            "ai": {
                "model": str(((app_cfg.get("ai") or {}).get("model") or "local-model")),
                "temperature": float(((app_cfg.get("ai") or {}).get("temperature") or 0.7),),
                "voice": str(((app_cfg.get("ai") or {}).get("voice") or "alloy")),
            },
            "backend": {
                "url": str(_normalize_backend_url(((app_cfg.get("backend") or {}).get("url") or "http://localhost:8012")) or "http://localhost:8012"),
                "wsUrl": str(_normalize_ws_host(((app_cfg.get("backend") or {}).get("wsUrl") or "localhost:8012")) or "localhost:8012"),
            },
        },
    )
    return SystemConfigResponse(success=True, data=cfg)


@router.post("/config")
async def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    patch = payload if isinstance(payload, dict) else {}

    # 1) 直接作用于 settings（立即生效）
    llm_endpoint = patch.get("llmEndpoint")
    if isinstance(llm_endpoint, str) and llm_endpoint.strip():
        normalized = _normalize_http_url(llm_endpoint)
        if normalized:
            settings.llm_base_url = normalized

    models = patch.get("models")
    if isinstance(models, dict):
        default_model = models.get("default")
        if isinstance(default_model, str):
            settings.llm_model = default_model.strip() or settings.llm_model

    asr = patch.get("asr")
    if isinstance(asr, dict):
        if "enabled" in asr:
            settings.enable_asr = bool(asr.get("enabled"))
        if isinstance(asr.get("backend"), str):
            backend = str(asr.get("backend") or "").strip()
            if backend:
                settings.asr_backend = backend
        if isinstance(asr.get("model"), str):
            settings.asr_model = str(asr.get("model")).strip() or settings.asr_model
        if isinstance(asr.get("device"), str):
            settings.asr_device = str(asr.get("device")).strip() or settings.asr_device
        if isinstance(asr.get("computeType"), str):
            settings.asr_compute_type = str(asr.get("computeType")).strip() or settings.asr_compute_type

        vad = asr.get("vad")
        if isinstance(vad, dict):
            if "enabled" in vad:
                settings.enable_vad = bool(vad.get("enabled"))
            if "mode" in vad:
                settings.vad_mode = _clamp_int(
                    vad.get("mode"),
                    low=0,
                    high=3,
                    default=int(settings.vad_mode),
                )
            if "silenceMs" in vad:
                settings.vad_silence_ms = _clamp_int(
                    vad.get("silenceMs"),
                    low=200,
                    high=5000,
                    default=int(settings.vad_silence_ms),
                )

    tts = patch.get("tts")
    if isinstance(tts, dict):
        if isinstance(tts.get("backend"), str):
            settings.tts_backend = str(tts.get("backend")).strip() or settings.tts_backend
    # 2) 运行时可持久化部分（场景模型 / Prompt 覆盖）
    runtime_patch: dict[str, Any] = {}
    if isinstance(models, dict):
        rp_models: dict[str, Any] = {}
        if isinstance(models.get("primary"), str):
            rp_models["primary"] = str(models.get("primary") or "").strip()
        if isinstance(models.get("scene"), dict):
            scene_raw = models.get("scene")
            scene: dict[str, Any] = scene_raw if isinstance(scene_raw, dict) else {}
            rp_models["scene"] = {
                "chat": str(scene.get("chat") or "").strip(),
                "vocab": str(scene.get("vocab") or "").strip(),
                "essay": str(scene.get("essay") or "").strip(),
            }
        if rp_models:
            runtime_patch["models"] = rp_models

    prompts = patch.get("prompts")
    if isinstance(prompts, dict) and isinstance(prompts.get("overrides"), dict):
        overrides_raw = prompts.get("overrides")
        overrides: dict[str, Any] = overrides_raw if isinstance(overrides_raw, dict) else {}
        runtime_patch["prompts"] = {
            "overrides": {
                str(k): str(v)
                for k, v in overrides.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        }

    app_config = patch.get("appConfig")
    if isinstance(app_config, dict):
        next_app_cfg: dict[str, Any] = {}

        general = app_config.get("general")
        if isinstance(general, dict):
            theme_raw = str(general.get("theme") or "").strip().lower()
            theme = theme_raw if theme_raw in {"dark", "light", "system"} else "dark"
            next_app_cfg["general"] = {
                "theme": theme,
                "language": str(general.get("language") or "zh-CN").strip() or "zh-CN",
                "autoUpdate": bool(general.get("autoUpdate", True)),
            }

        audio = app_config.get("audio")
        if isinstance(audio, dict):
            next_app_cfg["audio"] = {
                "inputDevice": str(audio.get("inputDevice") or "default").strip() or "default",
                "outputDevice": str(audio.get("outputDevice") or "default").strip() or "default",
                "volume": _clamp_int(audio.get("volume"), low=0, high=100, default=80),
            }

        ai = app_config.get("ai")
        if isinstance(ai, dict):
            temp_val = ai.get("temperature", 0.7)
            try:
                temp = float(temp_val)
            except Exception:
                temp = 0.7
            if temp < 0:
                temp = 0
            if temp > 2:
                temp = 2

            model = str(ai.get("model") or "").strip() or "local-model"
            voice = str(ai.get("voice") or "alloy").strip() or "alloy"
            next_app_cfg["ai"] = {
                "model": model,
                "temperature": temp,
                "voice": voice,
            }
            settings.llm_model = model

        backend_cfg = app_config.get("backend")
        if isinstance(backend_cfg, dict):
            url = _normalize_backend_url(str(backend_cfg.get("url") or "")) or "http://localhost:8012"
            ws = _normalize_ws_host(str(backend_cfg.get("wsUrl") or "")) or "localhost:8012"
            next_app_cfg["backend"] = {
                "url": url,
                "wsUrl": ws,
            }

        if next_app_cfg:
            runtime_patch["appConfig"] = next_app_cfg

    if runtime_patch:
        update_runtime_config(runtime_patch)

    return {"success": True}
