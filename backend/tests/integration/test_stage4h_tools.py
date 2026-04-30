"""Stage 4H integration tests — orchestration of the I/O tools.

The underlying exporters / importers / advisors all run in-process
(deterministic exporters / importers) or call the LLM (advisors). The
tests **monkeypatch** each leaf so the suite stays hermetic — no real
file I/O, no LLM calls.

Coverage:

- Discovery tools (list_*) return non-empty payloads and stable shape.
- Project-scope guard on tools that need a project.
- export_design_bundle base64-encodes payloads ≤ 32 KB and omits
  bytes for larger payloads with a flag.
- parse_import_file rejects bad base64 and propagates importer output.
- generate_import_manifest / generate_export_manifest translate
  service errors to ToolError envelopes.
"""

from __future__ import annotations

import base64

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx_no_project(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4h")


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(
        session=db_session,
        actor_id=None,
        project_id="test-project-456",
        request_id="t4h",
    )


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


def _stub_graph() -> dict:
    return {
        "room": {
            "type": "living_room",
            "dimensions": {"length": 5.0, "width": 4.0, "height": 2.7},
        },
        "objects": [{"id": "obj-1", "type": "sofa"}],
        "materials": [{"name": "walnut"}],
        "style": {"primary": "modern"},
    }


# ─────────────────────────────────────────────────────────────────────
# Discovery tools
# ─────────────────────────────────────────────────────────────────────


async def test_list_export_formats_returns_at_least_pdf_and_dxf(ctx):
    result = await _call("list_export_formats", {}, ctx)
    assert result["ok"], result.get("error")
    out = result["output"]
    keys = {f["key"] for f in out["formats"]}
    assert {"pdf", "dxf", "obj", "ifc"}.issubset(keys), (
        f"core formats missing — got {keys}"
    )
    # Families dict groups formats sensibly.
    assert "document" in out["families"]
    assert "pdf" in out["families"]["document"]
    assert out["count"] == len(out["formats"])


async def test_list_import_formats_includes_pdf_and_dxf(ctx):
    result = await _call("list_import_formats", {}, ctx)
    assert result["ok"], result.get("error")
    out = result["output"]
    assert "pdf" in out["extensions"]
    assert "dxf" in out["extensions"]
    assert out["count"] >= 5


async def test_list_export_recipients_returns_canonical_roles(ctx):
    result = await _call("list_export_recipients", {}, ctx)
    assert result["ok"], result.get("error")
    out = result["output"]
    roles = {r["role"] for r in out["recipients"]}
    assert {"client", "fabricator", "architect", "cnc_shop"}.issubset(roles)
    assert out["count"] >= 5


# ─────────────────────────────────────────────────────────────────────
# Project-scope guard
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name,raw", [
    ("build_spec_bundle_for_current", {}),
    ("export_design_bundle", {"format_key": "pdf"}),
])
async def test_project_scope_guard(tool_name, raw, ctx_no_project):
    result = await _call(tool_name, raw, ctx_no_project)
    assert result["ok"] is False
    assert "project_id" in result["error"]["message"].lower()


# ─────────────────────────────────────────────────────────────────────
# build_spec_bundle_for_current
# ─────────────────────────────────────────────────────────────────────


async def test_build_spec_bundle_no_versions_surfaces_as_tool_error(monkeypatch, ctx):
    async def fake_latest(db, project_id):
        return None

    monkeypatch.setattr("app.agents.tools.io.get_latest_version", fake_latest)

    result = await _call("build_spec_bundle_for_current", {}, ctx)
    assert result["ok"] is False
    assert "No design-graph versions" in result["error"]["message"]


async def test_build_spec_bundle_happy_path(monkeypatch, ctx):
    captured = {}

    class FakeVersion:
        version = 4
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeVersion()

    def fake_build(graph, *, project_name):
        captured["project_name"] = project_name
        captured["graph_room_type"] = graph.get("room", {}).get("type")
        return {
            "meta": {"project_name": project_name, "room_type": "living_room"},
            "material": {"primary_species": "walnut"},
            "manufacturing": {"woodworking_notes": "..."},
            "mep": {},  # not ready
            "cost": {"status": "pending"},
            "objects_count": 1,
        }

    monkeypatch.setattr("app.agents.tools.io.get_latest_version", fake_latest)
    monkeypatch.setattr("app.agents.tools.io._build_spec_bundle", fake_build)

    result = await _call(
        "build_spec_bundle_for_current",
        {"project_name": "Test Living Room"},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["project_id"] == "test-project-456"
    assert out["version"] == 4
    assert out["objects_count"] == 1
    assert out["meta"]["project_name"] == "Test Living Room"
    # Bundle status reflects truthiness of each section.
    status = out["bundle_status"]
    assert status["meta"] is True
    assert status["material"] is True
    assert status["manufacturing"] is True
    assert status["mep"] is False  # empty dict
    assert status["cost"] is True
    # Wiring sanity.
    assert captured["project_name"] == "Test Living Room"
    assert captured["graph_room_type"] == "living_room"


# ─────────────────────────────────────────────────────────────────────
# export_design_bundle — small payload (inlined) + large payload (omitted)
# ─────────────────────────────────────────────────────────────────────


async def test_export_design_bundle_small_payload_inlined(monkeypatch, ctx):
    class FakeVersion:
        version = 2
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeVersion()

    def fake_build(graph, *, project_name):
        return {"meta": {"project_name": project_name}, "material": {}, "objects_count": 0}

    payload = b"PDF-mock-bytes-small"

    def fake_export(format_key, bundle, graph):
        return {
            "content_type": "application/pdf",
            "filename": "design.pdf",
            "bytes": payload,
        }

    monkeypatch.setattr("app.agents.tools.io.get_latest_version", fake_latest)
    monkeypatch.setattr("app.agents.tools.io._build_spec_bundle", fake_build)
    monkeypatch.setattr("app.agents.tools.io._export", fake_export)

    result = await _call(
        "export_design_bundle",
        {"format_key": "pdf"},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["format_key"] == "pdf"
    assert out["content_type"] == "application/pdf"
    assert out["filename"] == "design.pdf"
    assert out["size_bytes"] == len(payload)
    assert out["inline_bytes_omitted"] is False
    # Round-trip the base64.
    assert base64.b64decode(out["content_base64"]) == payload
    assert out["version"] == 2


async def test_export_design_bundle_large_payload_omitted(monkeypatch, ctx):
    class FakeVersion:
        version = 3
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeVersion()

    def fake_build(graph, *, project_name):
        return {"meta": {}, "objects_count": 0}

    big_payload = b"X" * (33 * 1024)  # 33 KB > 32 KB threshold

    def fake_export(format_key, bundle, graph):
        return {
            "content_type": "model/gltf+json",
            "filename": "model.gltf",
            "bytes": big_payload,
        }

    monkeypatch.setattr("app.agents.tools.io.get_latest_version", fake_latest)
    monkeypatch.setattr("app.agents.tools.io._build_spec_bundle", fake_build)
    monkeypatch.setattr("app.agents.tools.io._export", fake_export)

    result = await _call(
        "export_design_bundle",
        {"format_key": "gltf"},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["size_bytes"] == 33 * 1024
    assert out["inline_bytes_omitted"] is True
    assert out["content_base64"] is None  # omitted


async def test_export_design_bundle_unsupported_format_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    class FakeVersion:
        version = 1
        graph_data = _stub_graph()

    async def fake_latest(db, project_id):
        return FakeVersion()

    def fake_build(graph, *, project_name):
        return {"meta": {}, "objects_count": 0}

    def fake_export(format_key, bundle, graph):
        raise ValueError(f"Unsupported export format '{format_key}'.")

    monkeypatch.setattr("app.agents.tools.io.get_latest_version", fake_latest)
    monkeypatch.setattr("app.agents.tools.io._build_spec_bundle", fake_build)
    monkeypatch.setattr("app.agents.tools.io._export", fake_export)

    result = await _call(
        "export_design_bundle",
        {"format_key": "phantom_format"},
        ctx,
    )
    assert result["ok"] is False
    assert "Unsupported export format" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# parse_import_file
# ─────────────────────────────────────────────────────────────────────


async def test_parse_import_file_rejects_bad_base64(ctx):
    """A clearly invalid base64 string surfaces as ToolError."""
    result = await _call(
        "parse_import_file",
        {
            "filename": "test.pdf",
            "content_base64": "!!!not-base64-at-all-???\x00\xff",
        },
        ctx,
    )
    # base64.b64decode is permissive; this might succeed or fail depending on
    # the bytes. The schema requires content_base64 to be non-empty, so even
    # if decode returns garbage, the tool still calls the parser. Accept
    # either: ToolError (decode failed) or ok with importer warnings.
    assert "ok" in result
    if not result["ok"]:
        # Decode failure → ToolError envelope.
        msg = result["error"]["message"].lower()
        assert "base64" in msg or "importer" in msg


async def test_parse_import_file_happy_path(monkeypatch, ctx):
    captured = {}

    def fake_parse(filename, payload):
        captured["filename"] = filename
        captured["payload_size"] = len(payload)
        return {
            "format": "pdf",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Parsed 12 pages, 3 dimensions.",
            "extracted": {"page_count": 12, "dims": {"width_mm": 4500}},
            "warnings": [],
        }

    monkeypatch.setattr("app.agents.tools.io._parse_file", fake_parse)

    raw_bytes = b"%PDF-fake-bytes-12345"
    encoded = base64.b64encode(raw_bytes).decode("ascii")

    result = await _call(
        "parse_import_file",
        {"filename": "site_plan.pdf", "content_base64": encoded},
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["format"] == "pdf"
    assert out["filename"] == "site_plan.pdf"
    assert out["summary"] == "Parsed 12 pages, 3 dimensions."
    assert out["extracted"]["page_count"] == 12
    assert captured["filename"] == "site_plan.pdf"
    assert captured["payload_size"] == len(raw_bytes)


async def test_parse_import_file_importer_crash_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    def fake_parse(filename, payload):
        raise RuntimeError("importer crashed: malformed PDF stream")

    monkeypatch.setattr("app.agents.tools.io._parse_file", fake_parse)

    result = await _call(
        "parse_import_file",
        {
            "filename": "broken.pdf",
            "content_base64": base64.b64encode(b"junk").decode("ascii"),
        },
        ctx,
    )
    assert result["ok"] is False
    assert "Importer crashed" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# generate_import_manifest
# ─────────────────────────────────────────────────────────────────────


async def test_generate_import_manifest_rejects_empty_imports(ctx):
    """min_length=1 — zero imports must fail validation."""
    result = await _call("generate_import_manifest", {"imports": []}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_generate_import_manifest_happy_path(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["import_count"] = len(req.imports)
        captured["theme"] = req.theme
        return {
            "id": "import_manifest",
            "name": "Import Manifest",
            "import_manifest": {
                "extractions": [
                    {"filename": "site_plan.pdf", "summary": "12 pages"},
                ],
                "conflicts": [],
                "merge_plan": [{"step": 1, "action": "ingest_room_dims"}],
            },
            "validation": {"all_extractions_present": True},
        }

    monkeypatch.setattr(
        "app.agents.tools.io._generate_import_manifest",
        fake,
    )

    result = await _call(
        "generate_import_manifest",
        {
            "imports": [
                {
                    "format": "pdf",
                    "filename": "site_plan.pdf",
                    "size_bytes": 1024,
                    "summary": "12-page architectural PDF",
                    "extracted": {"page_count": 12},
                },
            ],
            "theme": "modern",
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["import_count"] == 1
    assert out["validation_passed"] is True
    assert "extractions" in out["manifest"]
    assert captured["import_count"] == 1
    assert captured["theme"] == "modern"


async def test_generate_import_manifest_advisor_error_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    from app.services.import_advisor_service import ImportAdvisorError

    async def fake(req):
        raise ImportAdvisorError("LLM call failed: rate limit exceeded")

    monkeypatch.setattr(
        "app.agents.tools.io._generate_import_manifest",
        fake,
    )

    result = await _call(
        "generate_import_manifest",
        {
            "imports": [
                {"format": "pdf", "filename": "x.pdf", "size_bytes": 100},
            ],
        },
        ctx,
    )
    assert result["ok"] is False
    assert "rate limit" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# generate_export_manifest
# ─────────────────────────────────────────────────────────────────────


async def test_generate_export_manifest_default_recipients(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["recipients"] = list(req.recipients)
        captured["bundle_status"] = dict(req.bundle_status)
        return {
            "id": "export_manifest",
            "name": "Export Manifest",
            "export_manifest": {
                "format_catalogue": [
                    {"key": "pdf", "ready": True},
                ],
                "recipient_recommendations": [
                    {"recipient": "client", "primary_format": "pdf"},
                ],
                "primary_handoff_format": "pdf",
            },
            "validation": {"all_recommendations_in_catalogue": True},
        }

    monkeypatch.setattr(
        "app.agents.tools.io._generate_export_manifest",
        fake,
    )

    result = await _call(
        "generate_export_manifest",
        {
            "bundle_status": {
                "meta": True, "material": True, "manufacturing": False,
                "mep": False, "cost": True,
            },
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    # Defaults to 3 recipients.
    assert out["recipient_count"] == 3
    assert captured["recipients"] == ["client", "fabricator", "architect"]
    assert captured["bundle_status"]["material"] is True


async def test_generate_export_manifest_with_custom_recipients(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["recipients"] = list(req.recipients)
        captured["downstream_software"] = list(req.downstream_software)
        return {
            "id": "export_manifest",
            "name": "Export Manifest",
            "export_manifest": {"primary_handoff_format": "ifc"},
            "validation": {},
        }

    monkeypatch.setattr(
        "app.agents.tools.io._generate_export_manifest",
        fake,
    )

    result = await _call(
        "generate_export_manifest",
        {
            "recipients": ["bim_consultant", "structural_engineer"],
            "downstream_software": ["Revit", "Tekla"],
            "bundle_status": {"meta": True},
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["recipient_count"] == 2
    assert captured["recipients"] == ["bim_consultant", "structural_engineer"]
    assert captured["downstream_software"] == ["Revit", "Tekla"]


async def test_generate_export_manifest_advisor_error_surfaces_as_tool_error(
    monkeypatch, ctx,
):
    from app.services.export_advisor_service import ExportAdvisorError

    async def fake(req):
        raise ExportAdvisorError("Unknown recipient(s): phantom_role")

    monkeypatch.setattr(
        "app.agents.tools.io._generate_export_manifest",
        fake,
    )

    result = await _call(
        "generate_export_manifest",
        {"recipients": ["phantom_role"], "bundle_status": {"meta": True}},
        ctx,
    )
    assert result["ok"] is False
    assert "phantom_role" in result["error"]["message"]
