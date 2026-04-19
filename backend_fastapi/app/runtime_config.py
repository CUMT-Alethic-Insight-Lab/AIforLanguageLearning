from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

# 运行时可变配置（支持接口热更新 + 落盘持久化）
# 说明：
# - settings.py 负责“启动默认值”
# - 本模块负责“运行时覆盖值”，用于前端设置页实时修改
# - 配置存储在 backend_fastapi/data/runtime_config.json

_RUNTIME_LOCK = RLock()


def _runtime_file() -> Path:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "runtime_config.json"


_DEFAULT_RUNTIME_CONFIG: dict[str, Any] = {
    "appConfig": {
        "general": {
            "theme": "dark",
            "language": "zh-CN",
            "autoUpdate": True,
        },
        "audio": {
            "inputDevice": "default",
            "outputDevice": "default",
            "volume": 80,
        },
        "ai": {
            "model": "local-model",
            "temperature": 0.7,
            "voice": "alloy",
        },
        "backend": {
            "url": "http://localhost:8012",
            "wsUrl": "localhost:8012",
        },
    },
    "models": {
        "primary": "",
        "available": [],
        "scene": {
            "chat": "",
            "vocab": "",
            "essay": "",
            "analytics": "",  # 本地模型：学情分析、个人画像、周报润色
            "class_analysis": "",  # 云端模型：复杂班级数据分析
        },
    },
    "prompts": {
        "overrides": {
            # key 示例："voice_system_prompt.j2" / "essay_grade.j2"
        }
    },
}


_RUNTIME_CONFIG: dict[str, Any] = deepcopy(_DEFAULT_RUNTIME_CONFIG)
_LOADED = False


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_if_needed() -> None:
    global _LOADED, _RUNTIME_CONFIG
    if _LOADED:
        return

    path = _runtime_file()
    if path.exists():
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                _RUNTIME_CONFIG = _deep_merge(_DEFAULT_RUNTIME_CONFIG, obj)
        except Exception:
            _RUNTIME_CONFIG = deepcopy(_DEFAULT_RUNTIME_CONFIG)

    _LOADED = True


def _save_locked() -> None:
    path = _runtime_file()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_RUNTIME_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_runtime_config() -> dict[str, Any]:
    with _RUNTIME_LOCK:
        _load_if_needed()
        return deepcopy(_RUNTIME_CONFIG)


def update_runtime_config(patch: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    global _RUNTIME_CONFIG
    with _RUNTIME_LOCK:
        _load_if_needed()
        if isinstance(patch, dict) and patch:
            _RUNTIME_CONFIG = _deep_merge(_RUNTIME_CONFIG, patch)
            if persist:
                _save_locked()
        return deepcopy(_RUNTIME_CONFIG)


def get_scene_model(scene: str) -> str:
    cfg = get_runtime_config()
    scene_models = (((cfg.get("models") or {}).get("scene") or {}))
    value = scene_models.get(scene)
    return str(value or "").strip()


def get_prompt_override(template_name: str) -> str:
    cfg = get_runtime_config()
    overrides = ((((cfg.get("prompts") or {}).get("overrides") or {})))
    value = overrides.get(template_name)
    return str(value or "")
