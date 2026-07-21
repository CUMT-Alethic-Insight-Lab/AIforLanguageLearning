"""Tests for the optional static frontend hosting boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_frontend import _safe_static_file, mount_static_frontend

INDEX_HTML = "<html><body>Hello from Vue</body></html>"


def _create_fake_dist(dist: Path, *, with_assets: bool = True) -> None:
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    if with_assets:
        assets = dist / "assets"
        assets.mkdir()
        (assets / "style.css").write_text("body { color: red; }", encoding="utf-8")


def test_mount_returns_true_when_dist_exists(tmp_path: Path) -> None:
    _create_fake_dist(tmp_path)
    app = FastAPI()

    assert mount_static_frontend(app, dist_dir=tmp_path) is True


def test_root_and_frontend_route_return_index_html(tmp_path: Path) -> None:
    _create_fake_dist(tmp_path)
    app = FastAPI()
    mount_static_frontend(app, dist_dir=tmp_path)
    client = TestClient(app)

    assert client.get("/").text == INDEX_HTML
    response = client.get("/voice/session/42")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_assets_and_root_static_files_are_served(tmp_path: Path) -> None:
    _create_fake_dist(tmp_path)
    (tmp_path / "favicon.ico").write_bytes(b"icon")
    app = FastAPI()
    mount_static_frontend(app, dist_dir=tmp_path)
    client = TestClient(app)

    css_response = client.get("/assets/style.css")
    assert css_response.status_code == 200
    assert css_response.text == "body { color: red; }"
    assert client.get("/favicon.ico").content == b"icon"


@pytest.mark.parametrize(
    "path",
    [
        "/api/unknown",
        "/v1/unknown",
        "/ws/unknown",
        "/health/unknown",
        "/metrics/unknown",
        "/missing.js",
        "/assets/missing",
        "/assets/missing.css",
    ],
)
def test_backend_and_missing_file_paths_do_not_fall_back_to_spa(
    tmp_path: Path, path: str
) -> None:
    _create_fake_dist(tmp_path)
    app = FastAPI()
    mount_static_frontend(app, dist_dir=tmp_path)

    response = TestClient(app).get(path)

    assert response.status_code == 404
    assert INDEX_HTML not in response.text


@pytest.mark.parametrize("register_before_mount", [True, False])
def test_existing_backend_route_keeps_precedence(
    tmp_path: Path, register_before_mount: bool
) -> None:
    _create_fake_dist(tmp_path)
    app = FastAPI()

    def register_health() -> None:
        @app.get("/health")
        async def health() -> dict[str, bool]:
            return {"ok": True}

    if register_before_mount:
        register_health()
    mount_static_frontend(app, dist_dir=tmp_path)
    if not register_before_mount:
        register_health()
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("dist_state", ["missing", "missing_index", "index_directory"])
def test_invalid_dist_is_not_mounted(tmp_path: Path, dist_state: str) -> None:
    dist = tmp_path / "dist"
    if dist_state != "missing":
        dist.mkdir()
    if dist_state == "index_directory":
        (dist / "index.html").mkdir()
    app = FastAPI()

    assert mount_static_frontend(app, dist_dir=dist) is False
    assert TestClient(app).get("/").status_code == 404


def test_path_traversal_is_rejected_by_route_boundary(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _create_fake_dist(dist, with_assets=False)
    outside = tmp_path / "secret.txt"
    outside.write_text("not public", encoding="utf-8")

    assert _safe_static_file(dist.resolve(), "../secret.txt") is None


def test_dist_without_assets_can_still_serve_spa(tmp_path: Path) -> None:
    _create_fake_dist(tmp_path, with_assets=False)
    app = FastAPI()

    assert mount_static_frontend(app, dist_dir=tmp_path) is True
    assert TestClient(app).get("/teacher").text == INDEX_HTML
