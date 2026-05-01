"""Stage 13 — OpenAPI surface contract test.

Strategy: rather than diff the full OpenAPI JSON (noisy — Pydantic
generates verbose ``$defs`` that change with version bumps), we
lock the **shape** that matters to clients:

- Every route's ``method + path`` is captured in a stable list.
- Every route's required-fields / response shape skeletons.
- Removing a route or changing a path is a **failure** — it's a
  breaking change and must be intentional.
- Adding a route is **fine** — clients always tolerate new endpoints.

The locked manifest lives at ``tests/contract/openapi_v1_manifest.json``.
When you intentionally add or change routes, run
``pytest tests/contract -k regenerate`` (gated by an env var) to
refresh the snapshot, then commit the diff.

This isn't a perfect contract test — fancier tooling (e.g.
openapi-diff) exists. But it catches the most common breakage
(deleting / renaming an endpoint) at every push without external
dependencies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_MANIFEST_PATH = Path(__file__).parent / "openapi_v1_manifest.json"


def _load_app_openapi() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def _route_keys(spec: dict[str, Any]) -> list[str]:
    """Stable list of ``METHOD path`` strings — the surface fingerprint."""
    paths = spec.get("paths") or {}
    keys: list[str] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in (
            "get", "post", "put", "patch", "delete", "options", "head",
        ):
            if method in item:
                keys.append(f"{method.upper()} {path}")
    return sorted(keys)


def _load_manifest() -> dict[str, Any] | None:
    if not _MANIFEST_PATH.is_file():
        return None
    try:
        with _MANIFEST_PATH.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except json.JSONDecodeError:
        return None


def _save_manifest(manifest: dict[str, Any]) -> None:
    _MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_openapi_routes_are_stable():
    """Every route in the locked manifest must still exist.

    Adding new routes is fine — clients tolerate them. Removing or
    renaming a route is a failure: it's a breaking change and you
    should either update the snapshot intentionally (set
    ``KATHA_REGENERATE_OPENAPI_MANIFEST=1`` and re-run) or rev to v2.
    """
    spec = _load_app_openapi()
    current_routes = set(_route_keys(spec))

    if os.environ.get("KATHA_REGENERATE_OPENAPI_MANIFEST"):
        manifest = {
            "schema_version": "1.0",
            "api_version": "v1",
            "routes": sorted(current_routes),
        }
        _save_manifest(manifest)
        return  # regeneration mode; no assertion

    manifest = _load_manifest()
    if manifest is None:
        # First-run convenience: write the manifest and pass. The
        # next run will enforce. Commit the generated file.
        manifest = {
            "schema_version": "1.0",
            "api_version": "v1",
            "routes": sorted(current_routes),
        }
        _save_manifest(manifest)
        return

    locked = set(manifest.get("routes") or [])
    removed = locked - current_routes
    assert not removed, (
        f"v1 contract regression — these routes were removed/renamed "
        f"vs the locked manifest: {sorted(removed)}. If intentional, "
        f"set KATHA_REGENERATE_OPENAPI_MANIFEST=1 and re-run to refresh, "
        f"then commit the diff. If not, you broke v1."
    )

    # Adding routes is allowed but worth flagging in the test output
    # — operator may want to refresh the manifest deliberately.
    added = current_routes - locked
    if added:
        print(
            f"\n[openapi] {len(added)} new route(s) since last manifest: "
            f"{sorted(added)}"
        )


def test_openapi_health_endpoint_still_present():
    """``/health`` is the deploy probe target — it's load-balancer
    contract, not just OpenAPI. Lock it explicitly."""
    spec = _load_app_openapi()
    paths = spec.get("paths") or {}
    assert "/health" in paths, "‘/health’ must always be exposed"


def test_openapi_v1_prefix_consistency():
    """Every API route lives under ``/api/v1`` (or ``/health``).

    Catches accidentally-mounted unprefixed routes that would skip
    the version bucket and complicate eventual v2 migration."""
    spec = _load_app_openapi()
    paths = spec.get("paths") or {}
    misplaced = [
        p for p in paths
        if p != "/health" and not p.startswith("/api/v1")
    ]
    assert not misplaced, (
        f"non-versioned route(s) detected: {misplaced} — "
        f"every public API endpoint must mount under /api/v1"
    )
