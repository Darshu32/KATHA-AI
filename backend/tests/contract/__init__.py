"""Contract tests — lock the OpenAPI surface.

Stage 13 freezes the v1 API: every breaking change has to either
update the snapshot file *and* the migration policy, or rev to v2.
See ``docs/api-versioning.md``.
"""
