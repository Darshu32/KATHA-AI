"""The tool framework — heart of KATHA's agentic layer.

Why this matters
----------------
Every backend service we want the agent to invoke ends up here. The
decorator turns a typed async function into a registered tool the
LLM can call. The registry exposes JSON-schema definitions to the
provider layer and dispatches calls back to Python.

This module is the **cookbook** for Stages 3–10 — when we wrap the
drawing engine, MEP sizing, NBC compliance, and so on, every one of
those services becomes a ``@tool`` exactly like ``estimate_project_cost``.

Anatomy of a tool
-----------------
::

    class EstimateCostInput(BaseModel):
        '''What the LLM has to provide.'''
        project_id: str = Field(description="UUID of the project")
        city: str = Field(default="delhi", description="...")

    class EstimateCostOutput(BaseModel):
        '''What the LLM (and ultimately the user) sees.'''
        total_inr: float
        ...

    @tool(
        name="estimate_project_cost",
        description="Compute a parametric cost estimate ...",
    )
    async def estimate_project_cost(
        ctx: ToolContext,
        input: EstimateCostInput,
    ) -> EstimateCostOutput:
        ...

What you get for free
---------------------
- JSON-schema auto-generated from ``EstimateCostInput`` (Pydantic v2
  ``model_json_schema()``).
- Argument validation: bad LLM input fails *before* the function runs
  and produces an :class:`ToolValidationError`.
- Audit logging: every successful call writes an ``AuditEvent`` row
  with the input/output diff and the agent ``request_id``.
- Latency timing + structured log line per call.
- Error envelope: any exception becomes a JSON-serialisable dict the
  LLM can read and recover from.

Anti-goals
----------
- We do **not** auto-detect tools — every tool must be imported from
  ``app.agents.tools`` so the registry stays explicit.
- We do **not** support synchronous tools — pick async or move along.
- We do **not** allow positional arguments — tools take a single
  ``input`` Pydantic model. This keeps the LLM contract clean.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.confidence import KINDS as _CONFIDENCE_KINDS, build_confidence
from app.db import AuditLog
from app.observability.request_id import get_request_id
from app.provenance import build_banner

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────


class ToolError(RuntimeError):
    """Base for all tool-execution errors that should be returned to the LLM."""


class ToolValidationError(ToolError):
    """The LLM produced input that doesn't match the tool's input schema."""


class ToolNotFoundError(ToolError):
    """The LLM tried to call a tool name we don't have registered."""


class ToolTimeoutError(ToolError):
    """The tool took longer than its declared timeout."""


# ─────────────────────────────────────────────────────────────────────
# Context passed to every tool
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ToolContext:
    """Request-scoped state every tool sees.

    Tools receive the same ``ToolContext`` for every call within a
    single agent turn. They use it for:

    - DB session (a single transaction across all tool calls in the turn)
    - Identifying the actor (writes go through repositories with the
      right ``actor_id``)
    - Identifying the project + chat session in scope
    - Audit / observability (request_id)
    - Inter-tool state (``state`` dict for tools that share intermediate
      results inside one turn)
    """

    session: AsyncSession
    actor_id: Optional[str] = None
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.request_id is None:
            self.request_id = get_request_id()


# ─────────────────────────────────────────────────────────────────────
# Spec + registry
# ─────────────────────────────────────────────────────────────────────


InputModel = TypeVar("InputModel", bound=BaseModel)
OutputModel = TypeVar("OutputModel", bound=BaseModel)


# Concrete signature every tool function must satisfy.
ToolFn = Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]


@dataclass
class ToolSpec:
    """Self-describing record of one registered tool."""

    name: str
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    fn: ToolFn
    timeout_seconds: float = 30.0
    audit_target_type: Optional[str] = None
    # If set, every successful call writes an AuditEvent with this
    # ``target_type``. Skip for read-only tools that don't change state.
    confidence_kind: Optional[str] = None
    # Stage 11 — declares the tool's source of confidence (see
    # ``app.agents.confidence.KINDS``). When ``None`` the framework
    # falls back to the curated ``_DEFAULT_KIND_BY_TOOL`` map keyed
    # by tool ``name``. Tools authored in Stage 11+ should declare
    # this on the ``@tool`` decorator instead of relying on the map.

    def input_schema(self) -> dict[str, Any]:
        """JSON-schema the provider layer hands to the LLM."""
        schema = self.input_model.model_json_schema()
        # Anthropic's tool-use format is friendlier without ``$defs`` at
        # the top level — Pydantic produces them when the model has
        # nested types. We leave them for now; both Anthropic and
        # OpenAI accept them and inline-resolve.
        return schema


class ToolRegistry:
    """Module-level singleton. Every ``@tool`` call mutates this."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool name: {spec.name!r}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown tool: {name!r}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def definitions_for_llm(self) -> list[dict[str, Any]]:
        """Provider-agnostic JSON each tool's schema in shape::

            {"name": ..., "description": ..., "input_schema": {...}}
        """
        return [
            {
                "name": s.name,
                "description": s.description,
                "input_schema": s.input_schema(),
            }
            for s in self._tools.values()
        ]


# Single registry — Stage 2 keeps it global. If we ever need
# per-project / per-tenant tool sets we can make it scoped.
REGISTRY = ToolRegistry()


# ─────────────────────────────────────────────────────────────────────
# Decorator
# ─────────────────────────────────────────────────────────────────────


def tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    timeout_seconds: float = 30.0,
    audit_target_type: Optional[str] = None,
    confidence_kind: Optional[str] = None,
) -> Callable[[ToolFn], ToolFn]:
    """Mark an async function as an LLM-callable tool.

    Parameters
    ----------
    name:
        LLM-visible name. Defaults to the function name.
    description:
        Short prose the LLM uses to decide when to call. Falls back to
        the function's docstring first paragraph.
    timeout_seconds:
        Per-call cap. Tools exceeding this raise :class:`ToolTimeoutError`.
    audit_target_type:
        If set, every successful call records an AuditEvent with this
        ``target_type``. Use for write tools; read tools can leave None.
    confidence_kind:
        Stage 11 — one of :data:`app.agents.confidence.KINDS`. Declares
        why the framework should trust this tool's output. ``None`` =
        fall back to the curated map (``_DEFAULT_KIND_BY_TOOL``) and
        finally to ``"unknown"``. Tools whose confidence depends on
        the run (RAG, LLM self-report) should leave this ``None`` and
        set ``ctx.state["confidence_override"]`` at runtime instead.
    """

    if confidence_kind is not None and confidence_kind not in _CONFIDENCE_KINDS:
        # Fail at decoration time so a typo can't ship into prod.
        raise ValueError(
            f"@tool confidence_kind={confidence_kind!r} is not in "
            f"{_CONFIDENCE_KINDS}"
        )

    def decorator(fn: ToolFn) -> ToolFn:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        if len(params) != 2:
            raise TypeError(
                f"@tool {fn.__name__}: must take exactly 2 args (ctx, input); "
                f"got {len(params)}"
            )
        ctx_param, input_param = params

        # Validate signature.
        if ctx_param.annotation is not ToolContext:
            raise TypeError(
                f"@tool {fn.__name__}: first arg must be annotated `ctx: ToolContext`"
            )
        input_model = input_param.annotation
        if not (inspect.isclass(input_model) and issubclass(input_model, BaseModel)):
            raise TypeError(
                f"@tool {fn.__name__}: second arg must be a Pydantic BaseModel; "
                f"got {input_model!r}"
            )
        output_model = sig.return_annotation
        if not (inspect.isclass(output_model) and issubclass(output_model, BaseModel)):
            raise TypeError(
                f"@tool {fn.__name__}: return annotation must be a Pydantic BaseModel; "
                f"got {output_model!r}"
            )
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(f"@tool {fn.__name__}: must be `async def`")

        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or _first_para(fn.__doc__),
            input_model=input_model,
            output_model=output_model,
            fn=fn,
            timeout_seconds=timeout_seconds,
            audit_target_type=audit_target_type,
            confidence_kind=confidence_kind,
        )
        REGISTRY.register(spec)
        return fn

    return decorator


def _first_para(docstring: Optional[str]) -> str:
    if not docstring:
        return ""
    text = inspect.cleandoc(docstring)
    return text.split("\n\n", 1)[0]


# ─────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────


async def call_tool(
    name: str,
    raw_input: dict[str, Any],
    ctx: ToolContext,
    *,
    registry: ToolRegistry = REGISTRY,
) -> dict[str, Any]:
    """Run one tool. Returns a dict with ``ok`` / ``output`` / ``error``.

    The dict shape is the LLM-visible result. Any exception inside the
    tool is converted to a structured error so the agent can recover
    instead of crashing.
    """
    spec = registry.get(name)

    # 1. Validate input.
    try:
        input_obj = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        log.warning("tool.%s validation_error: %s", name, exc)
        return {
            "ok": False,
            "error": {
                "type": "validation_error",
                "message": str(exc),
                "details": exc.errors(),
            },
        }

    # 2. Run with timeout.
    started = time.perf_counter()
    try:
        output_obj = await asyncio.wait_for(
            spec.fn(ctx, input_obj),
            timeout=spec.timeout_seconds,
        )
    except asyncio.TimeoutError:
        log.warning("tool.%s timed out after %.1fs", name, spec.timeout_seconds)
        return {
            "ok": False,
            "error": {
                "type": "timeout",
                "message": f"Tool {name!r} exceeded {spec.timeout_seconds}s",
            },
        }
    except ToolError as exc:
        # Tool-author-raised — already a known shape, just surface.
        log.info("tool.%s tool_error: %s", name, exc)
        return {
            "ok": False,
            "error": {"type": exc.__class__.__name__.lower(), "message": str(exc)},
        }
    except Exception as exc:  # noqa: BLE001 — catch-all for LLM safety
        log.exception("tool.%s unhandled error", name)
        return {
            "ok": False,
            "error": {
                "type": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # 3. Validate output (defensive — catches bad tool implementations).
    if not isinstance(output_obj, spec.output_model):
        log.error(
            "tool.%s returned %s; expected %s",
            name,
            type(output_obj).__name__,
            spec.output_model.__name__,
        )
        return {
            "ok": False,
            "error": {
                "type": "internal_error",
                "message": (
                    f"Tool {name!r} returned wrong type: "
                    f"{type(output_obj).__name__}"
                ),
            },
        }
    output_dict = output_obj.model_dump(mode="json")

    # 4. Audit (write tools only).
    if spec.audit_target_type:
        try:
            await AuditLog.record(
                ctx.session,
                actor_id=ctx.actor_id,
                actor_kind="agent" if ctx.actor_id else "system",
                action="tool_call",
                target_type=spec.audit_target_type,
                target_id=ctx.project_id or "unscoped",
                after={
                    "tool": name,
                    "input": input_obj.model_dump(mode="json"),
                    "output_summary_keys": sorted(output_dict.keys()),
                    "elapsed_ms": round(elapsed_ms, 2),
                },
                request_id=ctx.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("tool.%s audit failed: %s", name, exc)

    log.info(
        "tool.%s ok elapsed_ms=%.1f",
        name,
        elapsed_ms,
        extra={"tool": name, "elapsed_ms": elapsed_ms},
    )

    # 5. Stage 11 — confidence + provenance retrofit.
    #
    # Every successful tool result carries a confidence block (score
    # + kind + factors) and a provenance banner (catalog versions +
    # tool stamp + request_id). Tools can override the confidence
    # at runtime by setting ``ctx.state["confidence_override"]``
    # before returning — RAG retrievers do this with the top
    # similarity score; LLM tools do this with their self-reported
    # confidence.
    runtime_override = None
    if isinstance(ctx.state, dict):
        runtime_override = ctx.state.get("confidence_override")
    confidence = build_confidence(
        declared_kind=spec.confidence_kind,
        tool_name=name,
        runtime_override=runtime_override if isinstance(runtime_override, dict) else None,
    )
    provenance = build_banner(
        tool=name,
        tool_invocation_kind="agent_call",
        request_id=ctx.request_id,
    )

    return {
        "ok": True,
        "output": output_dict,
        "elapsed_ms": round(elapsed_ms, 2),
        "confidence": confidence.to_dict(),
        "provenance": provenance,
    }
