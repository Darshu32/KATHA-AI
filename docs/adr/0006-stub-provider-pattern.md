# ADR 0006 — Stub-provider pattern for external integrations

Status: Accepted
Date: 2026-04-30 (initial); reaffirmed 2026-05-01 (Stage 12)
Stage: 5B / 7 / 12

## Context

Multiple stages need external integrations whose credentials
aren't always available:

- Stage 5B: OpenAI embeddings.
- Stage 7: Anthropic vision (image analysis), Gemini image
  generation, S3-compatible storage.
- Stage 12: MCX commodities, FX rates, GST classification, vendor
  scrapers, Slack webhook.

Tests run in CI without API keys. Local dev should boot without
a Stripe sandbox / S3 bucket / commodity feed. Production needs
the real thing. One pattern has to cover all of these.

## Decision

**Every external integration ships behind an abstract base class
with at least two implementations:**

1. **`StubXProvider`** — deterministic, hermetic, returns
   seed-aligned data without any network call. Used by tests +
   dev when credentials aren't set.
2. **`RealXProvider`** — production implementation that hits the
   actual API.

The selection happens at app-startup or per-request via a
configuration flag, never at the call site:

```python
# app/some_service.py
from app.vision import VisionProvider, get_vision_provider

vision = get_vision_provider()  # returns StubVisionProvider OR
                                 # AnthropicVisionProvider based on
                                 # settings.anthropic_api_key
result = await vision.analyse(image_url)
```

The downstream caller has no idea which provider it got. Tests
inject the stub; prod gets the real thing.

## Alternatives considered

- **Hard-fail when key missing** — rejected. Local dev becomes
  impossible without provisioning every integration; tests can't
  run in CI; "it works on my machine" failures multiply.
- **Mock at the test boundary** — rejected. Mocks are per-test
  scaffolding; stubs are first-class implementations. A `Stub*`
  class can be exercised in *integration* tests too, not just
  unit tests.
- **Feature flags at the call site** — rejected. Every consumer
  would re-implement the "is this configured?" check. Errors
  drift; silent fallthroughs sneak in.
- **Don't ship the integration until the key is acquired** —
  rejected. The framework + the integration are the same code;
  shipping the framework first and the implementation later is
  cleaner than blocking the framework on a credential. Stage 12
  is the canonical example: market-data feeds ship as framework
  + stubs *now*; real providers swap in when credentials land.

## Consequences

- **Tests run free** — no `httpx-mock` setup, no per-test patching.
  Stub providers are deterministic; assertions stay stable.
- **Local dev boots without credentials** — `Settings` has empty
  defaults for every external key. The service factory routes to
  the stub when the key is empty.
- **Real-provider files document the integration path** — even
  when the implementation isn't filled in, the file documents
  the API contract, the env vars needed, and the expected response
  shape.
- **CI is offline** — every test in `tests/` runs without internet
  access. This was a hard requirement from Stage 0.
- **Stub fidelity matters** — the stub must produce data shaped
  identically to the real provider, or tests pass against the
  stub and fail against prod. Each stub is reviewed against the
  real provider's response schema.

This ADR is invoked by every "we don't have the API key yet"
decision. Stage 12's "framework + stubs, no live integrations"
is the most extensive application.

Re-evaluate at: never — this is a core operating principle, not a
tactical choice.
