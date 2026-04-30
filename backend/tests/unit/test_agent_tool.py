"""Tests for the @tool decorator + registry + dispatcher.

Run without DB or LLM — uses an isolated registry per test so the
global REGISTRY isn't polluted.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field

from app.agents.tool import (
    ToolContext,
    ToolNotFoundError,
    ToolRegistry,
    ToolSpec,
    call_tool,
    tool,
)


# ─────────────────────────────────────────────────────────────────────
# Decorator validation
# ─────────────────────────────────────────────────────────────────────


def test_tool_decorator_rejects_sync_functions():
    class _In(BaseModel):
        x: int

    class _Out(BaseModel):
        y: int

    with pytest.raises(TypeError, match="async def"):
        @tool()
        def bad(ctx: ToolContext, input: _In) -> _Out:  # type: ignore[misc]
            return _Out(y=input.x)


def test_tool_decorator_rejects_wrong_arity():
    class _In(BaseModel):
        x: int

    class _Out(BaseModel):
        y: int

    with pytest.raises(TypeError, match="exactly 2 args"):
        @tool()
        async def bad(ctx: ToolContext) -> _Out:  # type: ignore[misc]
            return _Out(y=0)


def test_tool_decorator_requires_pydantic_input():
    class _Out(BaseModel):
        y: int

    with pytest.raises(TypeError, match="Pydantic BaseModel"):
        @tool()
        async def bad(ctx: ToolContext, input: dict) -> _Out:  # type: ignore[arg-type]
            return _Out(y=0)


def test_tool_decorator_requires_pydantic_output():
    class _In(BaseModel):
        x: int

    with pytest.raises(TypeError, match="Pydantic BaseModel"):
        @tool()
        async def bad(ctx: ToolContext, input: _In) -> dict:  # type: ignore[type-var]
            return {}


# ─────────────────────────────────────────────────────────────────────
# Registry behaviour
# ─────────────────────────────────────────────────────────────────────


class _AddInput(BaseModel):
    a: int = Field(description="first")
    b: int = Field(description="second")


class _AddOutput(BaseModel):
    sum: int


async def _add(ctx: ToolContext, input: _AddInput) -> _AddOutput:
    """Add two numbers."""
    return _AddOutput(sum=input.a + input.b)


def _make_registry_with_add() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="add",
            description="add two ints",
            input_model=_AddInput,
            output_model=_AddOutput,
            fn=_add,
        )
    )
    return reg


def test_registry_returns_definitions_with_required_keys():
    reg = _make_registry_with_add()
    defs = reg.definitions_for_llm()
    assert len(defs) == 1
    d = defs[0]
    assert d["name"] == "add"
    assert "description" in d
    assert "input_schema" in d
    schema = d["input_schema"]
    assert schema["type"] == "object"
    assert "a" in schema["properties"] and "b" in schema["properties"]


def test_registry_rejects_duplicate_names():
    reg = _make_registry_with_add()
    with pytest.raises(ValueError, match="Duplicate"):
        reg.register(
            ToolSpec(
                name="add",
                description="duplicate",
                input_model=_AddInput,
                output_model=_AddOutput,
                fn=_add,
            )
        )


def test_registry_get_unknown_raises():
    reg = _make_registry_with_add()
    with pytest.raises(ToolNotFoundError):
        reg.get("nope")


# ─────────────────────────────────────────────────────────────────────
# Dispatcher (call_tool)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx():
    return ToolContext(session=None, actor_id=None, request_id="req-test")  # type: ignore[arg-type]


async def test_call_tool_happy_path(ctx):
    reg = _make_registry_with_add()
    result = await call_tool("add", {"a": 2, "b": 3}, ctx, registry=reg)
    assert result["ok"] is True
    assert result["output"] == {"sum": 5}
    assert "elapsed_ms" in result


async def test_call_tool_validation_error(ctx):
    reg = _make_registry_with_add()
    result = await call_tool("add", {"a": "not-an-int"}, ctx, registry=reg)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_call_tool_unknown_tool(ctx):
    reg = _make_registry_with_add()
    with pytest.raises(ToolNotFoundError):
        await call_tool("missing", {}, ctx, registry=reg)


async def test_call_tool_internal_error_envelope(ctx):
    reg = ToolRegistry()

    class _In(BaseModel):
        x: int

    class _Out(BaseModel):
        y: int

    async def _explode(ctx: ToolContext, input: _In) -> _Out:
        raise RuntimeError("boom")

    reg.register(
        ToolSpec(
            name="explode",
            description="always errors",
            input_model=_In,
            output_model=_Out,
            fn=_explode,
        )
    )
    result = await call_tool("explode", {"x": 1}, ctx, registry=reg)
    assert result["ok"] is False
    assert result["error"]["type"] == "internal_error"
    assert "boom" in result["error"]["message"]


async def test_call_tool_timeout(ctx):
    reg = ToolRegistry()

    class _In(BaseModel):
        x: int

    class _Out(BaseModel):
        y: int

    async def _slow(ctx: ToolContext, input: _In) -> _Out:
        await asyncio.sleep(1.0)
        return _Out(y=input.x)

    reg.register(
        ToolSpec(
            name="slow",
            description="sleeps too long",
            input_model=_In,
            output_model=_Out,
            fn=_slow,
            timeout_seconds=0.05,
        )
    )
    result = await call_tool("slow", {"x": 1}, ctx, registry=reg)
    assert result["ok"] is False
    assert result["error"]["type"] == "timeout"


async def test_call_tool_wrong_return_type(ctx):
    reg = ToolRegistry()

    class _In(BaseModel):
        x: int

    class _Out(BaseModel):
        y: int

    class _Other(BaseModel):
        z: int

    async def _wrong(ctx: ToolContext, input: _In) -> _Out:
        return _Other(z=input.x)  # type: ignore[return-value]

    reg.register(
        ToolSpec(
            name="wrong",
            description="returns wrong type",
            input_model=_In,
            output_model=_Out,
            fn=_wrong,
        )
    )
    result = await call_tool("wrong", {"x": 1}, ctx, registry=reg)
    assert result["ok"] is False
    assert result["error"]["type"] == "internal_error"


# ─────────────────────────────────────────────────────────────────────
# Cost tool registers correctly
# ─────────────────────────────────────────────────────────────────────


def test_cost_tool_registered_in_global_registry():
    """Importing app.agents.tools registers the cost tool by side-effect."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert "estimate_project_cost" in REGISTRY.names()
    spec = REGISTRY.get("estimate_project_cost")
    assert spec.audit_target_type == "cost_engine"
    schema = spec.input_schema()
    # LLM-required fields surface in the schema.
    assert "piece_name" in schema["properties"]
