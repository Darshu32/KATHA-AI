"""High-level orchestration for architecture indexing and summaries."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.architecture_graph_service import (
    get_latest_snapshot,
    list_edges_for_snapshot,
    list_file_facts_for_snapshot,
    list_nodes_for_snapshot,
    replace_snapshot,
)
from app.services.architecture_ingestion import scan_repository


@dataclass(frozen=True)
class FeatureStep:
    title: str
    description: str
    file_path: str


FEATURE_FLOWS: dict[str, list[FeatureStep]] = {
    "initial_generation": [
        FeatureStep(
            title="Capture the prompt in the frontend",
            description="The new project page collects prompt, room type, and style before kicking off generation.",
            file_path="frontend/app/project/new/page.tsx",
        ),
        FeatureStep(
            title="Create the project shell",
            description="The projects route creates the project record before any design version exists.",
            file_path="backend/app/routes/projects.py",
        ),
        FeatureStep(
            title="Start generation through the API",
            description="The generation route validates ownership and forwards the prompt into the backend pipeline.",
            file_path="backend/app/routes/generation.py",
        ),
        FeatureStep(
            title="Orchestrate prompt to graph",
            description="The generation pipeline calls AI generation, persists the first version, and computes estimates.",
            file_path="backend/app/services/generation_pipeline.py",
        ),
        FeatureStep(
            title="Call the AI model",
            description="The AI orchestrator converts the prompt into the structured design graph contract.",
            file_path="backend/app/services/ai_orchestrator.py",
        ),
        FeatureStep(
            title="Persist the design version",
            description="The design graph service stores the version snapshot and updates project state.",
            file_path="backend/app/services/design_graph_service.py",
        ),
        FeatureStep(
            title="Compute the estimate",
            description="The estimation engine derives line items and totals from the design graph.",
            file_path="backend/app/services/estimation_engine.py",
        ),
        FeatureStep(
            title="Render the result",
            description="The project page loads the latest version, estimate, and interactive editing UI.",
            file_path="frontend/app/project/[id]/page.tsx",
        ),
    ],
    "local_edit": [
        FeatureStep(
            title="Select and edit an object",
            description="The project viewer sends an object-specific edit prompt from the object inspector flow.",
            file_path="frontend/app/project/[id]/page.tsx",
        ),
        FeatureStep(
            title="Handle the edit request",
            description="The generation route validates ownership and dispatches the single-object edit pipeline.",
            file_path="backend/app/routes/generation.py",
        ),
        FeatureStep(
            title="Load latest version and rewrite the object",
            description="The generation pipeline fetches the latest graph, edits the target object, persists a new version, and recalculates estimate impact.",
            file_path="backend/app/services/generation_pipeline.py",
        ),
        FeatureStep(
            title="Apply the prompt to the object",
            description="The AI orchestrator updates only the chosen object while preserving the object identity contract.",
            file_path="backend/app/services/ai_orchestrator.py",
        ),
    ],
    "theme_switch": [
        FeatureStep(
            title="Trigger a theme change",
            description="The project viewer sends the chosen style and preserve-layout flag.",
            file_path="frontend/app/project/[id]/page.tsx",
        ),
        FeatureStep(
            title="Route the theme request",
            description="The generation route validates access and forwards the request to the theme switch pipeline.",
            file_path="backend/app/routes/generation.py",
        ),
        FeatureStep(
            title="Regenerate style while preserving structure",
            description="The generation pipeline asks the AI orchestrator to transform the design graph, normalizes the output, and stores a new version.",
            file_path="backend/app/services/generation_pipeline.py",
        ),
        FeatureStep(
            title="Apply the style transformation",
            description="The AI orchestrator rewrites the design graph style, materials, and colors.",
            file_path="backend/app/services/ai_orchestrator.py",
        ),
    ],
    "estimation": [
        FeatureStep(
            title="Request the estimate",
            description="The project page loads the latest estimate or a version-specific estimate.",
            file_path="frontend/app/project/[id]/page.tsx",
        ),
        FeatureStep(
            title="Serve estimate endpoints",
            description="The estimates route loads the requested design version and computes the estimate on demand.",
            file_path="backend/app/routes/estimates.py",
        ),
        FeatureStep(
            title="Calculate costs from graph geometry",
            description="The estimation engine maps spaces, materials, and fixtures into line items and totals.",
            file_path="backend/app/services/estimation_engine.py",
        ),
    ],
}


async def index_architecture(db: AsyncSession) -> dict:
    parsed = scan_repository()
    latest = await get_latest_snapshot(db)
    if latest is not None:
        latest_file_facts = await list_file_facts_for_snapshot(db, latest.id)
        drift = _build_drift_report(parsed, latest_file_facts, latest.commit_hash)
        if not drift["has_drift"]:
            quality = _build_quality_report(parsed)
            return {
                "snapshot_id": latest.id,
                "repo_name": parsed.repo_name,
                "commit_hash": parsed.commit_hash,
                "stats": parsed.stats,
                "reindexed": False,
                "drift": drift,
                "quality": quality,
            }

    snapshot = await replace_snapshot(db, parsed)
    quality = _build_quality_report(parsed)
    drift = _build_drift_report(parsed, [], "")
    return {
        "snapshot_id": snapshot.id,
        "repo_name": parsed.repo_name,
        "commit_hash": parsed.commit_hash,
        "stats": parsed.stats,
        "reindexed": True,
        "drift": drift,
        "quality": quality,
    }


async def get_architecture_summary(
    db: AsyncSession,
    auto_index: bool = True,
) -> dict:
    snapshot = await get_latest_snapshot(db)
    if snapshot is None:
        if not auto_index:
            return {
                "status": "missing",
                "message": "Architecture snapshot has not been indexed yet.",
            }
        await index_architecture(db)
        snapshot = await get_latest_snapshot(db)

    if snapshot is None:
        return {
            "status": "error",
            "message": "Architecture snapshot could not be created.",
        }

    nodes = await list_nodes_for_snapshot(db, snapshot.id)
    file_facts = await list_file_facts_for_snapshot(db, snapshot.id)
    node_counter = Counter(node.node_type for node in nodes)
    current_scan = scan_repository()
    drift = _build_drift_report(current_scan, file_facts, snapshot.commit_hash)
    quality = _build_quality_report(current_scan)

    top_files = []
    for file_fact in file_facts[:12]:
        top_files.append(
            {
                "file_path": file_fact.file_path,
                "summary": file_fact.summary,
                "file_type": file_fact.metadata_.get("file_type", ""),
            }
        )

    system_modules = sorted(
        {
            file_fact.file_path.split("/", 1)[0]
            for file_fact in file_facts
            if "/" in file_fact.file_path
        }
    )

    return {
        "status": "ready",
        "snapshot": {
            "id": snapshot.id,
            "repo_name": snapshot.repo_name,
            "commit_hash": snapshot.commit_hash,
            "created_at": snapshot.created_at.isoformat(),
        },
        "freshness": {
            "status": "stale" if drift["has_drift"] else "synced",
            "current_commit_hash": current_scan.commit_hash,
            "indexed_commit_hash": snapshot.commit_hash,
        },
        "overview": {
            "modules": system_modules,
            "file_count": len(file_facts),
            "node_count": len(nodes),
            "top_node_types": dict(sorted(node_counter.items())),
        },
        "drift": drift,
        "quality": quality,
        "files": top_files,
    }


async def get_feature_flow(
    db: AsyncSession,
    feature_name: str,
) -> dict:
    snapshot = await _ensure_snapshot(db)
    normalized = _normalize_feature_name(feature_name)
    flow = FEATURE_FLOWS.get(normalized)
    if flow is None:
        return {
            "status": "not_found",
            "feature": normalized,
            "available_features": sorted(FEATURE_FLOWS.keys()),
        }

    file_facts = await list_file_facts_for_snapshot(db, snapshot.id)
    fact_map = {fact.file_path: fact for fact in file_facts}
    steps = []
    for index, step in enumerate(flow, start=1):
        fact = fact_map.get(step.file_path)
        steps.append(
            {
                "step": index,
                "title": step.title,
                "description": step.description,
                "file_path": step.file_path,
                "file_summary": fact.summary if fact else "",
            }
        )

    return {
        "status": "ready",
        "feature": normalized,
        "snapshot_id": snapshot.id,
        "steps": steps,
    }


async def get_dependency_analysis(
    db: AsyncSession,
    query: str,
) -> dict:
    snapshot = await _ensure_snapshot(db)
    nodes = await list_nodes_for_snapshot(db, snapshot.id)
    edges = await list_edges_for_snapshot(db, snapshot.id)

    matched_nodes = [
        node for node in nodes if _matches_query(node, query)
    ]
    if not matched_nodes:
        return {
            "status": "not_found",
            "query": query,
            "message": "No matching architecture node found.",
        }

    node_map = {node.id: node for node in nodes}
    focus = matched_nodes[0]
    incoming = []
    outgoing = []

    for edge in edges:
        if edge.from_node_id == focus.id:
            target = node_map.get(edge.to_node_id)
            if target is not None:
                outgoing.append(_serialize_related_node(edge.edge_type, target))
        if edge.to_node_id == focus.id:
            source = node_map.get(edge.from_node_id)
            if source is not None:
                incoming.append(_serialize_related_node(edge.edge_type, source))

    return {
        "status": "ready",
        "query": query,
        "focus": _serialize_node(focus),
        "incoming": outgoing_limit(_dedupe_relations(incoming)),
        "outgoing": outgoing_limit(_dedupe_relations(outgoing)),
    }


async def ask_architecture(
    db: AsyncSession,
    question: str,
) -> dict:
    _ = await _ensure_snapshot(db)
    lowered = question.lower()

    if "drift" in lowered or "stale" in lowered or "fresh" in lowered:
        summary = await get_architecture_summary(db)
        drift = summary["drift"]
        freshness = summary["freshness"]
        changed_files = drift.get("changed_files", [])
        return {
            "status": "ready",
            "question": question,
            "answer": (
                f"The architecture snapshot is currently {freshness['status']}. "
                f"{drift['changed_file_count']} file(s) differ from the indexed snapshot and "
                f"{drift['new_file_count']} new file(s) are waiting to be indexed."
            ),
            "citations": changed_files[:5],
            "mode": "freshness",
        }

    if "quality" in lowered or "coverage" in lowered:
        summary = await get_architecture_summary(db)
        quality = summary["quality"]
        return {
            "status": "ready",
            "question": question,
            "answer": (
                f"The current architecture coverage score is {quality['score']} out of 100. "
                f"There are {quality['issue_count']} issue(s) flagged across indexing freshness, feature coverage, and parsing."
            ),
            "citations": [issue["file_path"] for issue in quality["issues"] if issue.get("file_path")][:5],
            "mode": "quality",
        }

    for feature_name in FEATURE_FLOWS:
        if feature_name.replace("_", " ") in lowered or feature_name in lowered:
            flow = await get_feature_flow(db, feature_name)
            files = [step["file_path"] for step in flow.get("steps", [])]
            return {
                "status": "ready",
                "question": question,
                "answer": (
                    f"The strongest matching feature flow is '{feature_name}'. "
                    f"It spans {len(flow.get('steps', []))} step(s) from frontend entrypoints "
                    "through backend orchestration and persistence."
                ),
                "citations": files,
                "mode": "feature_flow",
            }

    dependency = await get_dependency_analysis(db, question)
    if dependency.get("status") == "ready":
        focus = dependency["focus"]
        return {
            "status": "ready",
            "question": question,
            "answer": (
                f"The closest architecture match is {focus['name']} ({focus['node_type']}). "
                f"It has {len(dependency['incoming'])} incoming and {len(dependency['outgoing'])} outgoing tracked dependencies."
            ),
            "citations": _collect_dependency_citations(dependency),
            "mode": "dependency",
        }

    summary = await get_architecture_summary(db, auto_index=False)
    return {
        "status": "ready",
        "question": question,
        "answer": (
            f"The repository currently contains {summary['overview']['file_count']} indexed files across "
            f"{', '.join(summary['overview']['modules'])}. "
            "Ask about a known feature like initial generation, local edit, theme switch, or estimation for a more grounded explanation."
        ),
        "citations": [file_info["file_path"] for file_info in summary["files"][:5]],
        "mode": "summary",
    }


async def _ensure_snapshot(db: AsyncSession):
    snapshot = await get_latest_snapshot(db)
    if snapshot is None:
        await index_architecture(db)
        snapshot = await get_latest_snapshot(db)
    if snapshot is None:
        raise RuntimeError("Architecture snapshot is unavailable")
    return snapshot


def _normalize_feature_name(feature_name: str) -> str:
    return feature_name.strip().lower().replace("-", "_").replace(" ", "_")


def _matches_query(node, query: str) -> bool:
    lowered = query.lower()
    return (
        lowered in node.name.lower()
        or lowered in node.file_path.lower()
        or lowered in node.symbol_path.lower()
    )


def _serialize_node(node) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "node_type": node.node_type,
        "file_path": node.file_path,
        "symbol_path": node.symbol_path,
    }


def _serialize_related_node(edge_type: str, node) -> dict:
    return {
        "edge_type": edge_type,
        **_serialize_node(node),
    }


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for relation in relations:
        key = (relation["edge_type"], relation["symbol_path"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(relation)
    return deduped


def outgoing_limit(relations: list[dict]) -> list[dict]:
    return relations[:20]


def _collect_dependency_citations(dependency: dict) -> list[str]:
    citations: list[str] = []
    focus = dependency.get("focus", {})
    if focus.get("file_path"):
        citations.append(focus["file_path"])
    for relation in dependency.get("incoming", [])[:3]:
        if relation.get("file_path"):
            citations.append(relation["file_path"])
    for relation in dependency.get("outgoing", [])[:3]:
        if relation.get("file_path"):
            citations.append(relation["file_path"])
    return list(dict.fromkeys(citations))


async def get_architecture_status(db: AsyncSession) -> dict:
    snapshot = await _ensure_snapshot(db)
    file_facts = await list_file_facts_for_snapshot(db, snapshot.id)
    current_scan = scan_repository()
    drift = _build_drift_report(current_scan, file_facts, snapshot.commit_hash)
    quality = _build_quality_report(current_scan)

    return {
        "status": "ready",
        "snapshot_id": snapshot.id,
        "repo_name": snapshot.repo_name,
        "indexed_commit_hash": snapshot.commit_hash,
        "current_commit_hash": current_scan.commit_hash,
        "freshness": "stale" if drift["has_drift"] else "synced",
        "drift": drift,
        "quality": quality,
    }


async def get_architecture_quality(db: AsyncSession) -> dict:
    snapshot = await _ensure_snapshot(db)
    file_facts = await list_file_facts_for_snapshot(db, snapshot.id)
    current_scan = scan_repository()
    drift = _build_drift_report(current_scan, file_facts, snapshot.commit_hash)
    quality = _build_quality_report(current_scan)

    return {
        "status": "ready",
        "snapshot_id": snapshot.id,
        "freshness": "stale" if drift["has_drift"] else "synced",
        **quality,
    }


async def refresh_architecture(
    db: AsyncSession,
    force: bool = False,
) -> dict:
    if force:
        parsed = scan_repository()
        snapshot = await replace_snapshot(db, parsed)
        quality = _build_quality_report(parsed)
        return {
            "status": "completed",
            "snapshot_id": snapshot.id,
            "repo_name": parsed.repo_name,
            "stats": parsed.stats,
            "quality": quality,
            "reindexed": True,
        }

    result = await index_architecture(db)
    return {
        "status": "completed",
        **result,
    }


def _build_drift_report(parsed, stored_file_facts, indexed_commit_hash: str) -> dict:
    stored_hashes = {
        fact.file_path: fact.metadata_.get("content_hash", "")
        for fact in stored_file_facts
    }
    current_hashes = {
        fact.file_path: fact.metadata.get("content_hash", "")
        for fact in parsed.file_facts
    }

    changed_files = sorted(
        file_path
        for file_path, current_hash in current_hashes.items()
        if file_path in stored_hashes and stored_hashes[file_path] != current_hash
    )
    new_files = sorted(
        file_path for file_path in current_hashes if file_path not in stored_hashes
    )
    deleted_files = sorted(
        file_path for file_path in stored_hashes if file_path not in current_hashes
    )
    commit_changed = bool(indexed_commit_hash and parsed.commit_hash and indexed_commit_hash != parsed.commit_hash)

    return {
        "has_drift": bool(changed_files or new_files or deleted_files or commit_changed),
        "commit_changed": commit_changed,
        "changed_file_count": len(changed_files),
        "new_file_count": len(new_files),
        "deleted_file_count": len(deleted_files),
        "changed_files": changed_files[:20],
        "new_files": new_files[:20],
        "deleted_files": deleted_files[:20],
    }


def _build_quality_report(parsed) -> dict:
    file_fact_map = {fact.file_path: fact for fact in parsed.file_facts}
    issues: list[dict] = []
    recommendations: list[str] = []
    score = 100

    parse_errors = [
        fact.file_path
        for fact in parsed.file_facts
        if fact.metadata.get("parse_error")
    ]
    for file_path in parse_errors:
        issues.append(
            {
                "type": "parse_error",
                "severity": "high",
                "message": "File could not be parsed during architecture indexing.",
                "file_path": file_path,
            }
        )
    score -= len(parse_errors) * 8

    for feature_name, steps in FEATURE_FLOWS.items():
        for step in steps:
            if step.file_path not in file_fact_map:
                issues.append(
                    {
                        "type": "missing_feature_file",
                        "severity": "high",
                        "message": f"Feature flow '{feature_name}' references a file that is not indexed.",
                        "file_path": step.file_path,
                    }
                )
                score -= 10

    node_types = parsed.stats.get("node_types", {})
    required_node_types = {
        "route_handler": "Route handlers should be discoverable.",
        "service": "Service layer coverage should exist for backend orchestration.",
        "page": "Frontend pages should be indexed.",
    }
    for node_type, message in required_node_types.items():
        if node_types.get(node_type, 0) == 0:
            issues.append(
                {
                    "type": "coverage_gap",
                    "severity": "medium",
                    "message": message,
                    "file_path": "",
                }
            )
            score -= 12

    summaries_without_detail = [
        fact.file_path
        for fact in parsed.file_facts
        if "defining" not in fact.summary and fact.metadata.get("language") != "markdown"
    ]
    if summaries_without_detail:
        recommendations.append(
            "Improve extraction depth for files that only received generic summaries."
        )
        score -= min(10, len(summaries_without_detail))

    unresolved_calls = parsed.stats.get("edge_types", {}).get("calls", 0)
    if unresolved_calls < 10:
        recommendations.append(
            "Expand symbol resolution so more runtime call edges can be traced precisely."
        )

    if not recommendations:
        recommendations.append("Architecture coverage is healthy; focus next on automatic background refresh triggers.")

    return {
        "score": max(score, 0),
        "issue_count": len(issues),
        "issues": issues[:20],
        "recommendations": recommendations[:5],
    }
