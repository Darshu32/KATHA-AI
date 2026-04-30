"""Admin routes — DB-backed updates to versioned business data.

- Stage 1 ships pricing admin under ``/admin/pricing``.
- Stage 3A adds themes admin under ``/admin/themes``.
- Stage 3B adds building-standards admin under ``/admin/standards``
  (covers Stages 3B, 3C, 3D, 3E since all use the same table).
- Stage 3F adds chat suggestions admin under ``/admin/suggestions``.

All admin endpoints:
  - require an authenticated user (current_user dep)
  - emit AuditEvent rows automatically (via repository helpers)
  - return the new version row including ``id``, ``version``, ``source``
"""

from app.routes.admin.pricing import router as pricing_admin_router
from app.routes.admin.standards import router as standards_admin_router
from app.routes.admin.suggestions import router as suggestions_admin_router
from app.routes.admin.themes import router as themes_admin_router

__all__ = [
    "pricing_admin_router",
    "standards_admin_router",
    "suggestions_admin_router",
    "themes_admin_router",
]
