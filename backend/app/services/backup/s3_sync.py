"""Push backup artefacts to an S3-compatible bucket.

Designed to be called either:

- From ``backup.sh`` as ``python3 -m app.services.backup.s3_sync FILE...``
- From a Celery beat job that wraps the bash script

Settings consumed (Stage 7 Cloudflare R2 / S3-compat block):

- ``s3_endpoint``, ``s3_access_key``, ``s3_secret_key``, ``s3_bucket``

If any of those are unset the function logs a warning and exits
with status 0 — backups must not fail because remote storage is
unconfigured. Local artefacts on disk are still authoritative.

Object keys are namespaced ``backups/<timestamp>/<filename>`` so
weekly pruning (``aws s3 rm s3://bucket/backups/202604`` etc.) is
trivial.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from app.config import get_settings


logger = logging.getLogger(__name__)


def _settings_ok(settings) -> bool:
    return all([
        settings.s3_endpoint,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_bucket,
    ])


def _extract_timestamp(name: str) -> str:
    """Pull the ``20260501T103045Z`` portion out of a backup filename."""
    parts = name.replace(".tar.gz", "").replace(".dump.gz", "").replace(
        ".json", ""
    ).split("_")
    for part in reversed(parts):
        # rough format check — 8 digits, T, 6 digits, Z
        if len(part) >= 16 and part.endswith("Z") and "T" in part:
            return part
    return "unknown"


def upload_files(
    paths: Iterable[str | os.PathLike],
    *,
    bucket_override: Optional[str] = None,
) -> int:
    """Upload one or more local files to the configured S3 bucket.

    Returns the number of files successfully uploaded. Logs but
    does not raise on individual upload failures — partial success
    is better than zero.
    """
    settings = get_settings()
    if not _settings_ok(settings):
        logger.warning(
            "s3_sync.skipped reason=settings_missing "
            "s3_endpoint/key/bucket must all be set"
        )
        return 0

    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "s3_sync.skipped reason=boto3_not_installed "
            "pip install boto3 to enable"
        )
        return 0

    bucket = bucket_override or settings.s3_bucket
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )

    uploaded = 0
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            logger.warning("s3_sync.skipped path=%s reason=not_a_file", path)
            continue
        ts = _extract_timestamp(path.name)
        key = f"backups/{ts}/{path.name}"
        try:
            client.upload_file(str(path), bucket, key)
            uploaded += 1
            logger.info(
                "s3_sync.ok bucket=%s key=%s bytes=%d",
                bucket, key, path.stat().st_size,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "s3_sync.failed bucket=%s key=%s err=%s",
                bucket, key, exc,
            )
    return uploaded


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.services.backup.s3_sync FILE...",
              file=sys.stderr)
        return 64
    n = upload_files(argv)
    print(f"s3_sync uploaded {n}/{len(argv)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
