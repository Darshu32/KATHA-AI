# Stage 2 — Agent Architecture

> **Audience:** future-you adding new tools, debugging agent behaviour,
> or onboarding a teammate. Read after `docs/foundations.md` and
> `docs/data/pricing.md`.

---

## What Stage 2 added

The first **real LLM-powered agent loop** in KATHA. Architects can now
chat with KATHA, and the LLM decides when to call backend tools to
ground its answers in real data.

```
User chats              Provider                Tools (Stage 2: cost only)
────────────            ──────────              ──────────────────────────
"How much would    →    Claude Sonnet          estimate_project_cost
my kitchen cost              ↓                          ↓
in Mumbai?"            "I'll check"           Stage-1 cost engine
                       calls cost tool        DB-backed knowledge +
                                              snapshot
                       ←   tool result   ←
                       reads result,
                       formulates final
                       answer with citations
                            ↓
User sees       ←      "Estimated total ₹X. Source: pricing snapshot Y."
```

---

## Module map

```
backend/app/agents/
├── __init__.py                  Public surface
├── tool.py                      @tool decorator, registry, dispatcher
├── runtime/
│   ├── base.py                  Provider-agnostic types
│   ├── anthropic.py             Anthropic Claude implementation
│   └── factory.py               Provider selection
├── stream.py                    SSE event protocol
├── prompts/
│   └── architect.py             System prompt for the architect agent
├── tools/
│   ├── __init__.py              Imports = registers
│   └── cost.py                  estimate_project_cost (Stage 2 pilot)
└── architect_agent.py           Main loop

backend/app/routes/agent.py      POST /v2/chat — SSE streaming endpoint
```

---

## The lifecycle of one user message

```
POST /v2/chat
  ↓
agent_chat(body, db, user)
  ├─ Build ToolContext(session=db, actor_id=user.id, request_id=…)
  ├─ Build conversation history from body.history + body.message
  └─ Run async generator → SSE encoder → response
        │
        ▼
run_architect_agent(messages, ctx)
  │
  ├─ Loop iter 1:
  │     Provider.stream(messages, config)
  │       ├─ text_delta  → ThinkingEvent
  │       ├─ tool_call   → ToolCallEvent
  │       └─ message_done(stop_reason="tool_use")
  │     │
  │     For each tool call:
  │       call_tool(name, input, ctx)
  │         ├─ Validate input (pydantic)
  │         ├─ Run tool fn (with timeout)
  │         ├─ AuditLog.record(action="tool_call", …)
  │         └─ Return {ok, output | error, elapsed_ms}
  │       Yield ToolResultEvent
  │     Append [ToolResultContent, …] to messages as user role
  │
  ├─ Loop iter 2:
  │     Provider.stream(messages, config)
  │       ├─ text_delta  → TextEvent (final answer)
  │       └─ message_done(stop_reason="end_turn")
  │
  └─ DoneEvent(stop_reason="end_turn", iterations=2, usage=…)
```

---

## SSE event vocabulary

The event names map 1:1 to UI elements. Frontend should treat unknown
events as informational and ignore them.

| Event           | When emitted                                         | Payload keys |
|---|---|---|
| `thinking`      | Text the model produces *before* a tool call         | `text` |
| `tool_call`     | Model invoked a tool                                 | `id`, `name`, `input` |
| `tool_result`   | Tool finished                                        | `id`, `name`, `ok`, `output` \| `error`, `elapsed_ms` |
| `text`          | Text the model produces *after* tool calls (final)   | `text` |
| `done`          | Stream complete                                      | `stop_reason`, `iterations`, `input_tokens`, `output_tokens` |
| `error`         | Provider/loop error — stream ends                    | `message` |

Wire format is plain SSE:

```
event: tool_call
data: {"id":"...","name":"estimate_project_cost","input":{...}}

event: tool_result
data: {"id":"...","ok":true,"output":{...},"elapsed_ms":1240.5}
```

---

## Adding a new tool (cookbook)

Three steps. Total time: ~30 minutes.

### 1. Write the tool

```python
# app/agents/tools/clearance.py
from pydantic import BaseModel, Field
from app.agents.tool import ToolContext, tool


class ClearanceLookupInput(BaseModel):
    rule: str = Field(description="Clearance type, e.g. 'door_main_entry'")
    jurisdiction: str = Field(default="india_nbc")


class ClearanceLookupOutput(BaseModel):
    rule: str
    min_mm: int
    typ_mm: int
    max_mm: int
    source: str


@tool(
    name="lookup_clearance",
    description="Return the BRD/NBC clearance band (mm) for a given rule",
    timeout_seconds=5.0,
)
async def lookup_clearance(
    ctx: ToolContext,
    input: ClearanceLookupInput,
) -> ClearanceLookupOutput:
    # Stage 3 will fetch from DB; for now you might import the legacy
    # constants temporarily.
    ...
```

### 2. Register it (one line)

```python
# app/agents/tools/__init__.py
from app.agents.tools import clearance as _clearance  # noqa: F401
```

### 3. Test it

```python
# tests/unit/test_clearance_tool.py
import pytest
from pydantic import ValidationError

from app.agents.tool import REGISTRY


def test_clearance_tool_registered():
    assert "lookup_clearance" in REGISTRY.names()


async def test_clearance_validation_error_returns_envelope():
    from app.agents.tool import ToolContext, call_tool
    ctx = ToolContext(session=None, actor_id=None)  # ignore typing here
    result = await call_tool("lookup_clearance", {"rule": 42}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"
```

That's it. The agent will pick it up on the next request — `REGISTRY`
is a process-global singleton populated at import time.

### Conventions every new tool must follow

- **Async only.** Sync tools are rejected by the decorator.
- **Pydantic in/out.** No raw dicts. The schema is what the LLM sees.
- **Field descriptions.** Every field needs `Field(description=…)` —
  the LLM uses these to decide when to call.
- **Idempotent reads, audited writes.** If the tool writes data, set
  `audit_target_type` so every call records an `AuditEvent`.
- **Cite sources.** Output models should include the row id +
  version + source tag for every value drawn from DB. The agent
  prompt instructs the LLM to surface these in its reply.
- **Bounded timeouts.** `timeout_seconds` defaults to 30s; tighten for
  fast lookups, loosen for LLM-heavy tools (cost engine = 45s).

---

## Provider abstraction

The agent loop never imports the Anthropic SDK directly. It speaks
only the types in `app.agents.runtime.base`:

```
AgentMessage       Provider-agnostic chat turn
ProviderEvent      Streaming event from the provider
AgentProvider      Abstract base — implement to add a provider
ProviderConfig     Per-call config (model, system prompt, tools, …)
```

Adding OpenAI (Stage 5) is a matter of writing
`app/agents/runtime/openai.py` that translates these types to the
OpenAI Chat Completions / Tool Calls format.

---

## Auth + audit

- Every `/v2/chat` request goes through `get_current_user` → real
  user (or dev fallback in `dev` env).
- Every successful tool call writes an `AuditEvent`:
  ```
  action       = "tool_call"
  target_type  = <tool's audit_target_type>
  target_id    = ctx.project_id or "unscoped"
  actor_id     = current user
  request_id   = same as the SSE response
  after        = {tool, input, output_summary_keys, elapsed_ms}
  ```
- This is what makes Stage 11 transparency work: pull every audit
  event for a project, get the full trail of agent decisions.

---

## Limits + safeguards

| Limit | Default | Why |
|---|---|---|
| `MAX_ITERATIONS` (per turn) | 8 | Prevents pathological loops |
| `MAX_TOOL_CALLS` (per turn) | 12 | Caps tool budget per request |
| Tool timeout | 30s default | Tools can override; cost is 45s |
| Provider `max_tokens` | 2048 | Adjustable per call from the route |

Hitting any of these emits an `error` SSE event and ends the stream.

---

## What's next

- **Stage 4** — wrap every existing service as a tool (drawings,
  diagrams, specs, MEP, exports, …). Use this same pattern.
- **Stage 5** — multi-tool reasoning, parallel tool dispatch, OpenAI
  provider, conversation summarisation for long histories.
- **Stage 6** — RAG: a `search_knowledge` tool that hits pgvector for
  NBC / IBC / vendor catalog citations.
- **Stage 8** — DB-backed conversation memory; the route will load
  `body.history` from DB instead of accepting it from the client.
