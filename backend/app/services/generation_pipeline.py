"""Generation Pipeline — orchestrates the full flow from prompt to design graph + assets."""

import base64
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_orchestrator import (
    edit_object_via_prompt,
    generate_design_graph,
    switch_theme,
)
from app.services.design_graph_service import (
    get_latest_version,
    save_graph_version,
    save_render_asset,
)
from app.services.estimation.catalog import convert_from_inr, currency_symbol
from app.services.estimation_engine import compute_estimate
from app.services.regions import (
    currency_for_region,
    get_region,
    jurisdiction_for_region,
)
from app.services.graph_describer import describe_graph_for_render
from app.services.image_service import generate_image, resolve_theme_visual_hint
from app.services.knowledge_validator import validate_design_graph_async
from app.services.standards.knowledge_service import resolve_standard as _resolve_standard
from app.services.standards.mep_sizing import system_cost_estimate as _mep_system_cost
from app.services.object_bboxes import compute_object_bboxes
from app.services.storage import key_to_url, make_key, save_bytes

logger = logging.getLogger(__name__)


async def _attach_render(
    db: AsyncSession,
    *,
    graph_version_id: str,
    prompt: str,
    project_type: str | None,
    theme: str | None,
    graph_data: dict | None = None,
    theme_label: str | None = None,
) -> str | None:
    """Best-effort: render an image for the just-saved version, persist
    the bytes to object storage, and write a GeneratedAsset row pointing
    at the storage key. Returns a clean URL the frontend can GET, or
    None when the provider is unconfigured / failed. Never raises —
    graph is already saved at this point.

    Storage flow
    ------------
    Gemini hands back a base64 ``data:`` URI. Embedding that in the DB
    (and shipping it on every read) was the prior fragility — single
    renders pushed multi-hundred KB through every request and ate
    localStorage quota on the client. Now we:

      1. Decode the data URI to raw bytes.
      2. Write them to ``storage`` under a stable key
         (``renders/{graph_version_id}/{uuid}.png``).
      3. Persist only the *key* on the GeneratedAsset row.
      4. Return a short ``/api/v1/assets/{key}`` URL the browser can
         cache like any normal image.

    When ``graph_data`` is supplied, we also append a structured
    description of the graph (objects, materials, dimensions,
    positions) to the prompt so the image model is conditioned on the
    actual geometry — the load-bearing step that lets edits like
    "move the table 30cm right" surface in the next render.
    """
    if not prompt or not prompt.strip():
        return None
    enriched_prompt = prompt.strip()
    if graph_data is not None:
        graph_desc = describe_graph_for_render(graph_data)
        if graph_desc:
            enriched_prompt = f"{enriched_prompt}\n\n{graph_desc}"
    # Resolve the visual hint from DB first — admin-defined themes
    # carry their hint in rule_pack.visual_hint, with the legacy
    # Python dict as a fallback for the 10 stock themes.
    resolved_hint = await resolve_theme_visual_hint(db, theme)
    try:
        result = await generate_image(
            enriched_prompt,
            project_type=project_type,
            theme=theme,
            theme_label=theme_label,
            theme_visual_hint=resolved_hint,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Render generation failed for version %s: %s",
                       graph_version_id, exc)
        return None
    if not result or not result.get("url"):
        return None

    raw_url = result["url"]
    image_bytes, mime_from_url = _decode_data_url(raw_url)
    mime_type = mime_from_url or str(result.get("mime_type") or "image/png")
    if image_bytes is None:
        # Provider returned something other than a base64 data URI
        # (e.g. an HTTP URL from a future CDN-backed provider). Persist
        # whatever it is verbatim as the key and skip the storage hop.
        logger.info(
            "Render returned non-data URL — passing through as key (version=%s)",
            graph_version_id,
        )
        storage_key = raw_url
        final_url = raw_url
    else:
        ext = _ext_for_mime(mime_type)
        storage_key = make_key("renders", graph_version_id, ext=ext)
        try:
            await save_bytes(storage_key, image_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Storage write failed for render version=%s: %s",
                graph_version_id, exc,
            )
            return None
        final_url = key_to_url(storage_key)

    try:
        await save_render_asset(
            db,
            graph_version_id=graph_version_id,
            storage_key=storage_key,
            mime_type=mime_type,
            metadata={
                "source": result.get("source", "gemini"),
                "title": result.get("title", ""),
                "bytes": len(image_bytes) if image_bytes is not None else None,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Persisting render asset failed for version %s: %s",
                       graph_version_id, exc)
        # Asset row didn't save, but the bytes are on disk and the URL
        # still resolves — return it so the response carries the render.
    return final_url


def _decode_data_url(value: str) -> tuple[bytes | None, str | None]:
    """Decode a base64 ``data:`` URI into bytes + the declared MIME type.

    Returns ``(None, None)`` when ``value`` isn't a base64 data URL —
    callers should treat that as "already an HTTP URL, pass through".
    """
    if not isinstance(value, str) or not value.startswith("data:"):
        return None, None
    header, _, payload = value.partition(",")
    if not payload:
        return None, None
    # header looks like "data:image/png;base64"
    mime: str | None = None
    is_base64 = False
    for part in header[5:].split(";"):
        part = part.strip()
        if part == "base64":
            is_base64 = True
        elif "/" in part and not mime:
            mime = part
    if not is_base64:
        return None, None
    try:
        return base64.b64decode(payload), mime
    except Exception:  # noqa: BLE001
        return None, mime


def _segment_for_project_type(project_type: str | None) -> str:
    """Map a BRD project_type slug to the high-level segment the
    space-standards table uses (residential / commercial / hospitality).

    The DB seed only registers room minimums for these three buckets,
    so anything else falls back to ``residential`` — conservative
    default that won't raise false alarms.
    """
    if not project_type:
        return "residential"
    pt = project_type.lower()
    if pt in {"residential", "mixed_use"}:
        return "residential"
    if pt in {"commercial", "office", "retail", "institutional", "industrial"}:
        return "commercial"
    if pt == "hospitality":
        return "hospitality"
    return "residential"


def _mep_system_keys(project_type: str | None) -> dict[str, str]:
    """Pick the right ``mep_system_cost_*`` slug per system for the
    project type. Residential gets split-AC HVAC + residential plumbing
    + residential electrical; commercial gets VRF + commercial set.
    Fire-fighting is included because the BRD §1B explicitly lists
    fire safety as part of the MEP cost stack.
    """
    is_commercial = (project_type or "").lower() in {
        "commercial",
        "office",
        "retail",
        "institutional",
        "industrial",
        "hospitality",
    }
    if is_commercial:
        return {
            "hvac": "hvac_vrf_commercial",
            "electrical": "electrical_commercial",
            "plumbing": "plumbing_commercial",
            "fire_fighting": "fire_fighting_commercial",
        }
    return {
        "hvac": "hvac_split_residential",
        "electrical": "electrical_residential",
        "plumbing": "plumbing_residential",
        "fire_fighting": "fire_fighting_residential",
    }


async def _mep_dimensions(graph_data: dict) -> dict:
    """Extract room dimensions from a design graph, tolerant of both the
    legacy top-level ``room`` shape and the serialised ``DesignGraph``
    shape (which carries dims under ``spaces[0]``).

    The pipeline feeds ``DesignGraph.model_dump()`` here, which has NO
    top-level ``room`` key — only ``spaces[]``. Reading ``room`` alone
    silently returned no area, leaving the Cost tab empty. Fall back to
    the first space so the MEP roll-up actually fires.
    """
    room = graph_data.get("room") or {}
    dims = room.get("dimensions") or {}
    if dims:
        return dims
    spaces = graph_data.get("spaces") or []
    if spaces and isinstance(spaces[0], dict):
        return spaces[0].get("dimensions") or {}
    return {}


async def _run_mep_cost(
    db: AsyncSession,
    *,
    graph_data: dict,
    project_type: str | None,
    region: str = "india",
) -> dict | None:
    """Aggregate MEP system cost (HVAC + electrical + plumbing +
    fire-fighting) at the project_type-appropriate ₹/m² band, based on
    the room area in the design graph, then convert to the project's
    regional currency for output.

    Returns ``None`` when there's no usable area — the cost terminal
    falls through to its no-MEP-cost-yet placeholder.
    """
    dims = await _mep_dimensions(graph_data)
    length = dims.get("length")
    width = dims.get("width")
    if not (length and width):
        return None
    try:
        # Graph dims are in metres; if anything came through as mm it'd
        # be >20, in which case treat as mm. The validator does this
        # heuristic already; mirror it here to stay consistent.
        l = float(length) / 1000.0 if float(length) > 20 else float(length)
        w = float(width) / 1000.0 if float(width) > 20 else float(width)
    except (TypeError, ValueError):
        return None
    area_m2 = l * w
    if area_m2 <= 0:
        return None

    keys = _mep_system_keys(project_type)
    systems: list[dict] = []
    total_low = 0.0
    total_high = 0.0
    for system_name, slug_suffix in keys.items():
        try:
            res = await _mep_system_cost(
                db, system_key=slug_suffix, area_m2=area_m2
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MEP cost lookup failed for %s: %s", slug_suffix, exc)
            continue
        if "error" in res:
            continue
        systems.append(
            {
                "system": system_name,
                "key": slug_suffix,
                "rate_inr_m2": res.get("rate_inr_m2") or {},
                "total_inr": res.get("total_inr") or {},
            }
        )
        total = res.get("total_inr") or {}
        total_low += float(total.get("low") or 0)
        total_high += float(total.get("high") or 0)

    if not systems:
        return None

    reg = get_region(region)
    currency = reg.currency
    # Rate-cards are authored in INR; convert the roll-up into the
    # project's regional currency for display. INR projects pass through
    # unchanged (rate == 1.0).
    total_low_ccy = round(float(convert_from_inr(total_low, currency)), 0)
    total_high_ccy = round(float(convert_from_inr(total_high, currency)), 0)

    return {
        "area_m2": round(area_m2, 2),
        "currency": currency,
        "currency_symbol": currency_symbol(currency),
        "jurisdiction": reg.jurisdiction,
        "region": reg.key,
        "systems": systems,
        # Native INR roll-up retained for back-compat + auditability.
        "total_inr": {
            "low": round(total_low, 0),
            "high": round(total_high, 0),
        },
        # Region-converted total — what the cost tab should display.
        "total": {
            "low": total_low_ccy,
            "high": total_high_ccy,
        },
    }


def _stamp_display_currency(estimate: dict, region: str) -> dict:
    """Stamp a ``display`` block on the estimate carrying the project's
    regional currency + the already-computed converted total.

    The estimation engine authors everything in INR (base currency) but
    also emits ``converted_totals[<code>]`` for every supported currency.
    Rather than re-architect the engine, we pick the region's currency
    here so the frontend renders €/AED/$ instead of ₹ for non-Indian
    markets — the difference between a credible Germany/Dubai demo and a
    rupee-denominated one.
    """
    if not isinstance(estimate, dict):
        return estimate
    reg = get_region(region)
    currency = reg.currency
    converted = (estimate.get("converted_totals") or {}).get(currency) or {}
    final_total = converted.get("final_total")
    # Fall back to a direct INR→currency conversion if the engine didn't
    # emit this currency (e.g. failed-estimate envelope).
    if final_total is None:
        base_total = (
            (estimate.get("pricing_adjustments") or {}).get("final_total")
            or 0
        )
        final_total = float(convert_from_inr(base_total, currency))
    area = (estimate.get("area") or {}).get("total_sqft") or 0
    estimate["display"] = {
        "currency": currency,
        "currency_symbol": currency_symbol(currency),
        "region": reg.key,
        "locale": reg.locale,
        "final_total": round(float(final_total), 0),
        "cost_per_sqft": round(float(final_total) / area, 0) if area else 0,
    }
    return estimate


def _jurisdiction_for_project(
    project_type: str | None, region: str | None = None
) -> str:
    """Pick the right standards jurisdiction for a project.

    Region is the primary driver: each of the 8 markets maps to a
    building-code jurisdiction (see ``app.services.regions``). The
    standards resolver falls back to the international baseline
    (``international_ibc``) when a region's native rows aren't seeded,
    so this never fails to find a matching code row.

    ``project_type`` is retained for signature back-compat but no longer
    selects the jurisdiction — that's a function of *where* the project
    is, not *what* it is.
    """
    return jurisdiction_for_region(region)


_COMPLIANCE_CODES = {
    "NBC_VIOLATION",
    "ROOM_AREA_BELOW_STANDARD",
    "DOOR_TOO_NARROW",
    "DOOR_WIDTH_OUT_OF_BAND",
    "CORRIDOR_TOO_NARROW",
    "STAIR_GEOMETRY_OUT_OF_BAND",
}


_COMPLIANCE_LABELS = {
    "NBC_VIOLATION": "NBC habitable room",
    "ROOM_AREA_BELOW_STANDARD": "Room area",
    "DOOR_TOO_NARROW": "Door width",
    "DOOR_WIDTH_OUT_OF_BAND": "Door width",
    "CORRIDOR_TOO_NARROW": "Corridor width",
    "STAIR_GEOMETRY_OUT_OF_BAND": "Stair geometry",
}


def _entries_from_validation(validation: dict) -> list[dict]:
    """Walk the validation report and emit one ``compliance entry``
    per code-related fail. Each carries label + status=fail + the
    issue message + the validator's citation passthrough.
    """
    out: list[dict] = []
    for level, issues in (
        ("fail", validation.get("errors", [])),
        ("warn", validation.get("warnings", [])),
    ):
        for issue in issues:
            code = issue.get("code") or ""
            if code not in _COMPLIANCE_CODES:
                continue
            out.append(
                {
                    "label": _COMPLIANCE_LABELS.get(code, code),
                    "value": issue.get("message") or "",
                    "target": issue.get("reference") or "",
                    "status": level,
                    "code": code,
                    "source_section": issue.get("source_section"),
                    "jurisdiction": issue.get("jurisdiction"),
                }
            )
    return out


async def _compliance_advisories(
    db: AsyncSession,
    *,
    jurisdiction: str,
) -> list[dict]:
    """Pull a small, curated set of advisory targets from DB-backed
    code rows. These don't have inputs to validate against today
    (envelope U-values, ramp slopes, fire-safety triggers) — we
    surface the target so the architect knows what they're meeting.
    Status ``info`` indicates advisory, not pass/fail.
    """
    advisories: list[dict] = []

    ecbc = await _resolve_standard(
        db,
        slug="code_ecbc_envelope_targets",
        category="code",
        jurisdiction=jurisdiction,
    )
    if ecbc:
        d = ecbc.get("data") or {}
        wall_u = d.get("envelope_U_value_wall_w_m2k")
        roof_u = d.get("envelope_U_value_roof_w_m2k")
        wwr = d.get("window_wall_ratio_max")
        cite = ecbc.get("source_section")
        jur = ecbc.get("jurisdiction") or jurisdiction
        if wall_u is not None:
            advisories.append(
                {
                    "label": "Wall U-value",
                    "value": f"target ≤ {wall_u} W/m²K",
                    "target": f"ECBC ≤ {wall_u}",
                    "status": "info",
                    "code": "ECBC_ENVELOPE_WALL",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )
        if roof_u is not None:
            advisories.append(
                {
                    "label": "Roof U-value",
                    "value": f"target ≤ {roof_u} W/m²K",
                    "target": f"ECBC ≤ {roof_u}",
                    "status": "info",
                    "code": "ECBC_ENVELOPE_ROOF",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )
        if wwr is not None:
            advisories.append(
                {
                    "label": "Window-wall ratio",
                    "value": f"target ≤ {wwr:.0%}",
                    "target": f"ECBC ≤ {wwr:.0%}",
                    "status": "info",
                    "code": "ECBC_WWR",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )

    access = await _resolve_standard(
        db,
        slug="code_accessibility_india_general",
        category="code",
        jurisdiction=jurisdiction,
    )
    if access:
        d = access.get("data") or {}
        slope = d.get("ramp_slope_max_ratio")
        clear = d.get("doorway_clear_width_mm")
        cite = access.get("source_section")
        jur = access.get("jurisdiction") or jurisdiction
        if slope:
            # Convert ratio to 1:N for human readability.
            ratio = round(1 / float(slope))
            advisories.append(
                {
                    "label": "Ramp slope",
                    "value": f"target ≤ 1:{ratio}",
                    "target": f"≤ 1:{ratio}",
                    "status": "info",
                    "code": "ACCESS_RAMP_SLOPE",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )
        if clear:
            advisories.append(
                {
                    "label": "Accessible doorway",
                    "value": f"clear ≥ {clear} mm",
                    "target": f"≥ {clear} mm",
                    "status": "info",
                    "code": "ACCESS_DOORWAY_CLEAR",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )

    fire = await _resolve_standard(
        db,
        slug="code_fire_safety_india_general",
        category="code",
        jurisdiction=jurisdiction,
    )
    if fire:
        d = fire.get("data") or {}
        smoke = d.get("smoke_detector")
        cite = fire.get("source_section")
        jur = fire.get("jurisdiction") or jurisdiction
        if smoke:
            advisories.append(
                {
                    "label": "Smoke detector",
                    "value": str(smoke),
                    "target": "NBC Part 4 req.",
                    "status": "info",
                    "code": "FIRE_SMOKE_DETECTOR",
                    "source_section": cite,
                    "jurisdiction": jur,
                }
            )

    return advisories


async def _run_compliance_summary(
    db: AsyncSession,
    *,
    validation: dict,
    jurisdiction: str,
) -> list[dict]:
    """Build the right-sidebar 'Code compliance' summary.

    Mix of:
    - Fail entries derived from the validation report (NBC, doors,
      corridors, stairs, areas).
    - Info / advisory entries pulled from DB (ECBC envelope targets,
      accessibility ramp + doorway, fire-safety smoke detector).

    A fully-clean design with no validation flags still shows the
    advisory rows so the architect knows which codes the design
    needs to meet, not just which ones it's currently failing.
    """
    entries = _entries_from_validation(validation)
    try:
        advisories = await _compliance_advisories(db, jurisdiction=jurisdiction)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Compliance advisories lookup failed: %s", exc)
        advisories = []
    return entries + advisories


async def _run_validation(
    db: AsyncSession,
    *,
    graph_data: dict,
    project_type: str | None,
    jurisdiction: str | None = None,
) -> dict:
    """Run the async DB-backed validator against the freshly-generated
    graph. Wrapped in a try so a validator hiccup never fails the
    generation — the architect still gets the design + cost, just
    without the Problems tab annotations.

    ``jurisdiction`` overrides the project_type-derived default — pass
    it when the route knows the project's regulatory.country.
    """
    chosen_jurisdiction = jurisdiction or _jurisdiction_for_project(project_type)
    try:
        return await validate_design_graph_async(
            graph_data,
            segment=_segment_for_project_type(project_type),
            session=db,
            jurisdiction=chosen_jurisdiction,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Validation pass failed (continuing without warnings): %s", exc)
        return {
            "ok": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "summary": "Validation unavailable.",
        }


def _ext_for_mime(mime: str) -> str:
    """Map a MIME type to a file extension we'd use in storage keys."""
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }.get((mime or "").lower(), "png")


async def run_initial_generation(
    db: AsyncSession,
    project_id: str,
    prompt: str,
    room_type: str = "living_room",
    style: str = "modern",
    camera: str | None = None,
    lighting: str | None = None,
    view_mode: str | None = None,
    ratio: str | None = None,
    quality: str | None = None,
    drawing_type: str | None = None,
    project_type: str | None = None,
    region: str = "india",
) -> dict:
    """
    Full pipeline for initial design:
    1. AI generates structured design graph
    2. Save as version 1
    3. Compute estimate
    4. Render a 2D image, persist as GeneratedAsset (best-effort)
    5. Return combined result
    """

    # Step 1 — AI generation
    logger.info("Starting initial generation for project %s", project_id)
    design_graph = await generate_design_graph(
        prompt=prompt,
        room_type=room_type,
        style=style,
        project_id=project_id,
        camera=camera,
        lighting=lighting,
        view_mode=view_mode,
        ratio=ratio,
        quality=quality,
        drawing_type=drawing_type,
    )
    graph_data = design_graph.model_dump()

    # Step 2 — Persist (capture prompt so re-renders inherit context)
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=graph_data,
        change_type="initial",
        change_summary=f"Initial generation from prompt: {prompt[:100]}",
        prompt=prompt,
    )

    # Step 3 — Estimate
    estimate = compute_estimate(graph_data)
    _stamp_display_currency(estimate, region)

    # Step 3b — BRD §1B / §9.1: validate against authoritative standards
    # (room areas, ergonomics, NBC clauses, theme alignment). Results
    # flow to the Problems terminal tab via the response.
    jurisdiction = _jurisdiction_for_project(project_type, region)
    validation = await _run_validation(
        db, graph_data=graph_data, project_type=project_type, jurisdiction=jurisdiction,
    )

    # Step 3c — BRD §1B MEP: roll up HVAC + electrical + plumbing +
    # fire-fighting system cost at ₹/m² bands. Surfaces in the cost
    # terminal as a real, cited number alongside the existing estimate.
    mep_cost = await _run_mep_cost(
        db, graph_data=graph_data, project_type=project_type, region=region
    )

    # Step 3d — BRD §1B Building Code Integration: condense validation
    # report + DB-advisory targets into a sidebar-ready compliance
    # summary (NBC pass/fail, ECBC envelope targets, accessibility,
    # fire-safety advisories).
    compliance = await _run_compliance_summary(
        db, validation=validation, jurisdiction=jurisdiction,
    )

    # Step 4 — Render (best-effort; doesn't fail the response if Gemini
    # is down or the API key is unset). The graph_data flows in so the
    # image model is conditioned on the actual generated geometry, not
    # just the user's typed brief.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=prompt,
        project_type=project_type,
        theme=style,
        graph_data=graph_data,
    )

    logger.info(
        "Generation complete: project=%s version=%d objects=%d render=%s warnings=%d",
        project_id,
        version.version,
        len(graph_data.get("objects", [])),
        "yes" if image_url else "no",
        len(validation.get("warnings", [])),
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": graph_data,
        "estimate": estimate,
        "image_url": image_url,
        "objects_bbox": compute_object_bboxes(graph_data),
        "validation": validation,
        "mep_cost_estimate": mep_cost,
        "code_compliance_summary": compliance,
        "status": "completed",
    }


async def run_local_edit(
    db: AsyncSession,
    project_id: str,
    object_id: str,
    edit_prompt: str,
    project_type: str | None = None,
    region: str = "india",
) -> dict:
    """
    Edit a single object:
    1. Load latest version
    2. AI edits the target object
    3. Save new version (preserves the originating prompt)
    4. Recompute estimate
    5. Re-render — combines original prompt + edit hint for context
    """

    latest = await get_latest_version(db, project_id)
    if latest is None:
        raise ValueError(f"No versions found for project {project_id}")

    current_graph = latest.graph_data
    base_prompt = (latest.prompt or "").strip()
    # Render context: original prompt + the edit hint, so Gemini has
    # the design's framing instead of just "make it walnut".
    render_prompt = (
        f"{base_prompt} — {edit_prompt.strip()}"
        if base_prompt
        else edit_prompt.strip()
    )
    theme = (current_graph.get("style") or {}).get("name") if isinstance(current_graph, dict) else None

    # AI edit
    updated_graph = await edit_object_via_prompt(
        current_graph=current_graph,
        object_id=object_id,
        edit_prompt=edit_prompt,
    )

    # Persist (preserve the originating prompt across the edit chain)
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph,
        change_type="prompt_edit",
        change_summary=f"Edited {object_id}: {edit_prompt[:100]}",
        changed_object_ids=[object_id],
        parent_version_id=latest.id,
        prompt=base_prompt or None,
    )

    estimate = compute_estimate(updated_graph)
    _stamp_display_currency(estimate, region)

    # BRD §1B / §9.1 — re-validate against authoritative standards
    # after the edit. Picks up any new violations the edit introduced.
    jurisdiction = _jurisdiction_for_project(project_type, region)
    validation = await _run_validation(
        db, graph_data=updated_graph, project_type=project_type, jurisdiction=jurisdiction,
    )
    mep_cost = await _run_mep_cost(
        db, graph_data=updated_graph, project_type=project_type, region=region
    )
    compliance = await _run_compliance_summary(
        db, validation=validation, jurisdiction=jurisdiction,
    )

    # Render against the *updated* graph so geometric edits surface
    # in the new render rather than just the data layer.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=render_prompt,
        project_type=project_type,
        theme=theme,
        graph_data=updated_graph,
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph,
        "estimate": estimate,
        "changed_objects": [object_id],
        "image_url": image_url,
        "objects_bbox": compute_object_bboxes(updated_graph),
        "validation": validation,
        "mep_cost_estimate": mep_cost,
        "code_compliance_summary": compliance,
        "status": "completed",
    }


async def run_theme_switch(
    db: AsyncSession,
    project_id: str,
    new_style: str,
    preserve_layout: bool = True,
    project_type: str | None = None,
    region: str = "india",
) -> dict:
    """
    Switch the entire design theme:
    1. Load latest version
    2. AI applies new theme
    3. Save new version (preserves the originating prompt)
    4. Recompute estimate
    5. Re-render — same originating prompt with the new theme hint
    """

    latest = await get_latest_version(db, project_id)
    if latest is None:
        raise ValueError(f"No versions found for project {project_id}")

    updated_graph = await switch_theme(
        current_graph=latest.graph_data,
        new_style=new_style,
        preserve_layout=preserve_layout,
    )

    # Re-wrap as internal design graph format
    updated_graph_data = _normalize_ai_output(updated_graph, latest.graph_data)

    base_prompt = (latest.prompt or "").strip() or None

    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph_data,
        change_type="theme_switch",
        change_summary=f"Theme switched to {new_style}",
        parent_version_id=latest.id,
        prompt=base_prompt,
    )

    estimate = compute_estimate(updated_graph_data)
    _stamp_display_currency(estimate, region)

    # BRD §1B / §9.1 — theme swaps shouldn't change geometry, but if
    # the LLM inadvertently shrank a room while re-tagging materials,
    # this catches it.
    jurisdiction = _jurisdiction_for_project(project_type, region)
    validation = await _run_validation(
        db, graph_data=updated_graph_data, project_type=project_type,
        jurisdiction=jurisdiction,
    )
    mep_cost = await _run_mep_cost(
        db, graph_data=updated_graph_data, project_type=project_type, region=region
    )
    compliance = await _run_compliance_summary(
        db, validation=validation, jurisdiction=jurisdiction,
    )

    # Theme switch keeps the same geometry — pass the updated graph so
    # the new render is conditioned on layout that's literally
    # unchanged, with only material / palette differing per the new
    # theme hint.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=base_prompt or new_style,
        project_type=project_type,
        theme=new_style,
        graph_data=updated_graph_data,
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph_data,
        "estimate": estimate,
        "image_url": image_url,
        "objects_bbox": compute_object_bboxes(updated_graph_data),
        "validation": validation,
        "mep_cost_estimate": mep_cost,
        "code_compliance_summary": compliance,
        "status": "completed",
    }


def _normalize_ai_output(ai_output: dict, previous: dict) -> dict:
    """Ensure AI output retains our internal structure fields."""
    # Carry forward fields that AI might not return
    for key in ("project_id", "version", "design_type", "site", "constraints"):
        if key not in ai_output and key in previous:
            ai_output[key] = previous[key]
    return ai_output
