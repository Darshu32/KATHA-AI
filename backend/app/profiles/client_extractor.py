"""Client-pattern extractor — recurring constraints across one client's projects.

Mines:

- **Typical budget band** — low / median / high across estimate
  totals for the client's projects.
- **Recurring room types** — counts how often each room type
  appears.
- **Recurring themes** — counts of design themes the client
  gravitates toward.
- **Accessibility flags** — surfaced from project metadata or
  decisions tagged ``accessibility``.
- **Constraints** — free-form recurring constraint phrases
  extracted from project descriptions.

Privacy
-------
Same gating as the architect extractor — the caller must confirm
the architect's ``learning_enabled`` flag before invoking. The
extractor itself runs the same way regardless of the flag's
value; the worker is the gatekeeper.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Optional


@dataclass
class ClientPattern:
    """Structured output of the per-client extractor."""

    client_id: str
    project_count: int = 0
    typical_budget_inr: dict[str, Any] = field(default_factory=dict)
    recurring_room_types: list[dict[str, Any]] = field(default_factory=list)
    recurring_themes: list[dict[str, Any]] = field(default_factory=list)
    accessibility_flags: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    last_project_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "project_count": self.project_count,
            "typical_budget_inr": dict(self.typical_budget_inr),
            "recurring_room_types": list(self.recurring_room_types),
            "recurring_themes": list(self.recurring_themes),
            "accessibility_flags": list(self.accessibility_flags),
            "constraints": list(self.constraints),
            "last_project_at": self.last_project_at,
        }


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _coerce_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _share(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    if total <= 0:
        return []
    return [
        {"name": name, "count": count, "share": round(count / total, 4)}
        for name, count in counter.most_common(20)
    ]


def _normalise(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


# ─────────────────────────────────────────────────────────────────────
# Public extractor
# ─────────────────────────────────────────────────────────────────────


def extract_client_pattern(
    *,
    client_id: str,
    projects: Iterable[dict[str, Any]],
    last_project_at: Optional[str] = None,
) -> ClientPattern:
    """Compute the client's recurring-constraint pattern.

    Parameters
    ----------
    client_id:
        The client id — copied verbatim onto the result.
    projects:
        Iterable of project dicts. Expected keys (all optional):

        - ``description``: str
        - ``estimate_total_inr``: float
        - ``room_type``: str (or under ``graph_data.room.type``)
        - ``theme``: str (or under ``graph_data.style.primary``)
        - ``accessibility_flags``: list[str]
        - ``decisions``: list of decision dicts with ``tags``
          containing ``"accessibility"``.

    Robust to partial / missing fields.
    """
    project_list = [p for p in (projects or []) if isinstance(p, dict)]
    if not project_list:
        return ClientPattern(client_id=client_id)

    budget_samples: list[float] = []
    room_counter: Counter[str] = Counter()
    theme_counter: Counter[str] = Counter()
    access_set: set[str] = set()
    constraint_counter: Counter[str] = Counter()

    for project in project_list:
        # Budget.
        budget = _coerce_float(project.get("estimate_total_inr"))
        if budget is None:
            estimate = project.get("estimate") or {}
            if isinstance(estimate, dict):
                budget = _coerce_float(estimate.get("total"))
        if budget is not None and budget > 0:
            budget_samples.append(budget)

        # Room type.
        room_type = _normalise(project.get("room_type"))
        if not room_type:
            graph = project.get("graph_data") or {}
            if isinstance(graph, dict):
                room = graph.get("room") or {}
                room_type = _normalise(room.get("type")) if isinstance(room, dict) else None
        if room_type:
            room_counter[room_type] += 1

        # Theme.
        theme = _normalise(project.get("theme"))
        if not theme:
            graph = project.get("graph_data") or {}
            if isinstance(graph, dict):
                style = graph.get("style") or {}
                if isinstance(style, dict):
                    theme = _normalise(style.get("primary"))
        if theme:
            theme_counter[theme] += 1

        # Accessibility flags — direct or via decisions.
        for flag in project.get("accessibility_flags") or []:
            n = _normalise(flag)
            if n:
                access_set.add(n)
        for decision in project.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            tags = decision.get("tags") or []
            if isinstance(tags, list) and any(
                _normalise(t) == "accessibility" for t in tags
            ):
                access_set.add("derived_from_decision")

        # Free-form constraints — pull short phrases off the
        # description. Counter dedups; we surface phrases that
        # recur across projects.
        desc = project.get("description") or ""
        for phrase in str(desc).split(";"):
            phrase = phrase.strip().lower()
            if 4 <= len(phrase) <= 80:
                constraint_counter[phrase] += 1

    # Budget summary.
    typical_budget: dict[str, Any] = {}
    if budget_samples:
        typical_budget = {
            "low": round(min(budget_samples), 2),
            "high": round(max(budget_samples), 2),
            "median": round(median(budget_samples), 2),
            "samples": len(budget_samples),
        }

    # Constraints — only keep phrases that recur (count >= 2) so
    # one-off project descriptions don't leak as "patterns".
    recurring_constraints = [
        phrase for phrase, count in constraint_counter.most_common(20)
        if count >= 2
    ]

    return ClientPattern(
        client_id=client_id,
        project_count=len(project_list),
        typical_budget_inr=typical_budget,
        recurring_room_types=_share(room_counter, sum(room_counter.values())),
        recurring_themes=_share(theme_counter, sum(theme_counter.values())),
        accessibility_flags=sorted(access_set),
        constraints=recurring_constraints,
        last_project_at=last_project_at,
    )
