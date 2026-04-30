"""Stage 4G integration tests — orchestration of the generation pipeline.

The underlying pipeline functions hit the AI orchestrator (LLM) and
the DB. Tests **monkeypatch** each pipeline function with a
deterministic fake, so they exercise the wrapper logic without
external services.

Coverage:

- Project-scope guard: every tool refuses to run without ctx.project_id.
- Wiring: input fields → pipeline call → result shape → tool output.
- Slim summarisation of graph_data and estimate.
- Service-error → ToolError envelope translation.
- Validator integration: latest version pulled, report fields surfaced.
- list_design_versions returns metadata in newest-first order.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx_no_project(db_session):
    """Context without a project_id — used to verify the scope guard."""
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4g")


@pytest.fixture
async def ctx(db_session):
    """Context with a project_id — required for every pipeline tool."""
    from app.agents.tool import ToolContext
    return ToolContext(
        session=db_session,
        actor_id=None,
        project_id="test-project-123",
        request_id="t4g",
    )


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


def _stub_graph(theme: str = "modern") -> dict:
    """Canonical stub design graph — what the pipeline returns."""
    return {
        "room": {
            "type": "living_room",
            "dimensions": {"length": 5.0, "width": 4.0, "height": 2.7},
        },
        "objects": [
            {"id": "obj-1", "type": "sofa"},
            {"id": "obj-2", "type": "coffee_table"},
        ],
        "materials": [{"name": "walnut"}],
        "style": {"primary": theme},
    }


# ─────────────────────────────────────────────────────────────────────
# Project-scope guard
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name,raw", [
    ("generate_initial_design",
        {"prompt": "design me a living room please"}),
    ("apply_theme", {"new_style": "scandinavian"}),
    ("edit_design_object",
        {"object_id": "obj-1", "edit_prompt": "make this longer"}),
    ("list_design_versions", {}),
    ("validate_current_design", {}),
])
async def test_each_pipeline_tool_requires_project_id(tool_name, raw, ctx_no_project):
    """Every tool refuses to run when project_id is absent on ctx."""
    result = await _call(tool_name, raw, ctx_no_project)
    assert result["ok"] is False
    assert "project_id" in result["error"]["message"].lower()


# ─────────────────────────────────────────────────────────────────────
# generate_initial_design — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_generate_initial_design_happy_path(monkeypatch, ctx):
    captured = {}

    async def fake(*, db, project_id, prompt, room_type, style, **kwargs):
        captured["project_id"] = project_id
        captured["prompt"] = prompt
        captured["room_type"] = room_type
        captured["style"] = style
        captured["kwargs"] = kwargs
        return {
            "project_id": project_id,
            "version": 1,
            "version_id": "ver-1",
            "graph_data": _stub_graph(theme=style),
            "estimate": {"total": 250000, "currency": "INR"},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation",
        fake,
    )

    result = await _call(
        "generate_initial_design",
        {
            "prompt": "Modern living room with walnut and brass",
            "room_type": "living_room",
            "style": "modern",
            "camera": "eye_level",
            "lighting": "daylight",
        },
        ctx,
    )

    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["project_id"] == "test-project-123"
    assert out["version"] == 1
    assert out["change_type"] == "initial"
    assert out["status"] == "completed"
    assert out["graph_summary"]["object_count"] == 2
    assert out["graph_summary"]["style_primary"] == "modern"
    assert out["estimate_summary"]["total"] == 250000
    # Full graph preserved for chaining.
    assert out["full_graph_data"]["room"]["type"] == "living_room"
    # Wiring sanity.
    assert captured["project_id"] == "test-project-123"
    assert captured["style"] == "modern"
    assert captured["kwargs"]["camera"] == "eye_level"
    assert captured["kwargs"]["lighting"] == "daylight"


async def test_generate_initial_design_short_prompt_rejected(ctx):
    """min_length=10 — a one-word prompt must fail validation."""
    result = await _call(
        "generate_initial_design",
        {"prompt": "hi"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_generate_initial_design_orchestrator_error_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    async def fake(**kwargs):
        raise RuntimeError("orchestrator returned malformed output")

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation",
        fake,
    )

    result = await _call(
        "generate_initial_design",
        {"prompt": "design a bedroom please for me"},
        ctx,
    )
    assert result["ok"] is False
    assert "malformed" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# apply_theme — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_apply_theme_happy_path(monkeypatch, ctx):
    captured = {}

    async def fake(*, db, project_id, new_style, preserve_layout):
        captured["project_id"] = project_id
        captured["new_style"] = new_style
        captured["preserve_layout"] = preserve_layout
        return {
            "project_id": project_id,
            "version": 2,
            "version_id": "ver-2",
            "graph_data": _stub_graph(theme=new_style),
            "estimate": {"total": 280000, "currency": "INR"},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_theme_switch",
        fake,
    )

    result = await _call(
        "apply_theme",
        {"new_style": "scandinavian", "preserve_layout": False},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["version"] == 2
    assert out["change_type"] == "theme_switch"
    assert out["graph_summary"]["style_primary"] == "scandinavian"
    assert captured["preserve_layout"] is False


async def test_apply_theme_no_versions_surfaces_as_tool_error(monkeypatch, ctx):
    async def fake(**kwargs):
        raise ValueError(f"No versions found for project {kwargs['project_id']}")

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_theme_switch",
        fake,
    )

    result = await _call(
        "apply_theme",
        {"new_style": "industrial"},
        ctx,
    )
    assert result["ok"] is False
    assert "No versions found" in result["error"]["message"]


async def test_apply_theme_default_preserve_layout_true(monkeypatch, ctx):
    captured = {}

    async def fake(**kwargs):
        captured["preserve_layout"] = kwargs["preserve_layout"]
        return {
            "project_id": kwargs["project_id"],
            "version": 2,
            "version_id": "ver-2",
            "graph_data": _stub_graph(),
            "estimate": {},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_theme_switch",
        fake,
    )

    await _call("apply_theme", {"new_style": "luxe"}, ctx)
    assert captured["preserve_layout"] is True


# ─────────────────────────────────────────────────────────────────────
# edit_design_object — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_edit_design_object_happy_path(monkeypatch, ctx):
    captured = {}

    async def fake(*, db, project_id, object_id, edit_prompt):
        captured["object_id"] = object_id
        captured["edit_prompt"] = edit_prompt
        return {
            "project_id": project_id,
            "version": 3,
            "version_id": "ver-3",
            "graph_data": _stub_graph(),
            "estimate": {"total": 245000, "currency": "INR"},
            "changed_objects": [object_id],
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_local_edit",
        fake,
    )

    result = await _call(
        "edit_design_object",
        {"object_id": "obj-1", "edit_prompt": "make this 1.8 m long"},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["version"] == 3
    assert out["change_type"] == "prompt_edit"
    assert out["changed_object_ids"] == ["obj-1"]
    assert captured["object_id"] == "obj-1"
    assert captured["edit_prompt"] == "make this 1.8 m long"


async def test_edit_design_object_short_prompt_rejected(ctx):
    """edit_prompt min_length=5 — a 2-char prompt must fail."""
    result = await _call(
        "edit_design_object",
        {"object_id": "obj-1", "edit_prompt": "go"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# list_design_versions — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_list_design_versions_happy_path(monkeypatch, ctx):
    """Build a list of fake DesignGraphVersion-shaped objects, return them."""

    class FakeVersion:
        def __init__(self, version, change_type, change_summary, vid="ver"):
            self.version = version
            self.id = vid
            self.change_type = change_type
            self.change_summary = change_summary
            self.changed_object_ids = []
            self.created_at = None  # exercises the "no isoformat" fallback

    async def fake(db, project_id):
        return [
            FakeVersion(3, "prompt_edit", "Edited obj-1", vid="ver-3"),
            FakeVersion(2, "theme_switch", "Theme switched to luxe", vid="ver-2"),
            FakeVersion(1, "initial", "Initial generation", vid="ver-1"),
        ]

    monkeypatch.setattr("app.agents.tools.pipeline.list_versions", fake)

    result = await _call("list_design_versions", {}, ctx)
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["project_id"] == "test-project-123"
    assert out["version_count"] == 3
    assert out["latest_version"] == 3
    # Newest first.
    assert [v["version"] for v in out["versions"]] == [3, 2, 1]
    assert out["versions"][0]["change_type"] == "prompt_edit"
    # created_at degrades gracefully when absent.
    assert out["versions"][0]["created_at"] is None


async def test_list_design_versions_empty_project(monkeypatch, ctx):
    async def fake(db, project_id):
        return []

    monkeypatch.setattr("app.agents.tools.pipeline.list_versions", fake)

    result = await _call("list_design_versions", {}, ctx)
    assert result["ok"]
    out = result["output"]
    assert out["version_count"] == 0
    assert out["latest_version"] == 0
    assert out["versions"] == []


# ─────────────────────────────────────────────────────────────────────
# validate_current_design — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_validate_current_design_no_versions_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    async def fake(db, project_id):
        return None

    monkeypatch.setattr("app.agents.tools.pipeline.get_latest_version", fake)

    result = await _call("validate_current_design", {}, ctx)
    assert result["ok"] is False
    assert "No design-graph versions" in result["error"]["message"]


async def test_validate_current_design_happy_path(monkeypatch, ctx):
    captured = {}

    class FakeLatest:
        version = 5
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeLatest()

    def fake_validate(graph, *, segment):
        captured["segment"] = segment
        captured["object_count"] = len(graph.get("objects", []))
        return {
            "ok": False,
            "errors": [
                {"code": "NBC_VIOLATION", "path": "room.dimensions",
                 "message": "Room area below NBC minimum"},
            ],
            "warnings": [
                {"code": "DOOR_TOO_NARROW", "path": "objects[door-1].width",
                 "message": "Door narrower than NBC clearance"},
            ],
            "suggestions": [
                {"code": "THEME_PALETTE_DRIFT", "path": "materials",
                 "message": "Walnut not in scandinavian palette"},
            ],
            "summary": "1 error(s), 1 warning(s), 1 suggestion(s).",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline.get_latest_version", fake_latest,
    )
    monkeypatch.setattr(
        "app.agents.tools.pipeline._validate_design_graph", fake_validate,
    )

    result = await _call(
        "validate_current_design",
        {"segment": "commercial"},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["version"] == 5
    assert out["ok"] is False
    assert out["error_count"] == 1
    assert out["warning_count"] == 1
    assert out["suggestion_count"] == 1
    assert out["errors"][0]["code"] == "NBC_VIOLATION"
    assert out["warnings"][0]["code"] == "DOOR_TOO_NARROW"
    # Segment passed through.
    assert captured["segment"] == "commercial"
    assert captured["object_count"] == 2


async def test_validate_current_design_default_segment_residential(monkeypatch, ctx):
    captured = {}

    class FakeLatest:
        version = 1
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeLatest()

    def fake_validate(graph, *, segment):
        captured["segment"] = segment
        return {
            "ok": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "summary": "0 error(s), 0 warning(s), 0 suggestion(s).",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline.get_latest_version", fake_latest,
    )
    monkeypatch.setattr(
        "app.agents.tools.pipeline._validate_design_graph", fake_validate,
    )

    await _call("validate_current_design", {}, ctx)
    assert captured["segment"] == "residential"
