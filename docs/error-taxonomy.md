# API Error Taxonomy

> Stable contract for clients integrating with KATHA-AI. Codes
> never repurpose; new codes append; deprecation is documented
> here, not silent.

## Envelope

Every error response across every route is shaped:

```jsonc
{
  "error": "validation_failed",       // ErrorCode enum value (string)
  "message": "Request validation failed",
  "request_id": "req-abc123",          // join key for logs/audit
  "details": [                          // optional, per-field
    {"field": "project_type.type", "message": "field required"},
    {"field": "requirements.functional_needs", "message": "min 1"}
  ]
}
```

Clients **must** branch on `error` (the code), **never** on
`message` (the prose). The prose is for humans / logs.

## Codes

### 4xx — client-fixable

| Code | HTTP | When |
|---|---|---|
| `validation_failed` | 422 | Pydantic validation failed at the API boundary |
| `invalid_input` | 400 | Field present but semantically wrong |
| `missing_required_field` | 400 | Field absent (used by hand-rolled validators) |
| `project_scope_required` | 400 | Tool/route needs `project_id` in context |
| `auth_required` | 401 | No / missing token |
| `auth_invalid` | 401 | Token shape valid but signature/contents bad |
| `auth_expired` | 401 | Token expired |
| `forbidden` | 403 | Authenticated but lacking permission |
| `not_found` | 404 | Resource doesn't exist (or owner-guard hit) |
| `conflict` | 409 | State conflict (e.g. duplicate insert) |
| `gone` | 410 | Resource permanently deleted |
| `rate_limited` | 429 | Sliding window exhausted (Stage 13) |
| `quota_exceeded` | 429 | Daily / monthly cap hit |

### 5xx — server / upstream

| Code | HTTP | When |
|---|---|---|
| `internal_error` | 500 | Unhandled exception |
| `upstream_error` | 502 | Anthropic / OpenAI / S3 returned an error |
| `upstream_unavailable` | 503 | Anthropic / OpenAI / S3 unreachable |
| `tool_timeout` | 504 | Agent tool exceeded its `timeout_seconds` |

### Domain-specific

| Code | HTTP | When |
|---|---|---|
| `tool_not_found` | 404 | Agent asked for a tool that isn't registered |
| `tool_validation_error` | 422 | LLM produced input that didn't match a tool's input schema |
| `decision_not_found` | 404 | `decision_id` doesn't exist in this project |
| `decision_locked` | 409 | Append-only — direct mutation rejected |
| `project_not_found` | 404 | Project doesn't exist or owner-guard hit |
| `learning_disabled` | 403 | Action requires `User.learning_enabled`; user has it off |

### Catch-all

| Code | HTTP | When |
|---|---|---|
| `unknown` | 500 | Last resort — should never ship; treat as a bug |

## Owner-guard convention

Cross-owner reads return **`not_found`**, not `forbidden`. The same
shape regardless of whether the resource exists under another owner
or not at all — so existence isn't leaked. The Stage 8 client
profile + Stage 11 decision routes follow this; new routes should
too.

## Deprecation policy

To deprecate a code:

1. Mark it deprecated in this doc with the date.
2. Continue emitting it in current code paths.
3. After ≥ one client release cycle, route the same situation to
   a new code; leave the old one in the enum for compatibility.
4. Drop the enum value only on a v-major bump (v1 → v2).

No code in `app.observability.error_codes:ErrorCode` has been
deprecated as of Stage 13. The list above is the current full
surface.

## Adding new codes

Append-only. Process:

1. Add to `app/observability/error_codes.py:ErrorCode`.
2. Add the canonical HTTP status to `_HTTP_STATUS_BY_CODE`.
3. Add a row to the table above.
4. Don't reuse a string value. New codes get new strings.
