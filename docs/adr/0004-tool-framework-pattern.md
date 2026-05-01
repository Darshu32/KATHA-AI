# ADR 0004 — One-decorator tool framework with Pydantic I/O + audit + confidence

Status: Accepted
Date: 2026-04-30 (initial); 2026-05-01 (Stage 11 retrofit)
Stage: 2 / 11

## Context

The agent surface grew from 1 tool (Stage 2) to 81 tools (Stage 11).
Every tool needs:

- JSON-schema definition for the LLM provider.
- Input + output validation.
- Per-tool timeout.
- Audit-event emission (write tools).
- (Stage 11) Confidence + provenance attached to every result.

Without a framework, every tool would re-implement these. With a
heavy framework, every tool would carry boilerplate.

## Decision

A single `@tool` decorator (`app/agents/tool.py`) accepting:

```python
@tool(
    name="...",
    description="...",
    timeout_seconds=30.0,
    audit_target_type="..." | None,
    confidence_kind="..." | None,
)
async def my_tool(ctx: ToolContext, input: MyInput) -> MyOutput:
    ...
```

The decorator:
- Extracts the input + output Pydantic models from the function
  signature.
- Registers the tool in a module-level `REGISTRY`.
- Generates the JSON-schema the LLM provider sees.

The dispatcher (`call_tool`) handles:
- Input validation (returns structured error envelope on failure).
- Timeout (returns structured error envelope on timeout).
- Audit emission (write tools).
- (Stage 11) Confidence + provenance attached to every successful
  result envelope.

## Alternatives considered

- **Per-tool boilerplate** — rejected. 81 tools × 20 lines of
  boilerplate = 1620 lines of duplicate code. Audit, timeout,
  schema gen would drift between tools.
- **OpenAI's function-calling stub generator** — rejected. Vendor-
  specific; we need both Anthropic + OpenAI schemas. Generating
  ourselves is one shared path.
- **Heavier framework (LangChain, Semantic Kernel)** — rejected.
  Their abstractions cover use cases we don't have (multi-step
  graphs, planners). Cost = locked-in mental model + frequent
  upstream churn. Our framework is ~400 lines and we own all of
  it.

## Consequences

- **Adding a tool is one file** — author the function with typed
  Pydantic in/out, slap `@tool` on it. Registry is auto-populated.
- **Tests are uniform** — every tool's contract is the same
  signature. Stage 4–11 unit tests assert audit_target_type,
  confidence_kind, schema requirements via the registry's
  reflection methods.
- **Confidence + provenance retrofit was free** (Stage 11) — one
  change in `call_tool` propagated to all 78 prior tools without
  touching individual tool modules. ADR 0007 documents that
  decision separately.
- **Swapping LLM providers is contained** — `definitions_for_llm()`
  emits provider-agnostic JSON; the per-provider adapter
  formats it. Both Anthropic + OpenAI consume the same registry.
- **The framework is ours forever** — no external upgrades to track.
  Trade-off: we reinvent some patterns (e.g. retry policies aren't
  built in; tools handle their own retries). Acceptable scope.

Re-evaluate at: when we need a multi-step planner / graph executor
that the registry doesn't handle. Stage 14+ if it ever lands.
