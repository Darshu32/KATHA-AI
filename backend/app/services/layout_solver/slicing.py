"""Slicing tree — the geometry-valid-by-construction core of the solver.

A slicing tree is a binary tree. Each internal node carries a cut orientation
and splits its rectangle into two; each leaf is a room. Placing a tree into a
boundary rectangle, splitting each node's extent in proportion to the total
target area beneath each child, yields rectangles that:

  * never overlap,
  * exactly tile the boundary, and
  * give every room *exactly* its target area (when boundary area = total area).

That is the whole point: **area is exact by construction**, so the search
(``solver.py``) is free to spend all its effort on proportion and adjacency —
it can never produce overlapping or area-wrong rooms, because the representation
cannot express them. (Slicing trees cannot express the rare non-slicible plan,
e.g. the 5-room pinwheel; that is the accepted trade for guaranteed validity.)
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# A placed rectangle: (x, z, length, width) — min corner + extents, metres.
Rect = tuple[float, float, float, float]

VERTICAL = "V"     # cut splits the x extent (length) → left | right
HORIZONTAL = "H"   # cut splits the z extent (depth)  → near / far


@dataclass
class Node:
    """A slicing-tree node. Leaf iff ``room_id is not None``."""

    room_id: str | None = None
    orient: str | None = None
    left: "Node | None" = None
    right: "Node | None" = None

    @property
    def is_leaf(self) -> bool:
        return self.room_id is not None


def clone(node: Node) -> Node:
    """Deep copy — the search mutates candidates, never the incumbent."""
    if node.is_leaf:
        return Node(room_id=node.room_id)
    return Node(orient=node.orient, left=clone(node.left), right=clone(node.right))  # type: ignore[arg-type]


def leaves(node: Node) -> list[Node]:
    if node.is_leaf:
        return [node]
    return leaves(node.left) + leaves(node.right)  # type: ignore[arg-type]


def internals(node: Node) -> list[Node]:
    if node.is_leaf:
        return []
    return [node] + internals(node.left) + internals(node.right)  # type: ignore[arg-type]


def subtree_area(node: Node, areas: dict[str, float]) -> float:
    """Total target area of every room beneath ``node``."""
    if node.is_leaf:
        return areas.get(node.room_id, 0.0)  # type: ignore[arg-type]
    return subtree_area(node.left, areas) + subtree_area(node.right, areas)  # type: ignore[arg-type]


def place(node: Node, rect: Rect, areas: dict[str, float]) -> dict[str, Rect]:
    """Project a tree onto ``rect``; return ``room_id → placed rectangle``."""
    out: dict[str, Rect] = {}
    _place(node, rect, areas, out)
    return out


def _place(node: Node, rect: Rect, areas: dict[str, float], out: dict[str, Rect]) -> None:
    x, z, length, width = rect
    if node.is_leaf:
        out[node.room_id] = rect  # type: ignore[index]
        return
    a_left = subtree_area(node.left, areas)   # type: ignore[arg-type]
    a_right = subtree_area(node.right, areas)  # type: ignore[arg-type]
    total = a_left + a_right
    frac = 0.5 if total <= 0 else a_left / total
    if node.orient == VERTICAL:
        cut = length * frac
        _place(node.left, (x, z, cut, width), areas, out)             # type: ignore[arg-type]
        _place(node.right, (x + cut, z, length - cut, width), areas, out)  # type: ignore[arg-type]
    else:  # HORIZONTAL
        cut = width * frac
        _place(node.left, (x, z, length, cut), areas, out)            # type: ignore[arg-type]
        _place(node.right, (x, z + cut, length, width - cut), areas, out)  # type: ignore[arg-type]


def adjacent(a: Rect, b: Rect, *, eps: float = 1e-6, min_share: float = 0.3) -> bool:
    """True when two rectangles share a wall *segment* (not merely a corner).

    ``min_share`` (metres) is the smallest shared edge that counts as an
    adjacency — kept loose so dense plans stay well-connected. Whether a shared
    wall is wide enough to actually hang a door is a separate, stricter test
    (``wall_model._MIN_DOOR_SEG``); a satisfied-but-narrow adjacency simply gets
    no door, which the egress advisory then surfaces.
    """
    ax, az, al, aw = a
    bx, bz, bl, bw = b

    # Shared vertical edge: A's right face meets B's left face (or vice versa),
    # with overlapping z-spans.
    touch_x = abs((ax + al) - bx) < eps or abs((bx + bl) - ax) < eps
    if touch_x:
        overlap_z = min(az + aw, bz + bw) - max(az, bz)
        if overlap_z > min_share:
            return True

    # Shared horizontal edge.
    touch_z = abs((az + aw) - bz) < eps or abs((bz + bw) - az) < eps
    if touch_z:
        overlap_x = min(ax + al, bx + bl) - max(ax, bx)
        if overlap_x > min_share:
            return True

    return False


def random_tree(room_ids: list[str], rng: random.Random) -> Node:
    """A random slicing tree over ``room_ids`` — the search's starting point."""
    if len(room_ids) == 1:
        return Node(room_id=room_ids[0])
    ids = list(room_ids)
    rng.shuffle(ids)
    cut = rng.randint(1, len(ids) - 1)
    return Node(
        orient=rng.choice((VERTICAL, HORIZONTAL)),
        left=random_tree(ids[:cut], rng),
        right=random_tree(ids[cut:], rng),
    )
