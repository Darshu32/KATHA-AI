"""Repo scanning and lightweight architecture extraction."""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
INCLUDED_ROOTS = ("frontend", "backend", "packages", "docs")
ALLOWED_SUFFIXES = {".py", ".ts", ".tsx", ".md"}
IGNORED_PARTS = {".git", ".next", "node_modules", "__pycache__", ".venv", "dist", "build"}


@dataclass
class ParsedNode:
    node_type: str
    name: str
    file_path: str
    symbol_path: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedEdge:
    from_symbol_path: str
    to_symbol_path: str
    edge_type: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedFileFact:
    file_path: str
    summary: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedArchitectureSnapshot:
    repo_name: str
    commit_hash: str
    nodes: list[ParsedNode]
    edges: list[ParsedEdge]
    file_facts: list[ParsedFileFact]
    stats: dict


def scan_repository() -> ParsedArchitectureSnapshot:
    nodes: list[ParsedNode] = []
    edges: list[ParsedEdge] = []
    file_facts: list[ParsedFileFact] = []
    files: list[Path] = []

    for root_name in INCLUDED_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if any(part in IGNORED_PARTS for part in path.parts):
                continue
            files.append(path)

    for path in files:
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8", errors="ignore")
        file_node_type = _classify_file(rel_path)
        file_symbol = f"file:{rel_path}"
        nodes.append(
            ParsedNode(
                node_type="file",
                name=path.name,
                file_path=rel_path,
                symbol_path=file_symbol,
                metadata={
                    "file_type": file_node_type,
                    "content_hash": _content_hash(source),
                },
            )
        )

        local_nodes, local_edges, summary_metadata = _parse_file(path, rel_path, source)
        nodes.extend(local_nodes)
        edges.extend(local_edges)
        file_facts.append(
            ParsedFileFact(
                file_path=rel_path,
                summary=_build_file_summary(rel_path, file_node_type, local_nodes, summary_metadata),
                metadata={
                    **summary_metadata,
                    "file_type": file_node_type,
                    "content_hash": _content_hash(source),
                },
            )
        )

    stats = _build_stats(nodes, edges, files)
    return ParsedArchitectureSnapshot(
        repo_name=REPO_ROOT.name.lower(),
        commit_hash=_read_git_commit_hash(),
        nodes=nodes,
        edges=edges,
        file_facts=file_facts,
        stats=stats,
    )


def _parse_file(path: Path, rel_path: str, source: str) -> tuple[list[ParsedNode], list[ParsedEdge], dict]:
    if path.suffix == ".py":
        return _parse_python_file(rel_path, source)
    if path.suffix in {".ts", ".tsx"}:
        return _parse_typescript_file(rel_path, source)
    return _parse_markdown_file(rel_path, source)


def _parse_python_file(rel_path: str, source: str) -> tuple[list[ParsedNode], list[ParsedEdge], dict]:
    nodes: list[ParsedNode] = []
    edges: list[ParsedEdge] = []
    imports: list[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return nodes, edges, {"language": "python", "parse_error": True}

    file_symbol = f"file:{rel_path}"

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            imports.append(module_name)

    for imported in imports:
        edges.append(
            ParsedEdge(
                from_symbol_path=file_symbol,
                to_symbol_path=f"module:{imported}",
                edge_type="imports",
            )
        )

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_type = _classify_python_class(node, rel_path)
            symbol_path = f"{file_symbol}::{node.name}"
            nodes.append(
                ParsedNode(
                    node_type=class_type,
                    name=node.name,
                    file_path=rel_path,
                    symbol_path=symbol_path,
                )
            )
            edges.append(
                ParsedEdge(
                    from_symbol_path=file_symbol,
                    to_symbol_path=symbol_path,
                    edge_type="defines",
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_type = _classify_python_function(node, rel_path)
            symbol_path = f"{file_symbol}::{node.name}"
            nodes.append(
                ParsedNode(
                    node_type=function_type,
                    name=node.name,
                    file_path=rel_path,
                    symbol_path=symbol_path,
                    metadata={"async": isinstance(node, ast.AsyncFunctionDef)},
                )
            )
            edges.append(
                ParsedEdge(
                    from_symbol_path=file_symbol,
                    to_symbol_path=symbol_path,
                    edge_type="defines",
                )
            )
            for call_name in _collect_python_calls(node):
                edges.append(
                    ParsedEdge(
                        from_symbol_path=symbol_path,
                        to_symbol_path=f"symbol:{call_name}",
                        edge_type="calls",
                    )
                )

    return nodes, edges, {"language": "python", "imports": imports[:20]}


def _parse_typescript_file(rel_path: str, source: str) -> tuple[list[ParsedNode], list[ParsedEdge], dict]:
    nodes: list[ParsedNode] = []
    edges: list[ParsedEdge] = []
    file_symbol = f"file:{rel_path}"

    imports = re.findall(r'^\s*import\s+.*?from\s+["\']([^"\']+)["\']', source, re.MULTILINE)
    exports = re.findall(
        r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|interface|type)\s+([A-Za-z0-9_]+)",
        source,
    )

    for imported in imports:
        edges.append(
            ParsedEdge(
                from_symbol_path=file_symbol,
                to_symbol_path=f"module:{imported}",
                edge_type="imports",
            )
        )

    node_type = _classify_file(rel_path)
    for export_name in exports:
        symbol_path = f"{file_symbol}::{export_name}"
        nodes.append(
            ParsedNode(
                node_type=node_type if node_type != "file" else "symbol",
                name=export_name,
                file_path=rel_path,
                symbol_path=symbol_path,
            )
        )
        edges.append(
            ParsedEdge(
                from_symbol_path=file_symbol,
                to_symbol_path=symbol_path,
                edge_type="defines",
            )
        )

    return nodes, edges, {"language": "typescript", "imports": imports[:20], "exports": exports[:20]}


def _parse_markdown_file(rel_path: str, source: str) -> tuple[list[ParsedNode], list[ParsedEdge], dict]:
    heading_matches = re.findall(r"^#{1,3}\s+(.+)$", source, re.MULTILINE)
    nodes = [
        ParsedNode(
            node_type="document_section",
            name=heading.strip(),
            file_path=rel_path,
            symbol_path=f"file:{rel_path}::{heading.strip()}",
        )
        for heading in heading_matches[:20]
    ]
    edges = [
        ParsedEdge(
            from_symbol_path=f"file:{rel_path}",
            to_symbol_path=node.symbol_path,
            edge_type="defines",
        )
        for node in nodes
    ]
    return nodes, edges, {"language": "markdown", "headings": heading_matches[:20]}


def _classify_python_class(node: ast.ClassDef, rel_path: str) -> str:
    if "models" in rel_path:
        return "orm_model"
    if "schemas" in rel_path:
        return "schema"
    return "class"


def _classify_python_function(node: ast.FunctionDef | ast.AsyncFunctionDef, rel_path: str) -> str:
    if "routes/" in rel_path:
        return "route_handler"
    if "services/" in rel_path:
        return "service"
    return "function"


def _collect_python_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    calls: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            if isinstance(inner.func, ast.Name):
                calls.add(inner.func.id)
            elif isinstance(inner.func, ast.Attribute):
                calls.add(inner.func.attr)
    return sorted(calls)


def _classify_file(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("backend/app/routes/"):
        return "route"
    if normalized.startswith("backend/app/services/"):
        return "service"
    if normalized.startswith("backend/app/models/"):
        return "model"
    if normalized.startswith("frontend/app/"):
        return "page"
    if normalized.startswith("frontend/components/"):
        return "component"
    if normalized.startswith("frontend/lib/store"):
        return "store"
    if normalized.startswith("frontend/lib/api-client"):
        return "api_client"
    if normalized.startswith("packages/"):
        return "shared_package"
    if normalized.startswith("docs/"):
        return "document"
    return "file"


def _build_file_summary(rel_path: str, file_type: str, nodes: list[ParsedNode], metadata: dict) -> str:
    important = [node.name for node in nodes[:4]]
    summary = f"{rel_path} is a {file_type} file"
    if important:
        summary += f" defining {', '.join(important)}"
    if metadata.get("imports"):
        summary += f"; imports {len(metadata['imports'])} module(s)"
    return summary + "."


def _build_stats(nodes: list[ParsedNode], edges: list[ParsedEdge], files: list[Path]) -> dict:
    node_counter = Counter(node.node_type for node in nodes)
    edge_counter = Counter(edge.edge_type for edge in edges)
    return {
        "file_count": len(files),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_types": dict(sorted(node_counter.items())),
        "edge_types": dict(sorted(edge_counter.items())),
        "roots": list(INCLUDED_ROOTS),
    }


def _content_hash(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()


def _read_git_commit_hash() -> str:
    git_head = REPO_ROOT / ".git" / "HEAD"
    if not git_head.exists():
        return ""

    head_value = git_head.read_text(encoding="utf-8", errors="ignore").strip()
    if not head_value.startswith("ref: "):
        return head_value

    ref_path = REPO_ROOT / ".git" / head_value.removeprefix("ref: ").strip()
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8", errors="ignore").strip()
    return ""
