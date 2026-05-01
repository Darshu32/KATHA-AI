"""Stage 7 unit tests — storage abstraction.

These tests exercise :class:`LocalStorageBackend` against a temp
directory. The S3 backend is not exercised here (boto3 + a real
endpoint required); its contract matches LocalStorageBackend.
"""

from __future__ import annotations

import pytest

from app.storage import LocalStorageBackend, StorageError
from app.storage.local import _sanitise_key


# ─────────────────────────────────────────────────────────────────────
# _sanitise_key
# ─────────────────────────────────────────────────────────────────────


def test_sanitise_key_lowercases_and_keeps_safe_chars():
    assert _sanitise_key("Uploads/2026/Photo.JPG") == "uploads/2026/photo.jpg"


def test_sanitise_key_strips_leading_slash():
    assert _sanitise_key("/uploads/file.png") == "uploads/file.png"


def test_sanitise_key_replaces_unsafe_chars():
    out = _sanitise_key("uploads/silly name!@#.png")
    assert "!" not in out
    assert "@" not in out
    assert "#" not in out
    assert " " not in out


def test_sanitise_key_rejects_dot_dot_traversal():
    with pytest.raises(StorageError):
        _sanitise_key("../etc/passwd")
    with pytest.raises(StorageError):
        _sanitise_key("uploads/../etc/passwd")


def test_sanitise_key_rejects_empty():
    with pytest.raises(StorageError):
        _sanitise_key("")


def test_sanitise_key_rejects_null_byte():
    with pytest.raises(StorageError):
        _sanitise_key("ok\x00name")


# ─────────────────────────────────────────────────────────────────────
# LocalStorageBackend
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def local_backend(tmp_path):
    return LocalStorageBackend(root=tmp_path)


async def test_local_backend_round_trips_bytes(local_backend):
    key = "uploads/test/sample.png"
    payload = b"PNG-bytes-go-here"
    asset = await local_backend.put_bytes(
        key=key, data=payload, mime_type="image/png",
    )
    assert asset.size_bytes == len(payload)
    assert asset.mime_type == "image/png"

    got = await local_backend.get_bytes(key)
    assert got == payload


async def test_local_backend_overwrites_same_key(local_backend):
    key = "u/k.png"
    await local_backend.put_bytes(key=key, data=b"v1", mime_type="image/png")
    await local_backend.put_bytes(key=key, data=b"v2-longer", mime_type="image/png")
    assert await local_backend.get_bytes(key) == b"v2-longer"


async def test_local_backend_get_missing_raises(local_backend):
    with pytest.raises(StorageError):
        await local_backend.get_bytes("not/here.png")


async def test_local_backend_delete_is_idempotent(local_backend):
    key = "u/del.png"
    await local_backend.put_bytes(key=key, data=b"x", mime_type="image/png")
    assert await local_backend.exists(key)
    await local_backend.delete(key)
    assert not await local_backend.exists(key)
    # Second delete is a no-op.
    await local_backend.delete(key)


async def test_local_backend_path_traversal_blocked(local_backend):
    with pytest.raises(StorageError):
        await local_backend.put_bytes(
            key="../escape.png",
            data=b"x",
            mime_type="image/png",
        )


async def test_local_backend_presigned_url_returns_none(local_backend):
    """LocalStorageBackend doesn't presign — clients fall back to the
    proxy route."""
    url = await local_backend.presigned_url("any/key.png")
    assert url is None


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────


def test_factory_returns_local_backend_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.storage.factory import (
        get_storage_backend,
        reset_storage_backend_for_tests,
    )
    reset_storage_backend_for_tests()
    backend = get_storage_backend()
    assert backend.name == "local"


def test_factory_unknown_backend_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "phantom")
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.storage.factory import (
        get_storage_backend,
        reset_storage_backend_for_tests,
    )
    reset_storage_backend_for_tests()
    backend = get_storage_backend()
    assert backend.name == "local"
