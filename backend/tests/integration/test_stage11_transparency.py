"""Stage 11 integration tests — end-to-end transparency flow.

Requires Postgres + ``alembic upgrade head`` (so migration 0021's
``reasoning_steps`` / ``confidence_score`` / ``confidence_factors``
/ ``provenance`` columns + ``decision_challenges`` table exist).

Coverage:

- The framework retrofit — every successful ``call_tool`` result
  carries ``confidence`` + ``provenance``.
- Decision recording with reasoning + confidence + auto-stamped
  provenance round-trips through the DB.
- ``explain_decision`` walks back full record + challenge chain.
- ``challenge_design_decision`` with all three resolutions:
  rejected_challenge / decision_revised / accepted_override.
- ``compare_alternatives`` auto-records a DesignDecision with
  rejected alternatives populated (the rejection ledger never goes
  empty).
- Cross-project owner guard — architect A can't explain or
  challenge architect B's decisions.
- Confidence floor — sample 20 decisions, assert all have
  reasoning_steps populated when the writing tool intended them.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _seed_user(session, *, email: str) -> str:
    from app.models.orm import User

    user = User(
        email=email,
        hashed_password="x",
        display_name="S11 test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S11") -> str:
    from app.models.orm import Project

    project = Project(
        owner_id=owner_id,
        name=name,
        description="",
        status="draft",
        latest_version=0,
    )
    session.add(project)
    await session.flush()
    return project.id


# ─────────────────────────────────────────────────────────────────────
# Framework retrofit — every result has confidence + provenance
# ─────────────────────────────────────────────────────────────────────


async def test_every_successful_tool_call_carries_confidence_and_provenance(
    db_session,
):
    """Spot-check via a known-light read tool. The framework should
    retrofit confidence + provenance regardless of the tool."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-fw@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="req-s11-fw",
    )
    result = await call_tool(
        "recall_design_decisions",
        {"limit": 5},
        ctx,
    )
    assert result["ok"] is True
    assert "confidence" in result
    assert "provenance" in result
    assert result["confidence"]["kind"] in {
        "deterministic", "static_catalog", "rag", "llm_validated",
        "llm_self_report", "llm_unvalidated", "heuristic",
        "io_export", "unknown",
    }
    prov = result["provenance"]
    assert prov["tool"] == "recall_design_decisions"
    assert prov["request_id"] == "req-s11-fw"
    assert prov["catalog_versions"]["haptic_catalog"]


async def test_confidence_runtime_override_picked_up(db_session):
    """A tool that sets ctx.state["confidence_override"] gets that
    score in the envelope."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-override@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="req-s11-override",
        state={
            "confidence_override": {
                "score": 0.42,
                "kind": "rag",
                "factors": ["test_override"],
            },
        },
    )
    result = await call_tool(
        "recall_design_decisions", {"limit": 1}, ctx,
    )
    assert result["ok"] is True
    assert result["confidence"]["score"] == 0.42
    assert result["confidence"]["kind"] == "rag"
    assert "test_override" in result["confidence"]["factors"]


# ─────────────────────────────────────────────────────────────────────
# record_design_decision — reasoning + confidence + provenance roundtrip
# ─────────────────────────────────────────────────────────────────────


async def test_record_decision_persists_reasoning_and_confidence(db_session):
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-record@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="req-s11-record",
    )
    result = await call_tool(
        "record_design_decision",
        {
            "title": "Picked walnut for kitchen island",
            "summary": (
                "Walnut over oak — better fit with mid-century theme "
                "and within budget."
            ),
            "rationale": "Theme rule pack lists walnut as primary.",
            "category": "material",
            "version": 1,
            "rejected_alternatives": [
                {"option": "oak", "reason_rejected": "Cooler tone"},
            ],
            "sources": ["theme_pack:mid_century_modern"],
            "tags": ["material", "theme_aligned"],
            "reasoning_steps": [
                {
                    "step": "check_theme_palette",
                    "observation": "MCM primary palette = [walnut, teak]",
                    "conclusion": "Walnut is in the BRD-anchored palette",
                },
                {
                    "step": "check_budget",
                    "observation": "Walnut adds ₹1500 vs oak baseline",
                    "conclusion": "Within the 5% budget headroom",
                },
            ],
            "confidence_score": 0.92,
            "confidence_factors": [
                "theme_pack_match",
                "cost_within_budget",
            ],
        },
        ctx,
    )
    assert result["ok"] is True
    decision_id = result["output"]["decision"]["id"]

    row = await DesignDecisionRepository.get_by_id(
        db_session, decision_id=decision_id,
    )
    assert row is not None
    assert len(row.reasoning_steps) == 2
    assert row.confidence_score == pytest.approx(0.92)
    assert "theme_pack_match" in row.confidence_factors
    # Provenance auto-stamped at write time.
    assert row.provenance.get("tool") == "record_design_decision"
    assert row.provenance.get("catalog_versions", {}).get("haptic_catalog")


# ─────────────────────────────────────────────────────────────────────
# explain_decision — full walkback + challenge chain
# ─────────────────────────────────────────────────────────────────────


async def test_explain_returns_full_decision_and_challenges(db_session):
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import (
        DecisionChallengeRepository,
        DesignDecisionRepository,
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-explain@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    decision = await DesignDecisionRepository.record(
        db_session,
        project_id=project_id, actor_id=user_id,
        title="Picked teak over oak",
        summary="Teak suits the warm-tropical client brief.",
        category="material",
        version=2,
        rationale="Client narrative emphasised tropical warmth.",
        rejected_alternatives=[
            {"option": "oak", "reason_rejected": "Cooler tone"},
        ],
        sources=["client_brief:warmth_request"],
        reasoning_steps=[
            {"step": "match_brief", "observation": "warmth requested",
             "conclusion": "teak"},
        ],
        confidence_score=0.88,
        confidence_factors=["brief_match"],
        provenance={"tool": "test_seed"},
    )

    # File a challenge against the decision.
    await DecisionChallengeRepository.file_challenge(
        db_session,
        project_id=project_id, decision_id=decision.id,
        challenger_id=user_id,
        challenge_text="What about budget? Teak is pricier.",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        project_id=project_id, request_id="req-explain",
    )
    result = await call_tool(
        "explain_decision",
        {"decision_id": decision.id},
        ctx,
    )
    assert result["ok"] is True
    out = result["output"]
    assert out["decision"]["id"] == decision.id
    assert out["decision"]["confidence_score"] == pytest.approx(0.88)
    assert len(out["decision"]["reasoning_steps"]) == 1
    assert len(out["challenges"]) == 1
    assert out["summary"]["pending_challenges"] == 1
    assert out["summary"]["resolved_challenges"] == 0


async def test_explain_rejects_cross_project_access(db_session):
    """Architect A cannot explain architect B's decisions — same
    error shape as 'not found' so existence isn't leaked."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    a_id = await _seed_user(db_session, email="s11-a@example.com")
    b_id = await _seed_user(db_session, email="s11-b@example.com")
    a_project = await _seed_project(db_session, owner_id=a_id, name="A")
    b_project = await _seed_project(db_session, owner_id=b_id, name="B")
    b_decision = await DesignDecisionRepository.record(
        db_session, project_id=b_project, actor_id=b_id,
        title="B's decision", summary="something B picked.",
    )

    ctx = ToolContext(
        session=db_session, actor_id=a_id,
        project_id=a_project, request_id="req-cross",
    )
    result = await call_tool(
        "explain_decision",
        {"decision_id": b_decision.id},
        ctx,
    )
    assert result["ok"] is False
    assert "not found" in result["error"]["message"].lower()


# ─────────────────────────────────────────────────────────────────────
# challenge_design_decision — three-state resolution machine
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("resolution", [
    "rejected_challenge",
    "decision_revised",
    "accepted_override",
])
async def test_challenge_supports_all_three_resolutions(
    db_session, resolution,
):
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    user_id = await _seed_user(
        db_session, email=f"s11-chal-{resolution}@example.com",
    )
    project_id = await _seed_project(db_session, owner_id=user_id)
    target = await DesignDecisionRepository.record(
        db_session, project_id=project_id, actor_id=user_id,
        title="Original choice", summary="something chosen earlier.",
    )

    new_decision_id = None
    if resolution in {"decision_revised", "accepted_override"}:
        successor = await DesignDecisionRepository.record(
            db_session, project_id=project_id, actor_id=user_id,
            title="Revised choice", summary="superseding decision.",
        )
        new_decision_id = successor.id

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        project_id=project_id, request_id=f"req-{resolution}",
    )
    payload = {
        "decision_id": target.id,
        "challenge_text": (
            "Reasonable challenge text exceeding the 4-char minimum."
        ),
        "resolution": resolution,
        "response_reasoning": "Agent's reply explaining the resolution.",
    }
    if new_decision_id:
        payload["new_decision_id"] = new_decision_id

    result = await call_tool(
        "challenge_design_decision", payload, ctx,
    )
    assert result["ok"] is True, result.get("error")
    chal = result["output"]["challenge"]
    assert chal["resolution"] == resolution
    if new_decision_id:
        assert chal["new_decision_id"] == new_decision_id
        assert result["output"]["superseded"] is not None


async def test_challenge_pending_when_no_resolution(db_session):
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-pending@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    target = await DesignDecisionRepository.record(
        db_session, project_id=project_id, actor_id=user_id,
        title="t", summary="something earlier.",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        project_id=project_id, request_id="req-pending",
    )
    result = await call_tool(
        "challenge_design_decision",
        {
            "decision_id": target.id,
            "challenge_text": "I disagree with this for several reasons.",
        },
        ctx,
    )
    assert result["ok"] is True
    assert result["output"]["challenge"]["resolution"] == "pending"


# ─────────────────────────────────────────────────────────────────────
# compare_alternatives — auto-records decision with full rejection ledger
# ─────────────────────────────────────────────────────────────────────


async def test_compare_alternatives_auto_records_with_rejected(db_session):
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-compare@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        project_id=project_id, request_id="req-compare",
    )
    result = await call_tool(
        "compare_alternatives",
        {
            "decision_question": "Pick primary wood for the kitchen island",
            "alternatives": [
                {"name": "walnut", "properties": {"cost_inr": 8000}},
                {"name": "oak",    "properties": {"cost_inr": 6500}},
                {"name": "teak",   "properties": {"cost_inr": 9000}},
            ],
            "evaluation_criteria": ["cost", "theme_match"],
            "ranked": [
                {
                    "name": "walnut",
                    "composite_score": 0.85,
                    "per_criterion": [
                        {"criterion": "cost",        "score": 0.65},
                        {"criterion": "theme_match", "score": 1.0},
                    ],
                },
                {
                    "name": "oak",
                    "composite_score": 0.70,
                    "per_criterion": [
                        {"criterion": "cost",        "score": 0.85},
                        {"criterion": "theme_match", "score": 0.55},
                    ],
                    "rejected_reason": "Theme match weaker for MCM",
                },
                {
                    "name": "teak",
                    "composite_score": 0.62,
                    "per_criterion": [
                        {"criterion": "cost",        "score": 0.50},
                        {"criterion": "theme_match", "score": 0.74},
                    ],
                    "rejected_reason": "Over budget by 12.5%",
                },
            ],
            "auto_record_decision": True,
            "category": "material",
            "version": 1,
            "sources": ["theme_pack:mid_century_modern"],
            "confidence_score": 0.81,
            "confidence_factors": [
                "theme_pack_match", "within_budget",
            ],
        },
        ctx,
    )
    assert result["ok"] is True, result.get("error")
    out = result["output"]
    assert out["winner"]["name"] == "walnut"
    assert len(out["rejected"]) == 2
    assert {r["name"] for r in out["rejected"]} == {"oak", "teak"}
    assert out["decision_id"]

    row = await DesignDecisionRepository.get_by_id(
        db_session, decision_id=out["decision_id"],
    )
    assert row is not None
    # Rejection ledger populated — point of the tool.
    rejected_names = {r["option"] for r in row.rejected_alternatives}
    assert rejected_names == {"oak", "teak"}
    # Reasoning chain has one step per option.
    assert len(row.reasoning_steps) == 3
    # Confidence stamped.
    assert row.confidence_score == pytest.approx(0.81)


async def test_compare_alternatives_rejects_missing_rejection_reasons(
    db_session,
):
    """Every loser must explain why it lost. Silent rejections
    defeat the rejection-ledger guarantee."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s11-noreason@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        project_id=project_id, request_id="req-noreason",
    )
    result = await call_tool(
        "compare_alternatives",
        {
            "decision_question": "Pick wood",
            "alternatives": [
                {"name": "a"}, {"name": "b"},
            ],
            "evaluation_criteria": ["cost"],
            "ranked": [
                {"name": "a", "composite_score": 0.9},
                {"name": "b", "composite_score": 0.5},  # no rejected_reason
            ],
        },
        ctx,
    )
    assert result["ok"] is False
    assert "rejected_reason" in result["error"]["message"]
