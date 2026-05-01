"""Backup helpers for the Stage 13 ops surface.

The actual backup orchestration lives in ``backend/scripts/backup.sh``
— bash is the right tool for pg_dump / tar plumbing. This Python
package holds the glue:

- :mod:`s3_sync` — push a list of files to the S3-compatible
  bucket configured in ``Settings``. Soft-fails when credentials
  are missing.
"""

from __future__ import annotations

__all__: list[str] = []
