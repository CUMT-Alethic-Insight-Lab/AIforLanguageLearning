from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..infrastructure.db_user import (
    delete_user,
    get_user_by_id,
    list_users,
    update_user_password,
)
from ..infrastructure.dependencies import get_current_user
from ..infrastructure.rbac import Role, has_role
from ..infrastructure.security import hash_password
from ..settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(current_user: Any = Depends(get_current_user)) -> Any:
    if not has_role(current_user, Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


class ConfigResponse(BaseModel):
    success: bool
    data: dict | None = None
    message: str | None = None
    error: str | None = None


class PromptUpdateRequest(BaseModel):
    key: str
    value: str


class BackupResponse(BaseModel):
    success: bool
    data: list[dict] | None = None
    message: str | None = None
    error: str | None = None


class LogResponse(BaseModel):
    success: bool
    data: list[str] | None = None
    message: str | None = None
    error: str | None = None


class SystemStatsResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None


class UserListResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None


@router.get("/config", response_model=ConfigResponse)
async def get_config(_: Any = Depends(_require_admin)) -> ConfigResponse:
    return ConfigResponse(
        success=True,
        data={
            "app_env": settings.app_env,
            "port": settings.port,
            "llm_base_url": settings.llm_base_url,
            "llm_model": settings.llm_model,
            "database_url": settings.database_url,
            "enable_asr": settings.enable_asr,
            "asr_backend": settings.asr_backend,
            "tts_backend": settings.tts_backend,
        },
    )


@router.post("/config", response_model=ConfigResponse)
async def update_config(
    body: dict,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    # FastAPI settings 是只读的，运行时配置持久化到 runtime_config.json
    from ..runtime_config import update_runtime_config

    runtime = update_runtime_config(body)
    return ConfigResponse(success=True, data=runtime)


@router.get("/prompts", response_model=ConfigResponse)
async def get_prompts(_: Any = Depends(_require_admin)) -> ConfigResponse:
    import json

    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")
    prompts: dict[str, Any] = {}
    if os.path.isdir(prompts_dir):
        for fname in os.listdir(prompts_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(prompts_dir, fname), "r", encoding="utf-8") as f:
                        prompts[fname[:-5]] = json.load(f)
                except Exception:
                    pass
    return ConfigResponse(success=True, data=prompts)


@router.post("/prompts/{category}", response_model=ConfigResponse)
async def update_prompt(
    category: str,
    req: PromptUpdateRequest,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    import json

    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")
    filepath = os.path.join(prompts_dir, f"{category}.json")
    data: dict[str, Any] = {}
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[req.key] = req.value
    os.makedirs(prompts_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return ConfigResponse(success=True, message=f"Prompt {category}.{req.key} updated")


@router.get("/services", response_model=ConfigResponse)
async def get_services(_: Any = Depends(_require_admin)) -> ConfigResponse:
    """返回各核心服务的真实健康状态。"""
    import importlib

    from app.llm import list_available_llm_models

    # LLM: 尝试拉取可用模型列表
    llm_status = "unknown"
    try:
        models = await list_available_llm_models()
        llm_status = "ready" if models else "degraded"
    except Exception:
        llm_status = "down"

    # ASR: 检查模块可用性和配置
    asr_status = "unknown"
    try:
        has_transformers = bool(importlib.import_module("transformers"))
        asr_status = "ready" if (settings.enable_asr and has_transformers) else "disabled"
    except Exception:
        asr_status = "down" if settings.enable_asr else "disabled"

    # TTS: 尝试合成一个短文本探测后端
    tts_status = "unknown"
    try:
        from app.tts import synthesize_tts_wav

        wav = synthesize_tts_wav("hello")
        tts_status = "ready" if wav else "degraded"
    except Exception:
        tts_status = "down"

    # OCR: 检查后端依赖
    ocr_status = "unknown"
    try:
        has_paddle = bool(importlib.import_module("paddleocr"))
        ocr_status = "ready" if has_paddle else "degraded"
    except Exception:
        try:
            has_rapid = bool(importlib.import_module("rapidocr"))
            ocr_status = "ready" if has_rapid else "down"
        except Exception:
            ocr_status = "down"

    return ConfigResponse(
        success=True,
        data={
            "status": {
                "llm": llm_status,
                "asr": asr_status,
                "tts": tts_status,
                "ocr": ocr_status,
            },
            "config": {
                "llm_base_url": settings.llm_base_url,
                "llm_model": settings.llm_model,
                "asr_backend": settings.asr_backend,
                "tts_backend": settings.tts_backend,
            },
        },
    )


@router.get("/backups", response_model=BackupResponse)
async def list_backups(_: Any = Depends(_require_admin)) -> BackupResponse:
    backup_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backups")
    backups: list[dict[str, Any]] = []
    if os.path.isdir(backup_dir):
        for fname in sorted(os.listdir(backup_dir)):
            fpath = os.path.join(backup_dir, fname)
            if os.path.isfile(fpath):
                backups.append(
                    {
                        "filename": fname,
                        "size": os.path.getsize(fpath),
                        "created_at": datetime.fromtimestamp(
                            os.path.getctime(fpath)
                        ).isoformat(),
                    }
                )
    return BackupResponse(success=True, data=backups)


@router.post("/backups", response_model=BackupResponse)
async def create_backup(_: Any = Depends(_require_admin)) -> BackupResponse:
    backup_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    db_path = settings.database_url.replace("sqlite:///./", "")
    db_path_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", db_path))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_manual_{timestamp}.db"
    dest = os.path.join(backup_dir, filename)
    if os.path.exists(db_path_abs):
        shutil.copy2(db_path_abs, dest)
    return BackupResponse(success=True, message="Backup created", data=[{"filename": filename}])


@router.post("/backups/restore", response_model=BackupResponse)
async def restore_backup(
    body: dict,
    _: Any = Depends(_require_admin),
) -> BackupResponse:
    filename = body.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    backup_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backups")
    src = os.path.join(backup_dir, filename)
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="Backup not found")
    db_path = settings.database_url.replace("sqlite:///./", "")
    db_path_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", db_path))
    # 恢复前自动快照
    if os.path.exists(db_path_abs):
        snap_name = f"auto_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(db_path_abs, os.path.join(backup_dir, snap_name))
    shutil.copy2(src, db_path_abs)
    return BackupResponse(
        success=True, message="Backup restored. Please restart the server to take effect."
    )


@router.get("/logs", response_model=LogResponse)
async def get_logs(_: Any = Depends(_require_admin)) -> LogResponse:
    log_path = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "app.log")
    lines: list[str] = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()[-100:]
    return LogResponse(success=True, data=lines)


@router.delete("/logs", response_model=LogResponse)
async def clear_logs(_: Any = Depends(_require_admin)) -> LogResponse:
    log_path = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "app.log")
    if os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8"):
            pass
    return LogResponse(success=True, message="Logs cleared")


@router.get("/system-stats", response_model=SystemStatsResponse)
async def get_system_stats(_: Any = Depends(_require_admin)) -> SystemStatsResponse:
    import platform

    import psutil

    mem = psutil.virtual_memory()
    stats = {
        "platform": platform.system(),
        "arch": platform.machine(),
        "cpus": psutil.cpu_count(logical=True),
        "totalMem": mem.total,
        "freeMem": mem.available,
        "uptime": int(datetime.now().timestamp() - psutil.boot_time()),
        "loadAvg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else [],
        "process": {
            "uptime": int(datetime.now().timestamp() - psutil.Process().create_time()),
            "memoryUsage": psutil.Process().memory_info()._asdict(),
            "pid": os.getpid(),
        },
    }
    return SystemStatsResponse(success=True, data=stats)


@router.post("/cleanup", response_model=ConfigResponse)
async def cleanup(
    body: dict,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    max_age_ms = body.get("maxAgeMs", 24 * 60 * 60 * 1000)
    temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "temp")
    cutoff = datetime.now().timestamp() - (max_age_ms / 1000.0)
    removed = 0
    if os.path.isdir(temp_dir):
        for root, _dirs, files in os.walk(temp_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                        removed += 1
                except Exception:
                    pass
    return ConfigResponse(success=True, data={"removed": removed})


@router.get("/users", response_model=UserListResponse)
async def admin_list_users(
    limit: int = 50,
    offset: int = 0,
    _: Any = Depends(_require_admin),
) -> UserListResponse:
    users, total = list_users(limit=limit, offset=offset)
    return UserListResponse(
        success=True,
        data={
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "created_at": u.created_at.isoformat(),
                    "updated_at": u.updated_at.isoformat(),
                }
                for u in users
            ],
            "total": total,
        },
    )


@router.post("/users/{user_id}/reset-password", response_model=ConfigResponse)
async def reset_user_password(
    user_id: int,
    body: dict,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    new_password = body.get("password", "")
    if not new_password:
        raise HTTPException(status_code=400, detail="Missing password")
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    update_user_password(user_id, hash_password(new_password))
    return ConfigResponse(success=True, message="Password reset")


@router.post("/users/{user_id}/role", response_model=ConfigResponse)
async def update_user_role(
    user_id: int,
    body: dict,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    new_role = body.get("role", "").strip()
    if not new_role:
        raise HTTPException(status_code=400, detail="Missing role")
    if new_role not in {"student", "teacher", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    from ..infrastructure.db_user import get_user_by_id

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    from sqlmodel import Session

    from ..db import get_engine

    with Session(get_engine()) as session:
        session.add(user)
        session.commit()
    return ConfigResponse(success=True, message="Role updated")


@router.delete("/users/{user_id}", response_model=ConfigResponse)
async def admin_delete_user(
    user_id: int,
    _: Any = Depends(_require_admin),
) -> ConfigResponse:
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    delete_user(user_id)
    return ConfigResponse(success=True, message="User deleted")
