"""Generation routes — initial design, local edit, theme switch, version history."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import (
    LocalEditRequest,
    PromptRequest,
    ThemeSwitchRequest,
)
from app.services.design_graph_service import (
    VersionDeleteError,
    delete_version,
    get_latest_render_for_version,
    get_latest_version,
    get_project,
    get_version,
    get_version_by_id,
    list_versions,
    load_render_bytes,
    set_version_bboxes,
)
from app.services.object_bboxes import compute_object_bboxes
from app.services.spatial import render_design
from app.services.spatial.render_pipeline import render_design_localized
from app.services.spatial.gltf import scene_to_gltf
from app.services.storage import key_to_url
from app.services.generation_pipeline import (
    _persist_render,
    _run_mep_cost,
    _stamp_display_currency,
    run_initial_generation,
    run_local_edit,
    run_theme_switch,
)
from app.services.estimation_engine import compute_estimate
from app.services.diagrams import (
    generate_all as generate_all_diagrams,
    generate_one as generate_one_diagram,
    list_available as list_available_diagrams,
)
from app.services.exporters import available_formats, export as export_bundle
from app.services.knowledge_validator import validate_design_graph_async
from app.services.recommendations import recommend as build_recommendations
from app.services.recommendations_service import (
    RecommendationsError,
    RecommendationsRequest,
    generate_recommendations,
)
from app.knowledge import materials as _materials_kb
from app.services.pricing.knowledge_service import load_html_export_bands
from app.services.specs import build_spec_bundle
from app.services.standards.manufacturing_lookup import (
    lead_times_weeks_map as _lead_times_weeks_map_db,
)
from app.services.themes import get_theme as _get_theme_db

# LLM-authored diagram services (BRD Layer 2B). Each pairs a request model
# with a generate fn that reuses the matching deterministic renderer as the
# base SVG, then overlays a prompt/theme-aware interpretation on top. Used by
# the authored fan-out below; the deterministic registry remains the fallback.
from app.services.concept_diagram_service import (
    ConceptDiagramRequest,
    generate_concept_diagram,
)
from app.services.form_diagram_service import (
    FormDiagramRequest,
    generate_form_diagram,
)
from app.services.massing_diagram_service import (
    MassingDiagramRequest,
    generate_massing_diagram,
)
from app.services.volumetric_block_diagram_service import (
    VolumetricBlockRequest,
    generate_volumetric_block_diagram,
)
from app.services.design_process_diagram_service import (
    DesignProcessRequest,
    generate_design_process_diagram,
)
from app.services.solid_void_diagram_service import (
    SolidVoidRequest,
    generate_solid_void_diagram,
)
from app.services.spatial_organism_diagram_service import (
    SpatialOrganismRequest,
    generate_spatial_organism_diagram,
)
from app.services.hierarchy_diagram_service import (
    HierarchyRequest,
    generate_hierarchy_diagram,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])

logger = logging.getLogger(__name__)

# panel diagram_id → (request model, async generate fn). Ordered to match the
# frontend DIAGRAMS_CATALOGUE and the deterministic registry so the authored
# and fallback lists render in the same sequence.
_AUTHORED_DIAGRAMS: dict[str, tuple[type, object]] = {
    "concept_transparency": (ConceptDiagramRequest, generate_concept_diagram),
    "form_development": (FormDiagramRequest, generate_form_diagram),
    "massing": (MassingDiagramRequest, generate_massing_diagram),
    "volumetric": (VolumetricBlockRequest, generate_volumetric_block_diagram),
    "design_process": (DesignProcessRequest, generate_design_process_diagram),
    "solid_void": (SolidVoidRequest, generate_solid_void_diagram),
    "spatial_organism": (SpatialOrganismRequest, generate_spatial_organism_diagram),
    "hierarchy": (HierarchyRequest, generate_hierarchy_diagram),
}

_DIAGRAM_NAMES: dict[str, str] = {
    "concept_transparency": "Concept Transparency",
    "form_development": "Form Development",
    "massing": "Massing",
    "volumetric": "Volumetric",
    "design_process": "Design Process",
    "solid_void": "Solid vs Void",
    "spatial_organism": "Spatial Organism",
    "hierarchy": "Hierarchy",
}


async def _resolve_theme_slug(db: AsyncSession, graph: dict) -> str:
    """Best-effort resolve the stored theme to a slug the theme DB accepts.

    Real generations store ``style.primary`` as the theme key (slug), so the
    first candidate usually resolves directly. Older/starter graphs may carry
    a display name ("Warm Contemporary"); we try a couple of normalised forms
    before giving up. If nothing resolves we return the raw value and let the
    authored fan-out degrade that diagram to its deterministic base.
    """
    raw = ((graph.get("style") or {}).get("primary") or "").strip()
    seen: set[str] = set()
    for cand in (raw, raw.lower().replace(" ", "_"), raw.lower().replace(" ", "-"), raw.lower()):
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if await _get_theme_db(db, cand):
            return cand
    return raw


async def _author_one_diagram(
    diagram_id: str,
    graph: dict,
    summary: str,
    theme: str,
) -> dict:
    """Run one LLM diagram author, falling back to the deterministic base.

    Each service manages its own DB session (``session=None``) so the callers
    can fan these out concurrently. On any failure — missing LLM key, unknown
    theme, malformed response — we return the deterministic renderer's output
    tagged ``meta.authored=False`` so the panel still shows a real diagram
    rather than an error, only without the prompt-aware overlay.
    """
    req_model, gen_fn = _AUTHORED_DIAGRAMS[diagram_id]
    try:
        req = req_model(theme=theme, design_graph=graph, project_summary=summary)
        result = await gen_fn(req, session=None)  # type: ignore[operator]
        result.setdefault("meta", {})
        result["meta"]["authored"] = True
        return result
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the whole sheet
        logger.warning(
            "authored_diagram_degraded",
            extra={"id": diagram_id, "error": str(exc)[:300]},
        )
        base = generate_one_diagram(graph, diagram_id) or {"id": diagram_id}
        base.setdefault("name", _DIAGRAM_NAMES.get(diagram_id, diagram_id))
        base.setdefault("format", "svg")
        base.setdefault("meta", {})
        base["meta"]["authored"] = False
        base["meta"]["authored_error"] = str(exc)[:300]
        # Only surface a hard error when the deterministic base also produced
        # nothing renderable; a present SVG is a valid (un-annotated) diagram.
        if not base.get("svg") and not base.get("error"):
            base["error"] = str(exc)[:300]
        return base


async def _generate_authored_diagrams(
    db: AsyncSession,
    graph: dict,
    summary: str,
    diagram_id: str | None = None,
) -> list[dict]:
    """Fan out the LLM diagram authors concurrently (or one, if requested)."""
    theme = await _resolve_theme_slug(db, graph)
    ids = [diagram_id] if diagram_id else list(_AUTHORED_DIAGRAMS)
    results = await asyncio.gather(
        *(_author_one_diagram(did, graph, summary, theme) for did in ids)
    )
    return list(results)


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post("/generate")
async def generate_design(
    project_id: str,
    payload: PromptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run full initial generation pipeline."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    project.status = "generating"
    await db.flush()

    result = await run_initial_generation(
        db=db,
        project_id=project_id,
        prompt=payload.prompt,
        room_type=payload.room_type,
        style=payload.style,
        camera=payload.camera,
        lighting=payload.lighting,
        view_mode=payload.view_mode,
        ratio=payload.ratio,
        quality=payload.quality,
        drawing_type=payload.drawing_type,
        project_type=project.project_type,
        region=project.region,
        site=payload.site.model_dump() if payload.site else None,
    )
    return result


@router.post("/edit")
async def local_edit(
    project_id: str,
    payload: LocalEditRequest,
    render: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a single object via prompt. ``render=false`` returns the saved spec
    immediately (graph, estimate, validation) and skips the slow photoreal finish
    so the UI stays responsive; the client refreshes the image via /render."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    result = await run_local_edit(
        db=db,
        project_id=project_id,
        object_id=payload.object_id,
        edit_prompt=payload.prompt,
        project_type=project.project_type,
        region=project.region,
        render=render,
    )
    return result


@router.post("/theme")
async def switch_theme_route(
    project_id: str,
    payload: ThemeSwitchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the design theme."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    result = await run_theme_switch(
        db=db,
        project_id=project_id,
        new_style=payload.new_style,
        preserve_layout=payload.preserve_layout,
        project_type=project.project_type,
        region=project.region,
    )
    return result


@router.get("/versions")
async def list_versions_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    versions = await list_versions(db, project_id)
    return {
        "project_id": project_id,
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "change_type": v.change_type,
                "change_summary": v.change_summary,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@router.get("/versions/{version_num}")
async def get_version_route(
    project_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = await get_version(db, project_id, version_num)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    return {
        "id": version.id,
        "version": version.version,
        "change_type": version.change_type,
        "change_summary": version.change_summary,
        "graph_data": version.graph_data,
        "created_at": version.created_at.isoformat(),
    }


@router.delete("/versions/{version_num}")
async def delete_version_route(
    project_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single version (with its estimates + render assets) and
    re-point the project at the newest survivor. A project must keep at least
    one version, so deleting the last one is refused (409)."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    try:
        result = await delete_version(db, project_id, version_num)
    except VersionDeleteError as exc:
        msg = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in msg
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=msg)

    return {
        "status": "deleted",
        "project_id": project_id,
        "deleted_version": version_num,
        "latest_version": result["latest_version"],
        "remaining": result["remaining"],
    }


@router.get("/latest")
async def get_latest_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Latest version of a project — graph + render URL.

    Used by the project picker when re-opening an existing project so
    the gallery can render the most recent state without a re-generation.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")

    # Pull the most recent render asset for this version. Stored as a
    # short key; converted to the frontend-consumable URL here so the
    # caller doesn't need to know about the storage adapter.
    render = await get_latest_render_for_version(db, version.id)
    image_url = key_to_url(render.storage_key) if render and render.storage_key else None

    # Cost was historically only returned in the generate/edit/theme RESPONSE and
    # never persisted on the version, so re-opening a project showed an empty Cost
    # tab. Recompute it from the saved graph on load — compute_estimate is
    # deterministic + fast — so EVERY project (including ones generated before this
    # fix) shows cost. MEP system cost is rolled up the same way.
    graph = version.graph_data or {}
    estimate = None
    try:
        estimate = compute_estimate(graph)
        _stamp_display_currency(estimate, project.region)
        graph = {**graph, "estimation": estimate}
    except Exception as exc:  # noqa: BLE001 — never 500 the re-open
        logger.warning("estimate recompute failed for project %s: %s", project_id, exc)
    mep_cost = None
    try:
        mep_cost = await _run_mep_cost(
            db, graph_data=graph, project_type=project.project_type, region=project.region)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MEP recompute failed for project %s: %s", project_id, exc)

    return {
        "id": version.id,
        "version": version.version,
        "graph_data": graph,
        "estimate": estimate,
        "mep_cost_estimate": mep_cost,
        "prompt": version.prompt,
        "image_url": image_url,
        # Prefer vision-grounded hotspots persisted at generation time
        # (accurate to the render); fall back to the plan projection for
        # versions saved before grounding, or when grounding was unavailable.
        "objects_bbox": version.objects_bbox or compute_object_bboxes(version.graph_data),
    }


@router.get("/scene.gltf")
async def scene_gltf_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the latest version's real kernel geometry as glTF for the browser
    3D viewport. Built on demand from the spec so it always matches the current
    design; 404 when there is no renderable geometry yet."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")
    try:
        gltf = scene_to_gltf(version.graph_data or {})
    except Exception as exc:  # noqa: BLE001 — geometry must never 500 the workspace
        logger.warning("scene.gltf build failed for project %s: %s", project_id, exc)
        gltf = None
    if not gltf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No geometry for this design")
    return Response(content=gltf, media_type="model/gltf+json",
                    headers={"Cache-Control": "no-store"})


class _Vec3(BaseModel):
    x: float
    y: float
    z: float


class ObjectPositionUpdate(BaseModel):
    position: _Vec3


@router.patch("/objects/{object_id}/position")
async def update_object_position(
    project_id: str,
    object_id: str,
    payload: ObjectPositionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Direct-manipulation edit: set an object's position on the latest version's
    spec. The spec is the source of truth, so the 3D model, 2D render and
    drawings all re-derive from it. Updated in place (a nudge, not a new design
    iteration); the photoreal 2D render refreshes on the next generate. 404 when
    the object id isn't in the graph."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")

    graph = version.graph_data or {}
    target = next(
        (o for o in (graph.get("objects") or [])
         if isinstance(o, dict) and str(o.get("id")) == object_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object not found in design")

    target["position"] = {"x": payload.position.x, "y": payload.position.y, "z": payload.position.z}
    # In-place JSONB mutation isn't auto-tracked — flag it so the commit writes it.
    flag_modified(version, "graph_data")
    await db.flush()
    return {"status": "ok", "version": version.version, "object_id": object_id,
            "position": target["position"]}


def _geometry_unchanged(parent_graph: dict, new_graph: dict, object_ids: list[str]) -> bool:
    """True when every named object keeps the SAME position + dimensions across
    the two graphs — i.e. the edit changed only material/finish/colour. That's
    the condition under which the new render shares the previous camera, so a
    localized composite over the previous image is geometrically sound (a moved
    or resized object shifts the framing and must fall back to a full render)."""
    def _obj(g: dict, oid: str) -> dict | None:
        return next((o for o in (g.get("objects") or [])
                     if isinstance(o, dict) and str(o.get("id")) == oid), None)
    for oid in object_ids:
        a, b = _obj(parent_graph, oid), _obj(new_graph, oid)
        if a is None or b is None:
            return False
        if a.get("position") != b.get("position") or a.get("dimensions") != b.get("dimensions"):
            return False
    return True


@router.post("/render")
async def rerender_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-render the latest version's photoreal image from its current spec.
    After a direct edit (drag in the plan / 3D) the spec and the 3D model update
    instantly, but the photoreal 2D render is stale — this regenerates it (kernel
    → real-camera render → finish pass) and refreshes the exact hotspots so the
    flagship image and the click-to-edit boxes match the edited layout."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")
    graph = version.graph_data or {}

    # Localized edit render: when this version is a targeted, geometry-preserving
    # edit whose parent already has a render, change ONLY the edited object's
    # region on the hero (composite over the parent image) instead of re-finishing
    # — and reshuffling — the whole scene. Engages only under a geometry-locked
    # finish (ControlNet-depth); with the img2img finishes it self-defers, so any
    # miss falls through to the full render below (today's default behaviour).
    result = None
    changed = [str(x) for x in (version.changed_object_ids or []) if x]
    if changed and version.parent_version_id:
        parent = await get_version_by_id(db, version.parent_version_id)
        if parent and _geometry_unchanged(parent.graph_data or {}, graph, changed):
            prev = await load_render_bytes(db, parent.id)
            if prev:
                result = await render_design_localized(graph, prev, changed)

    if result is None or not result.image_bytes:
        result = await render_design(graph)
    if not result or not result.image_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Render unavailable (no geometry, or image provider unconfigured)",
        )

    image_url, _img, hotspots = await _persist_render(
        db,
        graph_version_id=version.id,
        image_bytes=result.image_bytes,
        mime_type=result.mime,
        source=result.provider,
        hotspots=result.hotspots,
        title=f"{result.kind} re-render",
    )
    if hotspots:
        await set_version_bboxes(db, version.id, hotspots)
    return {
        "status": "ok",
        "version": version.version,
        "image_url": image_url,
        "objects_bbox": hotspots or compute_object_bboxes(version.graph_data or {}),
    }


@router.post("/present")
async def present_route(
    project_id: str,
    setting: str | None = None,
    light: str | None = None,
    palette: str | None = None,
    styling: str | None = None,
    people: bool | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Presentation (hero) render — an atmospheric, styled architectural
    photograph of the latest version, for client/manager-facing decks. Distinct
    from /render (the faithful technical render): this deliberately adds site,
    light, materials and lifestyle styling. Optional mood params (setting, light,
    palette, styling, people) tune the look; each auto-derives a tasteful default
    from the design. Photoreal today via the image provider; faithful-photoreal
    once a Replicate token enables ControlNet-depth."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")
    graph = version.graph_data or {}

    mood = {k: v for k, v in {
        "setting": setting, "light": light, "palette": palette,
        "styling": styling, "people": people,
    }.items() if v is not None}

    result = await render_design(graph, presentation=True, mood=mood or None)
    if not result or not result.image_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Presentation render unavailable (no geometry, or image provider unconfigured)",
        )
    image_url, _img, _hotspots = await _persist_render(
        db,
        graph_version_id=version.id,
        image_bytes=result.image_bytes,
        mime_type=result.mime,
        source=result.provider,
        hotspots=None,
        title=f"{result.kind} presentation",
    )
    return {
        "status": "ok",
        "version": version.version,
        "image_url": image_url,
        "finished": bool(getattr(result, "finished", False)),
        "provider": result.provider,
    }


@router.post("/validate")
async def validate_route(
    project_id: str,
    version_num: int | None = None,
    segment: str = "residential",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run knowledge validator + recommendations on a stored graph version.

    If `version_num` is omitted, the latest version is used.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    report = await validate_design_graph_async(graph, segment=segment, session=db)
    style = (graph.get("style") or {}).get("primary") or ""
    theme_pack = await _get_theme_db(db, style) if style else None
    lt_map = await _lead_times_weeks_map_db(db)
    recommendations = build_recommendations(
        graph, theme_pack=theme_pack, lead_times_weeks=lt_map
    )
    return {
        "version": version.version,
        "validation": report,
        "recommendations": recommendations,
    }


# ── Second-speed advisor: LLM-authored recommendations ──────────────────────


def _dominant_material(graph: dict) -> tuple[str, str]:
    """Infer (primary_material, family) from the graph's materials + objects.

    Picks the most frequently named material across the materials list
    and object materials, then classifies it as ``wood`` / ``metal`` by
    matching against the knowledge-base catalogues (falls back to a
    keyword check for common species not keyed verbatim).
    """
    from collections import Counter

    names: list[str] = []
    for m in graph.get("materials", []) or []:
        n = (m.get("name") or "").strip()
        if n:
            names.append(n.lower())
    for o in graph.get("objects", []) or []:
        n = (o.get("material") or "").strip()
        if n:
            names.append(n.lower())
    if not names:
        return "", ""

    primary = Counter(names).most_common(1)[0][0]
    wood_keys = {k.lower() for k in _materials_kb.WOOD}
    metal_keys = {k.lower() for k in _materials_kb.METALS}

    family = ""
    if any(k in primary for k in wood_keys) or any(
        w in primary for w in
        ("wood", "walnut", "oak", "teak", "rosewood", "rubberwood", "pine", "plywood")
    ):
        family = "wood"
    elif any(k in primary for k in metal_keys) or any(
        w in primary for w in
        ("steel", "iron", "brass", "aluminium", "aluminum", "metal")
    ):
        family = "metal"

    return primary[:80], family[:32]


def _dominant_piece_type(graph: dict) -> str:
    """Most common object ``type`` in the graph (used as the piece type)."""
    from collections import Counter

    types = [
        (o.get("type") or "").strip().lower()
        for o in graph.get("objects", []) or []
    ]
    types = [t for t in types if t]
    if not types:
        return ""
    return Counter(types).most_common(1)[0][0][:80]


def _request_from_graph(graph: dict, project_name: str) -> RecommendationsRequest:
    """Build the LLM recommendations brief from a stored design graph."""
    style = ((graph.get("style") or {}).get("primary") or "")[:64]
    city = ((graph.get("site") or {}).get("location") or "").strip()[:80]
    primary_material, family = _dominant_material(graph)
    return RecommendationsRequest(
        project_name=(project_name or "KATHA Project")[:200],
        theme=style,
        piece_type=_dominant_piece_type(graph),
        primary_material=primary_material,
        primary_material_family=family,
        city=city,
    )


@router.post("/recommendations/full")
async def full_recommendations_route(
    project_id: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the LLM recommendations author against a stored graph version.

    This is the BRD §6 "second speed" advisor — slower than the
    deterministic ``/validate`` path (a live LLM call, ~3-8s) but it adds
    confidence / impact / effort labels and catalogue-grounded
    alternatives. The brief is derived from the version's graph (theme,
    dominant material + family, city, piece type) so the caller doesn't
    need to assemble it client-side.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    req = _request_from_graph(graph, project.name or "KATHA Project")
    try:
        report = await generate_recommendations(req, session=db)
    except RecommendationsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return {"version": version.version, "report": report}


@router.get("/diagrams/available")
async def diagrams_available_route(
    project_id: str,
    user: User = Depends(get_current_user),
):
    """List diagram types supported by the platform."""
    return {"diagrams": list_available_diagrams()}


@router.post("/diagrams")
async def diagrams_route(
    project_id: str,
    version_num: int | None = None,
    diagram_id: str | None = None,
    authored: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate auto-diagrams for a stored graph version.

    - If `diagram_id` is given, returns only that diagram.
    - Otherwise returns every ready diagram for the version.
    - If `authored` is set, each diagram is run through its LLM author
      (prompt + theme aware) instead of the geometry-only renderer, with a
      per-diagram fallback to the deterministic base when the LLM is
      unavailable. Slower (concurrent live LLM calls) but reflects the brief.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}

    if authored:
        if diagram_id and diagram_id not in _AUTHORED_DIAGRAMS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown diagram '{diagram_id}'")
        # The prompt is the prompt-awareness signal the geometry lacks; fall
        # back to the project name so the author always has a brief to read.
        summary = (version.prompt or project.name or "")[:2000]
        diagrams = await _generate_authored_diagrams(db, graph, summary, diagram_id)
        return {"version": version.version, "diagrams": diagrams}

    if diagram_id:
        single = generate_one_diagram(graph, diagram_id)
        if single is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown diagram '{diagram_id}'")
        return {"version": version.version, "diagrams": [single]}
    return {"version": version.version, "diagrams": generate_all_diagrams(graph)}


@router.get("/specs")
async def specs_route(
    project_id: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the structured spec bundle (material + manufacturing + MEP + cost)."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    bundle = build_spec_bundle(graph, project_name=project.name or "KATHA Project")
    return {"version": version.version, "spec_bundle": bundle}


@router.get("/export/formats")
async def export_formats_route(
    project_id: str,
    user: User = Depends(get_current_user),
):
    return {"formats": available_formats()}


@router.post("/export")
async def export_route(
    project_id: str,
    format: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the latest (or specified) version as pdf / docx / xlsx."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    brd_bands = await load_html_export_bands(db)
    bundle = build_spec_bundle(
        graph,
        project_name=project.name or "KATHA Project",
        design_title=getattr(version, "prompt", None),
        brd_bands=brd_bands,
    )
    try:
        result = export_bundle(format, bundle, graph)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{result["filename"]}"'}
    return Response(content=result["bytes"], media_type=result["content_type"], headers=headers)
