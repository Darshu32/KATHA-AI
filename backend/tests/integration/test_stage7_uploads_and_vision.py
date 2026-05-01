"""Stage 7 integration tests — uploads + vision end-to-end.

Real Postgres, real (local-disk) storage, stub vision provider so
no Anthropic call goes out. Covers:

- Upload repo lifecycle (create → mark_status → list → delete).
- Owner guard isolates users — cross-owner reads return None.
- Vision analyzer end-to-end with a real on-disk asset.
- Each of the 5 vision agent tools through ``call_tool``.
- Owner-mismatch on vision tool returns ToolError, not a crash.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


# 1×1 PNG — minimal valid bytes the storage backend will accept.
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000"
    "00907753de0000000c4944415408d76360000000000004000180b25cf60000000049454e44ae426082"
)


async def _seed_user(session, *, email: str) -> str:
    from app.models.orm import User

    u = User(
        email=email,
        hashed_password="x",
        display_name="S7 test",
        is_active=True,
    )
    session.add(u)
    await session.flush()
    return u.id


async def _create_asset(
    session,
    backend,
    *,
    owner_id: str,
    project_id: str | None = None,
    kind: str = "image",
    payload: bytes = _PNG_1X1,
    mime: str = "image/png",
    filename: str = "fixture.png",
):
    from app.repositories.uploads import UploadRepository

    storage_key = f"uploads/test/{owner_id}/{filename}"
    row = await UploadRepository.create(
        session,
        owner_id=owner_id,
        project_id=project_id,
        kind=kind,
        storage_backend=backend.name,
        storage_key=storage_key,
        original_filename=filename,
        mime_type=mime,
        size_bytes=len(payload),
        content_hash="testhash",
        status="uploading",
    )
    await backend.put_bytes(key=storage_key, data=payload, mime_type=mime)
    await UploadRepository.mark_status(
        session, asset_id=row.id, status="ready",
    )
    return row


@pytest.fixture
def local_backend(tmp_path):
    from app.storage import LocalStorageBackend
    from app.storage.factory import reset_storage_backend_for_tests

    reset_storage_backend_for_tests()
    backend = LocalStorageBackend(root=tmp_path / "uploads")
    return backend


@pytest.fixture
def patched_storage(monkeypatch, local_backend):
    """Make ``get_storage_backend()`` return our temp-dir local backend."""
    monkeypatch.setattr(
        "app.storage.factory.get_storage_backend",
        lambda: local_backend,
    )
    # The vision analyzer + upload route both import via this path.
    monkeypatch.setattr(
        "app.vision.analyzer.get_storage_backend",
        lambda: local_backend,
    )
    monkeypatch.setattr(
        "app.routes.uploads.get_storage_backend",
        lambda: local_backend,
    )
    return local_backend


# ─────────────────────────────────────────────────────────────────────
# Upload repo
# ─────────────────────────────────────────────────────────────────────


async def test_upload_repo_create_then_mark_ready(db_session, patched_storage):
    from app.repositories.uploads import UploadRepository

    user_id = await _seed_user(db_session, email="s7-create@example.com")
    row = await _create_asset(
        db_session, patched_storage, owner_id=user_id, kind="site_photo",
    )
    assert row.status == "ready"
    assert row.kind == "site_photo"
    assert row.size_bytes == len(_PNG_1X1)


async def test_owner_guard_isolates_users(db_session, patched_storage):
    from app.repositories.uploads import UploadRepository

    a_id = await _seed_user(db_session, email="s7-owner-a@example.com")
    b_id = await _seed_user(db_session, email="s7-owner-b@example.com")

    row = await _create_asset(db_session, patched_storage, owner_id=a_id)

    found = await UploadRepository.get_for_owner(
        db_session, asset_id=row.id, owner_id=a_id,
    )
    assert found is not None

    not_found = await UploadRepository.get_for_owner(
        db_session, asset_id=row.id, owner_id=b_id,
    )
    assert not_found is None


async def test_list_for_owner_filters(db_session, patched_storage):
    from app.repositories.uploads import UploadRepository

    user_id = await _seed_user(db_session, email="s7-list@example.com")
    await _create_asset(
        db_session, patched_storage, owner_id=user_id,
        kind="site_photo", filename="a.png",
    )
    await _create_asset(
        db_session, patched_storage, owner_id=user_id,
        kind="reference", filename="b.png",
    )

    site = await UploadRepository.list_for_owner(
        db_session, owner_id=user_id, kind="site_photo",
    )
    assert all(r.kind == "site_photo" for r in site)
    assert len(site) >= 1


async def test_delete_for_owner_removes_row(db_session, patched_storage):
    from app.repositories.uploads import UploadRepository

    user_id = await _seed_user(db_session, email="s7-del@example.com")
    row = await _create_asset(db_session, patched_storage, owner_id=user_id)
    removed = await UploadRepository.delete_for_owner(
        db_session, asset_id=row.id, owner_id=user_id,
    )
    assert removed is not None
    after = await UploadRepository.get_by_id(db_session, asset_id=row.id)
    assert after is None


# ─────────────────────────────────────────────────────────────────────
# Vision analyzer
# ─────────────────────────────────────────────────────────────────────


async def test_analyzer_round_trips_with_stub_provider(
    db_session, patched_storage,
):
    from app.vision import StubVisionProvider, VisionAnalyzer

    user_id = await _seed_user(db_session, email="s7-analyze@example.com")
    row = await _create_asset(
        db_session, patched_storage, owner_id=user_id, kind="site_photo",
    )

    analyzer = VisionAnalyzer(provider=StubVisionProvider())
    outcome = await analyzer.analyze_assets(
        db_session,
        owner_id=user_id,
        asset_ids=[row.id],
        purpose="site_photo",
    )
    assert outcome.purpose == "site_photo"
    assert outcome.provider == "stub_vision"
    assert "summary" in outcome.parsed
    assert "orientation" in outcome.parsed
    assert outcome.assets[0].asset_id == row.id


async def test_analyzer_rejects_cross_owner_assets(
    db_session, patched_storage,
):
    from app.vision import StubVisionProvider, VisionAnalyzeError, VisionAnalyzer

    a_id = await _seed_user(db_session, email="s7-cross-a@example.com")
    b_id = await _seed_user(db_session, email="s7-cross-b@example.com")
    row = await _create_asset(db_session, patched_storage, owner_id=a_id)

    analyzer = VisionAnalyzer(provider=StubVisionProvider())
    with pytest.raises(VisionAnalyzeError):
        await analyzer.analyze_assets(
            db_session,
            owner_id=b_id,
            asset_ids=[row.id],
            purpose="site_photo",
        )


async def test_analyzer_rejects_unknown_purpose(db_session, patched_storage):
    from app.vision import StubVisionProvider, VisionAnalyzeError, VisionAnalyzer

    user_id = await _seed_user(db_session, email="s7-bad-purpose@example.com")
    row = await _create_asset(db_session, patched_storage, owner_id=user_id)

    analyzer = VisionAnalyzer(provider=StubVisionProvider())
    with pytest.raises(VisionAnalyzeError):
        await analyzer.analyze_assets(
            db_session,
            owner_id=user_id,
            asset_ids=[row.id],
            purpose="phantom_purpose",
        )


async def test_analyzer_rejects_uploading_status(
    db_session, patched_storage,
):
    """An asset that's still in 'uploading' state must not be analysed."""
    from app.repositories.uploads import UploadRepository
    from app.vision import StubVisionProvider, VisionAnalyzeError, VisionAnalyzer

    user_id = await _seed_user(db_session, email="s7-uploading@example.com")
    row = await _create_asset(db_session, patched_storage, owner_id=user_id)
    # Force back to 'uploading' to simulate a not-yet-finalised upload.
    await UploadRepository.mark_status(
        db_session, asset_id=row.id, status="uploading",
    )

    analyzer = VisionAnalyzer(provider=StubVisionProvider())
    with pytest.raises(VisionAnalyzeError):
        await analyzer.analyze_assets(
            db_session,
            owner_id=user_id,
            asset_ids=[row.id],
            purpose="site_photo",
        )


# ─────────────────────────────────────────────────────────────────────
# Vision agent tools — end-to-end via call_tool
# ─────────────────────────────────────────────────────────────────────


async def test_analyze_image_tool_e2e(monkeypatch, db_session, patched_storage):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.vision import StubVisionProvider

    # Force StubVisionProvider for the analyzer-init path.
    monkeypatch.setattr(
        "app.vision.factory.get_vision_provider",
        lambda: StubVisionProvider(),
    )
    monkeypatch.setattr(
        "app.vision.analyzer.get_vision_provider",
        lambda: StubVisionProvider(),
    )

    ensure_tools_registered()

    user_id = await _seed_user(db_session, email="s7-analyze-tool@example.com")
    row = await _create_asset(
        db_session, patched_storage, owner_id=user_id, kind="image",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s7-analyze",
    )
    result = await call_tool(
        "analyze_image",
        {"asset_id": row.id, "purpose": "reference"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["purpose"] == "reference"
    assert out["provider"] == "stub_vision"
    assert "summary" in out["parsed"]
    assert out["assets"][0]["asset_id"] == row.id


async def test_analyze_image_unknown_purpose_returns_tool_error(
    monkeypatch, db_session, patched_storage,
):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.vision import StubVisionProvider

    monkeypatch.setattr(
        "app.vision.factory.get_vision_provider",
        lambda: StubVisionProvider(),
    )
    monkeypatch.setattr(
        "app.vision.analyzer.get_vision_provider",
        lambda: StubVisionProvider(),
    )
    ensure_tools_registered()

    user_id = await _seed_user(db_session, email="s7-bad-purpose-tool@example.com")
    row = await _create_asset(db_session, patched_storage, owner_id=user_id)

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s7-bad",
    )
    result = await call_tool(
        "analyze_image",
        {"asset_id": row.id, "purpose": "phantom"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "phantom" in result["error"]["message"].lower()


async def test_analyze_image_requires_actor(db_session, patched_storage):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    ctx = ToolContext(
        session=db_session, actor_id=None, request_id="s7-noactor",
    )
    result = await call_tool(
        "analyze_image",
        {"asset_id": "some-id", "purpose": "site_photo"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "actor" in result["error"]["message"].lower()


@pytest.mark.parametrize("tool_name,purpose,kind", [
    ("analyze_site_photo", "site_photo", "site_photo"),
    ("sketch_to_floor_plan", "hand_sketch", "hand_sketch"),
    ("digitize_floor_plan", "existing_floor_plan", "existing_floor_plan"),
])
async def test_specialized_tools_route_to_right_purpose(
    monkeypatch, db_session, patched_storage,
    tool_name, purpose, kind,
):
    """Sugar tools wrap analyze_image with a fixed purpose. Verify
    each one ends up dispatched to the right StubVisionProvider
    fixture."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.vision import StubVisionProvider

    provider = StubVisionProvider()
    monkeypatch.setattr(
        "app.vision.factory.get_vision_provider", lambda: provider,
    )
    monkeypatch.setattr(
        "app.vision.analyzer.get_vision_provider", lambda: provider,
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email=f"s7-{purpose}@example.com")
    row = await _create_asset(
        db_session, patched_storage, owner_id=user_id, kind=kind,
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id=f"s7-{purpose}",
    )
    result = await call_tool(
        tool_name,
        {"asset_id": row.id},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["purpose"] == purpose


async def test_extract_aesthetic_dispatches_mood_board_when_multiple_images(
    monkeypatch, db_session, patched_storage,
):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.vision import StubVisionProvider

    provider = StubVisionProvider()
    monkeypatch.setattr(
        "app.vision.factory.get_vision_provider", lambda: provider,
    )
    monkeypatch.setattr(
        "app.vision.analyzer.get_vision_provider", lambda: provider,
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s7-mood@example.com")
    row1 = await _create_asset(
        db_session, patched_storage, owner_id=user_id,
        kind="reference", filename="ref1.png",
    )
    row2 = await _create_asset(
        db_session, patched_storage, owner_id=user_id,
        kind="reference", filename="ref2.png",
    )
    row3 = await _create_asset(
        db_session, patched_storage, owner_id=user_id,
        kind="reference", filename="ref3.png",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s7-mood",
    )
    result = await call_tool(
        "extract_aesthetic",
        {"asset_ids": [row1.id, row2.id, row3.id]},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["purpose"] == "mood_board"
    assert len(out["assets"]) == 3


async def test_extract_aesthetic_uses_reference_when_one_image(
    monkeypatch, db_session, patched_storage,
):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.vision import StubVisionProvider

    provider = StubVisionProvider()
    monkeypatch.setattr(
        "app.vision.factory.get_vision_provider", lambda: provider,
    )
    monkeypatch.setattr(
        "app.vision.analyzer.get_vision_provider", lambda: provider,
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s7-ref-one@example.com")
    row = await _create_asset(
        db_session, patched_storage, owner_id=user_id, kind="reference",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s7-ref-one",
    )
    result = await call_tool(
        "extract_aesthetic",
        {"asset_ids": [row.id]},
        ctx, registry=REGISTRY,
    )
    assert result["ok"]
    assert result["output"]["purpose"] == "reference"
