"""Stage 14 — derive end-user-facing content from the spec bundle.

The DOCX/PPTX exporters need two BRD-mandated sections that aren't
in the raw spec dict:

1. **Assembly Instructions** — a numbered, plain-language sequence
   of steps for whoever physically puts the piece together. The
   manufacturing spec already carries an ``assembly.sequence`` list
   (from ``app.services.specs.manufacturing_spec``); we expand each
   bullet into a tools/notes/safety dict suitable for client delivery.

2. **Maintenance & Care Guide** — daily / weekly / monthly / annual
   tasks per material category present in the design, with warnings
   the customer needs to know (UV, humidity, abrasive cleaners, …).
   Derived from the material rows in ``spec["material"]`` — we map
   each row's category to a curated care matrix below.

Both functions are **pure** — no IO, no DB, take ``(spec, graph)``
and return a JSON-serialisable structure. Exporters render that
structure into their own format. Centralising the derivation here
means the DOCX and PPTX (and any future exporter) cite the same
BRD-anchored content; if maintenance guidance changes, it changes
in one place.
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────
# Assembly instructions
# ─────────────────────────────────────────────────────────────────────


# Curated tools + safety per assembly step. Keyed by a substring match
# against the manufacturing-spec sequence string so we stay decoupled
# from the exact wording of the upstream list.
_ASSEMBLY_STEP_LIBRARY: list[dict[str, Any]] = [
    {
        "match": "frame",
        "tools": ["Allen key set", "Square (try square)", "Soft mallet"],
        "safety": "Dry-fit with no glue first; check joints engage cleanly before commitment.",
    },
    {
        "match": "sand",
        "tools": ["Random orbital sander (P120 → P220)", "Sanding block", "Tack cloth"],
        "safety": "Wear dust mask; sand with the grain on visible surfaces.",
    },
    {
        "match": "finish",
        "tools": ["Foam brush or HVLP gun", "Lint-free cloth", "Sanding block (P320)"],
        "safety": "Ventilated space; allow recommended cure time between coats.",
    },
    {
        "match": "hardware",
        "tools": ["Torque screwdriver", "Hex / Phillips bits", "Thread-lock (medium)"],
        "safety": "Tighten to torque spec — over-torque strips cabinetry; under-torque allows wobble.",
    },
    {
        "match": "upholstery",
        "tools": ["Pneumatic stapler (8–10 mm)", "Webbing stretcher", "Upholstery hammer"],
        "safety": "Webbing tension per manufacturing spec; staples flush, no proud heads.",
    },
    {
        "match": "qc",
        "tools": ["Tape measure", "Spirit level", "Notepad"],
        "safety": "Verify against the QA gates list; nothing ships until every gate is signed.",
    },
    {
        "match": "packag",
        "tools": ["Edge protectors", "Stretch wrap", "Strapping"],
        "safety": "Corner foam on every contact face; label fragile + this-side-up.",
    },
]

_DEFAULT_TOOLS = ["General workshop kit"]
_DEFAULT_SAFETY = "Follow manufacturing spec tolerances; do not skip QA gates."


def _enrich_step(raw_step: str) -> dict[str, Any]:
    lowered = raw_step.lower()
    for entry in _ASSEMBLY_STEP_LIBRARY:
        if entry["match"] in lowered:
            return {
                "action": raw_step,
                "tools": list(entry["tools"]),
                "safety": entry["safety"],
            }
    return {
        "action": raw_step,
        "tools": _DEFAULT_TOOLS,
        "safety": _DEFAULT_SAFETY,
    }


def derive_assembly_instructions(spec: dict, graph: dict) -> dict[str, Any]:
    """Return a structured assembly guide ready for DOCX/PPTX rendering.

    Shape::

        {
          "summary": "...",
          "steps": [
            {"step_number": 1, "action": "Frame + joinery dry-fit",
             "tools": [...], "safety": "..."},
            ...
          ],
          "qa_gates": [...],          # passthrough from manufacturing spec
          "packaging": "...",          # passthrough
          "tolerance_notes": [...],   # mm tolerances pulled from manufacturing
        }

    Returns an empty-but-valid structure when the manufacturing spec is
    missing — exporters render a "not yet generated" note in that case
    rather than crashing.
    """
    manufacturing = (spec.get("manufacturing") or {}) if isinstance(spec, dict) else {}
    assembly = manufacturing.get("assembly") or {}
    sequence = assembly.get("sequence") or []
    qa_gates = assembly.get("qa_gates") or []
    packaging = assembly.get("packaging") or "Standard packaging."

    steps = [
        {"step_number": idx + 1, **_enrich_step(str(s))}
        for idx, s in enumerate(sequence)
    ]

    tolerance_notes: list[str] = []
    wood = manufacturing.get("woodworking") or {}
    if wood.get("tolerance_structural_mm"):
        tolerance_notes.append(
            f"Woodworking — structural ±{wood['tolerance_structural_mm']} mm, "
            f"cosmetic ±{wood.get('tolerance_cosmetic_mm', '—')} mm."
        )
    metal = manufacturing.get("metal_fabrication") or {}
    if metal.get("tolerance_structural_mm"):
        tolerance_notes.append(
            f"Metal — structural ±{metal['tolerance_structural_mm']} mm, "
            f"cosmetic ±{metal.get('tolerance_cosmetic_mm', '—')} mm."
        )
    upholstery = manufacturing.get("upholstery") or {}
    if upholstery.get("foam_tolerance_mm"):
        tolerance_notes.append(
            f"Upholstery — foam ±{upholstery['foam_tolerance_mm']} mm; "
            f"webbing tension {upholstery.get('webbing_tension_kg_per_inch', '—')} kg/inch."
        )

    if steps:
        summary = (
            f"{len(steps)}-stage assembly. Critical path is the woodworking "
            "frame; finishing happens before hardware to keep visible faces clean."
        )
    else:
        summary = (
            "Assembly sequence will be generated once the manufacturing spec "
            "completes for this design."
        )

    return {
        "summary": summary,
        "steps": steps,
        "qa_gates": list(qa_gates),
        "packaging": packaging,
        "tolerance_notes": tolerance_notes,
    }


# ─────────────────────────────────────────────────────────────────────
# Maintenance & care guide
# ─────────────────────────────────────────────────────────────────────


# Care matrix per material family. Sourced from BRD Layer 1C
# product-knowledge guidance (finishes, leather care, fabric durability).
_CARE_MATRIX: dict[str, dict[str, list[str]]] = {
    "wood": {
        "daily": ["Wipe dust with a soft, dry microfibre cloth."],
        "weekly": ["Spot-clean spills with a barely-damp cloth, dry immediately."],
        "monthly": ["Inspect for surface scratches; touch up with manufacturer wax."],
        "annually": [
            "Reapply oil/wax finish per the material spec.",
            "Inspect joints; tighten hardware if loosening detected.",
        ],
        "warnings": [
            "Avoid direct sunlight for prolonged periods (UV bleaches grain).",
            "Keep humidity 40–60 %RH; sustained dryness can crack solid timber.",
            "No ammonia, bleach, or silicone-based polishes.",
        ],
    },
    "metal": {
        "daily": ["Dust with a soft cloth."],
        "weekly": ["Wipe with a damp cloth; dry to prevent water spots."],
        "monthly": [
            "Inspect powder-coat / anodise finish for chips; touch up promptly to prevent corrosion.",
        ],
        "annually": ["Apply a microfibre application of corrosion inhibitor on hidden faces."],
        "warnings": [
            "No abrasive scourers — they leave visible micro-scratches.",
            "Avoid acidic cleaners on brass/copper accents (causes patina drift).",
        ],
    },
    "leather": {
        "daily": ["Plump cushions; redistribute filling."],
        "weekly": ["Vacuum with a soft brush attachment; spot-blot any spills immediately."],
        "monthly": ["Wipe with a barely-damp cloth, dry immediately."],
        "annually": [
            "Condition with a pH-neutral leather conditioner (twice yearly preferred).",
        ],
        "warnings": [
            "No saddle soap, alcohol, or solvent cleaners.",
            "Keep at least 60 cm from heat sources / radiators.",
            "Direct sunlight fades and dries leather; rotate cushions to even out wear.",
        ],
    },
    "fabric": {
        "daily": ["Plump cushions; rotate seats."],
        "weekly": ["Vacuum upholstery (low-suction setting, brush attachment)."],
        "monthly": ["Spot-test any cleaner on a hidden seam first; blot spills, never rub."],
        "annually": ["Professional clean (water-based or solvent per fibre content)."],
        "warnings": [
            "Check rubs rating before commercial use (BRD threshold ≥ 30k).",
            "Direct sun fades dyes; rotate cushions every 2–3 months.",
        ],
    },
    "foam": {
        "daily": ["Redistribute by plumping after each use."],
        "weekly": ["Rotate and flip cushions for even compression."],
        "monthly": ["Inspect for permanent compression; report sag > 10 % to the studio."],
        "annually": ["Replace high-traffic cushions on a 5–7 year cycle."],
        "warnings": [
            "HD36 foam (180 kg/m³) is the BRD baseline; lower density compresses faster.",
        ],
    },
    "finish": {
        "daily": ["Dust gently with a microfibre cloth."],
        "weekly": ["Damp-cloth wipe; never use solvent on lacquer / varnish."],
        "monthly": ["Inspect for cloudiness or micro-cracking on coated surfaces."],
        "annually": ["Refresh wax-finish pieces; respray lacquer if cloudiness develops."],
        "warnings": [
            "Lacquer and PU finishes are intolerant of alcohol-based cleaners.",
            "Powder coat: no solvent; use mild detergent + warm water only.",
        ],
    },
    "hardware": {
        "daily": [],
        "weekly": ["Wipe brass/steel with a soft cloth."],
        "monthly": ["Check torque on visible fixings; tighten if loose."],
        "annually": ["Lubricate concealed hinges with a drop of light machine oil."],
        "warnings": [
            "Brass develops a natural patina — don't strip it unless you want a polished look.",
        ],
    },
}


# Ordered list — hardware/finish keywords are checked before raw
# material families because a row like "Brass Knob" should map to
# hardware (its function), not metal (its substrate). Within each
# entry the first match wins.
_KEY_TO_CATEGORY: list[tuple[str, tuple[str, ...]]] = [
    ("hardware", ("knob", "handle", "hinge", "lock", "bracket", "fastener", "screw")),
    ("finish", ("lacquer", "paint", "varnish", "stain", "wax", "powder", "anodise", "anodize")),
    ("leather", ("leather",)),
    ("fabric", ("fabric", "linen", "cotton", "wool", "velvet", "boucle", "bouclé")),
    ("foam", ("foam",)),
    ("wood", ("walnut", "oak", "teak", "plywood", "mdf", "rubberwood", "ply")),
    ("metal", ("steel", "aluminium", "aluminum", "brass", "iron", "copper")),
]


def _classify_material(name: str, category: str) -> str | None:
    """Match a material row to one of the care-matrix categories."""
    cat = (category or "").lower()
    if cat in _CARE_MATRIX:
        return cat
    nm = (name or "").lower()
    for bucket, keys in _KEY_TO_CATEGORY:
        if any(k in nm for k in keys):
            return bucket
    if cat in {"wood_solid", "wood_panel"}:
        return "wood"
    return None


def derive_maintenance_guide(spec: dict, graph: dict) -> dict[str, Any]:
    """Return a structured care guide keyed by material category present in the spec.

    Shape::

        {
          "intro": "...",
          "categories": [
            {"category": "wood", "applies_to": ["Walnut", "Oak"],
             "daily": [...], "weekly": [...], "monthly": [...],
             "annually": [...], "warnings": [...]},
            ...
          ],
          "general_notes": [...],
        }

    Categories with no matching materials in the design are omitted —
    the guide stays specific to what the client actually owns.
    """
    material = (spec.get("material") or {}) if isinstance(spec, dict) else {}
    buckets = ["primary_structure", "secondary_materials", "hardware",
               "upholstery", "finishing"]

    by_category: dict[str, list[str]] = {}
    for bucket in buckets:
        for row in (material.get(bucket) or []):
            cat = _classify_material(
                row.get("name") or "",
                row.get("category") or "",
            )
            if cat is None:
                continue
            by_category.setdefault(cat, []).append(row.get("name") or "Unnamed")

    categories: list[dict[str, Any]] = []
    for cat, applies_to in by_category.items():
        matrix = _CARE_MATRIX[cat]
        categories.append({
            "category": cat,
            "applies_to": sorted(set(applies_to)),
            "daily": list(matrix["daily"]),
            "weekly": list(matrix["weekly"]),
            "monthly": list(matrix["monthly"]),
            "annually": list(matrix["annually"]),
            "warnings": list(matrix["warnings"]),
        })

    if categories:
        intro = (
            "Care recommendations below are tailored to the specific materials "
            "in this piece. Following them keeps the finishes warranty-compliant."
        )
    else:
        intro = (
            "Care guide will be generated once the material specification "
            "completes for this design."
        )

    general = [
        "Climate the room: 18–26 °C, 40–60 %RH for best material longevity.",
        "Always test new cleaners on a hidden surface for 24 h before use.",
        "Document any incident (impact, spill, structural issue) and contact the studio promptly.",
    ]

    return {
        "intro": intro,
        "categories": categories,
        "general_notes": general,
    }


# ─────────────────────────────────────────────────────────────────────
# Render assets (Stage 14 Gap #3 — PPTX visuals)
# ─────────────────────────────────────────────────────────────────────


_ALLOWED_RENDER_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def collect_render_images(spec: dict, graph: dict) -> list[dict[str, Any]]:
    """Return a list of render image dicts ready for embedding.

    Looks in three conventional locations, in this order:
      1. ``spec["renders"]``   — explicit hand-off from the orchestrator.
      2. ``graph["renders"]``  — DesignGraph-attached renders.
      3. ``graph["assets"]``   — ORM-derived asset list with kind in
         {render_2d, thumbnail}; bytes must be already loaded.

    Each returned dict has::

        {"caption": str, "mime": str, "ext": str, "bytes": bytes}

    Missing/invalid entries are silently dropped — the export shouldn't
    crash because of one malformed render.
    """
    out: list[dict[str, Any]] = []
    candidates: list[Any] = []

    if isinstance(spec, dict):
        candidates.extend(spec.get("renders") or [])
    if isinstance(graph, dict):
        candidates.extend(graph.get("renders") or [])
        for asset in (graph.get("assets") or []):
            kind = (asset or {}).get("kind") or (asset or {}).get("asset_type") or ""
            if kind in {"render_2d", "thumbnail"}:
                candidates.append(asset)

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        data = raw.get("bytes") or raw.get("data") or raw.get("content")
        if not isinstance(data, (bytes, bytearray)):
            continue
        mime = (raw.get("mime") or raw.get("content_type") or "image/png").lower()
        ext = _ALLOWED_RENDER_MIME.get(mime)
        if ext is None:
            continue
        out.append({
            "caption": str(raw.get("caption") or raw.get("title") or "Render"),
            "mime": mime,
            "ext": ext,
            "bytes": bytes(data),
        })
    return out
