"""Stage 1 pricing services.

Public surface
--------------
- :func:`build_seed_rows` — deterministic translation of the legacy
  ``app.knowledge`` constants into row-dicts ready for bulk insert.
  Used by the Stage 1 seed migration AND by the unit tests so the
  same code path proves the data is correct.
- :func:`build_pricing_knowledge` — async, DB-backed; replaces the
  hardcoded ``cost_engine_service.build_cost_engine_knowledge``.
- :func:`record_snapshot` — captures the pricing dict that fed a
  cost-engine / estimate run for immutable replay.
- :func:`load_snapshot` — replays a previously captured snapshot.
"""

from app.services.pricing.knowledge_service import build_pricing_knowledge
from app.services.pricing.seed import build_seed_rows
from app.services.pricing.snapshot_service import (
    load_snapshot,
    record_snapshot,
)

__all__ = [
    "build_pricing_knowledge",
    "build_seed_rows",
    "load_snapshot",
    "record_snapshot",
]
