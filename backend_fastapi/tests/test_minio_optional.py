"""Tests for MinIO optional dependency handling."""

from __future__ import annotations

import subprocess
import sys
import unittest.mock as mock


class TestMinioModuleImport:
    """Verify that the minio_storage module imports without minio installed."""

    def test_module_imports_without_crash(self):
        """The module itself should import cleanly regardless of minio presence."""
        from app.infrastructure.storage import minio_storage

        assert hasattr(minio_storage, "is_minio_available")
        assert hasattr(minio_storage, "get_minio_storage")
        assert hasattr(minio_storage, "MinIOStorage")

    def test_is_minio_available_returns_bool(self):
        """is_minio_available() must return a bool and never raise."""
        from app.infrastructure.storage.minio_storage import is_minio_available

        result = is_minio_available()
        assert isinstance(result, bool)

    def test_is_minio_available_idempotent(self):
        """Calling is_minio_available multiple times should be safe."""
        from app.infrastructure.storage.minio_storage import is_minio_available

        first = is_minio_available()
        second = is_minio_available()
        assert first == second


class TestMinIOStorageInit:
    """Test MinIOStorage construction behavior."""

    def test_init_raises_runtime_error_when_minio_missing(self):
        """MinIOStorage() must raise RuntimeError (not ImportError) when minio absent."""
        from app.infrastructure.storage.minio_storage import MinIOStorage

        with mock.patch("builtins.__import__", side_effect=ImportError("No module named 'minio'")):
            try:
                MinIOStorage("localhost:9000", "ak", "sk")
            except RuntimeError as e:
                assert "MinIO SDK is not installed" in str(e)
            except ImportError:
                raise AssertionError(
                    "MinIOStorage() must not leak ImportError; should raise RuntimeError"
                )
            else:
                # If minio is installed and import succeeds, that's also fine.
                pass

    def test_init_does_not_require_current_event_loop(self):
        """Construction is synchronous and must not bind to an event loop."""
        from app.infrastructure.storage.minio_storage import (
            MinIOStorage,
            is_minio_available,
        )

        if not is_minio_available():
            import pytest

            pytest.skip("minio SDK not installed in this environment")

        with mock.patch(
            "app.infrastructure.storage.minio_storage.asyncio.get_event_loop",
            side_effect=RuntimeError("There is no current event loop"),
        ):
            storage = MinIOStorage("localhost:9000", "ak", "sk")

        assert storage.client is not None


class TestGetMinioStorage:
    """Test get_minio_storage() behavior."""

    def test_returns_none_when_minio_unavailable(self):
        """get_minio_storage() returns None when minio SDK is absent."""
        # Reset the module-level cache so we re-check availability
        import app.infrastructure.storage.minio_storage as mod

        saved = mod._storage
        mod._storage = None

        try:
            with mock.patch.object(mod, "is_minio_available", return_value=False):
                result = mod.get_minio_storage()
                assert result is None
        finally:
            mod._storage = saved

    def test_returns_instance_when_minio_available(self):
        """get_minio_storage() returns a MinIOStorage when SDK is present."""
        from app.infrastructure.storage.minio_storage import (
            MinIOStorage,
            get_minio_storage,
            is_minio_available,
        )

        # Only meaningful if minio is actually installed
        if not is_minio_available():
            import pytest

            pytest.skip("minio SDK not installed in this environment")

        import app.infrastructure.storage.minio_storage as mod

        saved = mod._storage
        mod._storage = None

        try:
            result = get_minio_storage()
            assert isinstance(result, MinIOStorage)
        finally:
            mod._storage = saved


class TestStorageRouterWithoutMinio:
    """Verify storage router endpoints return 503 without minio."""

    def test_upload_returns_503_when_storage_unavailable(self):
        """POST /api/v1/upload returns 503 when get_minio_storage() is None."""
        from fastapi.testclient import TestClient

        from app.main import app

        # We need to import the router after mocking get_minio_storage.
        # Since the router is already imported at module level elsewhere,
        # we patch at the call site inside the endpoint.
        client = TestClient(app)

        with mock.patch(
            "app.interfaces.storage_router.get_minio_storage", return_value=None
        ):
            resp = client.post(
                "/api/v1/upload",
                files={"file": ("test.txt", b"hello", "text/plain")},
            )
            assert resp.status_code == 503
            assert "not available" in resp.json()["detail"].lower()

    def test_multipart_init_returns_503_when_storage_unavailable(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        with mock.patch(
            "app.interfaces.storage_router.get_minio_storage", return_value=None
        ):
            resp = client.post(
                "/api/v1/upload/multipart/init",
                json={"bucket": "b", "key": "k"},
            )
            assert resp.status_code == 503

    def test_multipart_complete_returns_503_when_storage_unavailable(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        with mock.patch(
            "app.interfaces.storage_router.get_minio_storage", return_value=None
        ):
            resp = client.post(
                "/api/v1/upload/multipart/complete",
                json={"bucket": "b", "key": "k", "upload_id": "u", "parts": []},
            )
            assert resp.status_code == 503

    def test_presigned_url_returns_503_when_storage_unavailable(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        with mock.patch(
            "app.interfaces.storage_router.get_minio_storage", return_value=None
        ):
            resp = client.post(
                "/api/v1/upload/presigned-url",
                json={"bucket": "b", "key": "k"},
            )
            assert resp.status_code == 503


class TestSubprocessImport:
    """Smoke test: importing the module in a subprocess should never crash."""

    def test_import_via_subprocess(self):
        """Running `from app.infrastructure.storage.minio_storage import ...` exits 0."""
        code = (
            "from app.infrastructure.storage.minio_storage import "
            "get_minio_storage, is_minio_available; "
            "print('available:', is_minio_available())"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert "available:" in proc.stdout
