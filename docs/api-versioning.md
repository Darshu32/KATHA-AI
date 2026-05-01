# API Versioning Policy

> Stage 13 freezes `v1`. The OpenAPI surface is locked by a
> contract test. Breaking changes go to `v2`; non-breaking changes
> ship in `v1` continuously.

## What's a breaking change?

Breaking (require v-bump):

- Removing a route, or renaming its path
- Changing an HTTP method on an existing path
- Removing or renaming a field in a request body
- Removing or renaming a field in a response body
- Changing the type of an existing field (e.g. `int → string`)
- Tightening validation (`max_length 100 → 50`, `optional → required`)
- Changing or repurposing an error code's meaning

Non-breaking (ship in current version):

- Adding new routes
- Adding new optional request fields
- Adding new fields to response bodies
- **Loosening** validation
- Adding new error codes (without re-purposing old ones)
- Adding new tools, new domain enums, new HTTP status info-headers

## Surface lock

`tests/contract/test_openapi_surface.py` reads
`tests/contract/openapi_v1_manifest.json` and asserts every
locked route still exists. CI fails on removal.

To update the snapshot intentionally:

```bash
KATHA_REGENERATE_OPENAPI_MANIFEST=1 pytest tests/contract -k stable
```

Then commit the diff with a message that explains *which* routes
moved and why.

## Pathing

- Public API: `/api/v1/...`
- Internal probes: `/health`, `/docs`, `/redoc`, `/openapi.json`
- Future v2: `/api/v2/...` runs side-by-side; the same FastAPI
  app mounts both router sets until v1 is sunsetted.

## v2 trigger

Don't rev to v2 for a single breaking change — accumulate a
batch. Realistic triggers:

- Auth / identity model overhaul (e.g. workspace-scoped resources)
- Major shape change to the design graph JSONB
- Currency-strict pricing (today INR is implicit; v2 might require
  `currency` on every monetary field)
- Streaming-first chat (today HTTP-style; v2 might be SSE-default)

Until then: v1 grows, doesn't change.

## Deprecation in v1

When a v1 endpoint is going away in v2:

1. Add `Deprecated: true` in the route's OpenAPI metadata
   (FastAPI: `@router.get(..., deprecated=True)`).
2. Document the v2 successor in this file.
3. Continue serving v1 traffic without performance regression
   until v2 is stable.

No v1 endpoints are deprecated as of Stage 13.
