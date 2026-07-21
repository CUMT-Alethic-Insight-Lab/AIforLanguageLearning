"""Optional static hosting boundary for the built Vue frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_NON_SPA_PATH_ROOTS = {
    "api",
    "assets",
    "docs",
    "health",
    "metrics",
    "openapi.json",
    "redoc",
    "v1",
    "ws",
}


def _default_dist_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "app" / "v5" / "dist"


def _validated_dist_dir(dist_dir: Path | None) -> tuple[Path, Path] | None:
    resolved_dist = Path(dist_dir or _default_dist_dir()).resolve()
    index_html = resolved_dist / "index.html"

    if not resolved_dist.is_dir() or not index_html.is_file():
        return None

    resolved_index = index_html.resolve()
    try:
        resolved_index.relative_to(resolved_dist)
    except ValueError:
        return None
    return resolved_dist, resolved_index


def _is_non_spa_path(full_path: str) -> bool:
    root = full_path.lstrip("/").split("/", 1)[0]
    return root in _NON_SPA_PATH_ROOTS


def _safe_static_file(dist_dir: Path, full_path: str) -> Path | None:
    candidate = (dist_dir / full_path).resolve()
    try:
        candidate.relative_to(dist_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def mount_static_frontend(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """Mount a validated Vue dist, returning ``False`` when no build is available.

    The SPA fallback is intentionally limited to browser routes. Backend namespaces
    and missing file-like paths remain 404s so deployment and API errors stay visible.
    This function must be called after backend routes are registered.
    """
    validated = _validated_dist_dir(dist_dir)
    if validated is None:
        return False

    resolved_dist, index_html = validated
    assets_dir = (resolved_dist / "assets").resolve()
    if assets_dir.is_dir():
        try:
            assets_dir.relative_to(resolved_dist)
        except ValueError:
            pass
        else:
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir), check_dir=True),
                name="frontend_assets",
            )

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(index_html)

    @app.middleware("http")
    async def frontend_spa_fallback(request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.method != "GET" or response.status_code != 404:
            return response

        full_path = request.url.path.lstrip("/")
        if _is_non_spa_path(full_path):
            return response

        static_file = _safe_static_file(resolved_dist, full_path)
        if static_file is not None:
            return FileResponse(static_file)

        if Path(full_path).suffix:
            return response
        return FileResponse(index_html)

    return True
