"""Stage 3A themes services.

Public surface
--------------
- :func:`build_seed_rows`       — deterministic translator from
  ``app.knowledge.themes.THEMES`` into row-dicts ready for bulk insert.
  Used by the Stage 3A seed migration AND by tests.
- :func:`get_theme`              — async, DB-backed theme lookup (alias-aware).
  Replacement for ``app.knowledge.themes.get`` in agent / cost-engine paths.
- :func:`describe_theme_for_prompt` — DB-backed prompt renderer (replacement
  for the legacy sync ``describe_for_prompt``).
"""

from app.services.themes.knowledge_service import (
    describe_theme_for_prompt,
    get_theme,
    list_published_themes,
)
from app.services.themes.seed import build_theme_seed_rows

__all__ = [
    "build_theme_seed_rows",
    "describe_theme_for_prompt",
    "get_theme",
    "list_published_themes",
]
