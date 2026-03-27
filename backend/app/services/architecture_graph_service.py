"""Persistence helpers for architecture snapshots."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.architecture import (
    ArchitectureEdge,
    ArchitectureFileFact,
    ArchitectureNode,
    ArchitectureSnapshot,
)
from app.services.architecture_ingestion import ParsedArchitectureSnapshot


async def replace_snapshot(
    db: AsyncSession,
    parsed: ParsedArchitectureSnapshot,
) -> ArchitectureSnapshot:
    existing = await get_latest_snapshot(db)
    if existing is not None:
        await db.execute(
            delete(ArchitectureEdge).where(ArchitectureEdge.snapshot_id == existing.id)
        )
        await db.execute(
            delete(ArchitectureFileFact).where(ArchitectureFileFact.snapshot_id == existing.id)
        )
        await db.execute(
            delete(ArchitectureNode).where(ArchitectureNode.snapshot_id == existing.id)
        )
        await db.execute(
            delete(ArchitectureSnapshot).where(ArchitectureSnapshot.id == existing.id)
        )
        await db.flush()

    snapshot = ArchitectureSnapshot(
        repo_name=parsed.repo_name,
        commit_hash=parsed.commit_hash,
        status="ready",
    )
    db.add(snapshot)
    await db.flush()

    symbol_to_node_id: dict[str, str] = {}

    for parsed_node in parsed.nodes:
        node = await _ensure_node(
            db=db,
            snapshot_id=snapshot.id,
            symbol_to_node_id=symbol_to_node_id,
            symbol_path=parsed_node.symbol_path,
            node_type=parsed_node.node_type,
            name=parsed_node.name,
            file_path=parsed_node.file_path,
            metadata=parsed_node.metadata,
        )
        symbol_to_node_id[parsed_node.symbol_path] = node.id

    for parsed_edge in parsed.edges:
        from_node = await _ensure_reference_node(
            db=db,
            snapshot_id=snapshot.id,
            symbol_to_node_id=symbol_to_node_id,
            symbol_path=parsed_edge.from_symbol_path,
        )
        to_node = await _ensure_reference_node(
            db=db,
            snapshot_id=snapshot.id,
            symbol_to_node_id=symbol_to_node_id,
            symbol_path=parsed_edge.to_symbol_path,
        )
        db.add(
            ArchitectureEdge(
                snapshot_id=snapshot.id,
                from_node_id=from_node.id,
                to_node_id=to_node.id,
                edge_type=parsed_edge.edge_type,
                metadata_=parsed_edge.metadata,
            )
        )

    for file_fact in parsed.file_facts:
        db.add(
            ArchitectureFileFact(
                snapshot_id=snapshot.id,
                file_path=file_fact.file_path,
                summary=file_fact.summary,
                metadata_=file_fact.metadata,
            )
        )

    await db.flush()
    return snapshot


async def get_latest_snapshot(db: AsyncSession) -> ArchitectureSnapshot | None:
    result = await db.execute(
        select(ArchitectureSnapshot)
        .order_by(ArchitectureSnapshot.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_nodes_for_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> list[ArchitectureNode]:
    result = await db.execute(
        select(ArchitectureNode).where(ArchitectureNode.snapshot_id == snapshot_id)
    )
    return list(result.scalars().all())


async def list_edges_for_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> list[ArchitectureEdge]:
    result = await db.execute(
        select(ArchitectureEdge).where(ArchitectureEdge.snapshot_id == snapshot_id)
    )
    return list(result.scalars().all())


async def _ensure_reference_node(
    db: AsyncSession,
    snapshot_id: str,
    symbol_to_node_id: dict[str, str],
    symbol_path: str,
) -> ArchitectureNode:
    if symbol_path in symbol_to_node_id:
        result = await db.execute(
            select(ArchitectureNode).where(ArchitectureNode.id == symbol_to_node_id[symbol_path])
        )
        existing = result.scalar_one()
        return existing

    node_type, name = _derive_reference_node(symbol_path)
    node = await _ensure_node(
        db=db,
        snapshot_id=snapshot_id,
        symbol_to_node_id=symbol_to_node_id,
        symbol_path=symbol_path,
        node_type=node_type,
        name=name,
        file_path="",
        metadata={"generated": True},
    )
    symbol_to_node_id[symbol_path] = node.id
    return node


async def _ensure_node(
    db: AsyncSession,
    snapshot_id: str,
    symbol_to_node_id: dict[str, str],
    symbol_path: str,
    node_type: str,
    name: str,
    file_path: str,
    metadata: dict,
) -> ArchitectureNode:
    existing_id = symbol_to_node_id.get(symbol_path)
    if existing_id is not None:
        result = await db.execute(select(ArchitectureNode).where(ArchitectureNode.id == existing_id))
        return result.scalar_one()

    node = ArchitectureNode(
        snapshot_id=snapshot_id,
        node_type=node_type,
        name=name,
        file_path=file_path,
        symbol_path=symbol_path,
        metadata_=metadata,
    )
    db.add(node)
    await db.flush()
    symbol_to_node_id[symbol_path] = node.id
    return node


def _derive_reference_node(symbol_path: str) -> tuple[str, str]:
    if symbol_path.startswith("module:"):
        return "module_ref", symbol_path.removeprefix("module:")
    if symbol_path.startswith("symbol:"):
        return "symbol_ref", symbol_path.removeprefix("symbol:")
    if symbol_path.startswith("file:"):
        return "file", symbol_path.removeprefix("file:")
    return "reference", symbol_path


async def list_file_facts_for_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> list[ArchitectureFileFact]:
    result = await db.execute(
        select(ArchitectureFileFact)
        .where(ArchitectureFileFact.snapshot_id == snapshot_id)
        .order_by(ArchitectureFileFact.file_path.asc())
    )
    return list(result.scalars().all())
