"""Vision analyzer — orchestrates upload → bytes → provider call.

The agent tools call into here. The analyzer:

1. Resolves :class:`UploadedAsset` rows (owner-guarded).
2. Reads the bytes from the storage backend.
3. Confirms the MIME type is on the allow-list.
4. Selects the prompt for the requested purpose.
5. Calls the configured provider with the assembled
   :class:`VisionRequest`.
6. Returns a :class:`VisionResult` plus a slim
   :class:`AnalyzedAsset` summary the tool layer can echo back.

Owner-guard semantics
---------------------
- Asset id supplied + owner mismatch → :class:`VisionAnalyzeError`
  with a generic "not found" message (we don't leak existence).
- Asset id supplied + status != ``ready`` → analyze error.
- Multiple asset ids (``mood_board`` etc.) — every id must belong
  to the owner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.orm import UploadedAsset
from app.repositories.uploads import UploadRepository
from app.storage import StorageError, get_storage_backend
from app.vision.base import (
    VisionError,
    VisionImage,
    VisionProvider,
    VisionRequest,
    VisionResult,
)
from app.vision.factory import get_vision_provider
from app.vision.prompts import SUPPORTED_PURPOSES, prompt_for_purpose

log = logging.getLogger(__name__)


class VisionAnalyzeError(RuntimeError):
    """Raised when the analyzer cannot complete a request.

    Wraps storage / vision / repo failures into one error type so
    the agent tool layer has a single thing to catch.
    """


@dataclass
class AnalyzedAsset:
    """Slim per-asset reference returned alongside the parsed result."""

    asset_id: str
    kind: str
    mime_type: str
    size_bytes: int
    label: str = ""


@dataclass
class AnalyzeOutcome:
    """What the analyzer returns to the tool layer."""

    purpose: str
    parsed: dict[str, Any]
    raw_text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    assets: list[AnalyzedAsset] = field(default_factory=list)


class VisionAnalyzer:
    """High-level orchestrator — owns the provider + uses the upload repo."""

    def __init__(self, provider: Optional[VisionProvider] = None) -> None:
        self._provider = provider or get_vision_provider()

    @property
    def provider(self) -> VisionProvider:
        return self._provider

    async def analyze_assets(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        asset_ids: list[str],
        purpose: str,
        focus: str = "",
        max_tokens: int = 1500,
        temperature: float = 0.2,
    ) -> AnalyzeOutcome:
        if not asset_ids:
            raise VisionAnalyzeError("No asset_ids supplied")
        if purpose not in SUPPORTED_PURPOSES:
            raise VisionAnalyzeError(
                f"Unknown purpose {purpose!r}. "
                f"Allowed: {SUPPORTED_PURPOSES}"
            )

        # 1. Owner-guarded fetch + status check.
        rows: list[UploadedAsset] = []
        for asset_id in asset_ids:
            row = await UploadRepository.get_for_owner(
                session, asset_id=asset_id, owner_id=owner_id,
            )
            if row is None:
                raise VisionAnalyzeError(
                    f"Upload {asset_id} not found for this user."
                )
            if row.status != "ready":
                raise VisionAnalyzeError(
                    f"Upload {asset_id} status is {row.status!r}, expected 'ready'."
                )
            rows.append(row)

        # 2. MIME allow-list (defence in depth — already enforced at upload).
        settings = get_settings()
        for r in rows:
            if r.mime_type.lower() not in settings.upload_allowed_mime:
                raise VisionAnalyzeError(
                    f"Upload {r.id} has disallowed MIME {r.mime_type!r}."
                )

        # 3. Pull bytes from storage. We use the backend the row was
        # written under — even if the global config has flipped to
        # something else, the bytes must come from where they live.
        backend = get_storage_backend()
        images: list[VisionImage] = []
        analyzed_refs: list[AnalyzedAsset] = []
        for idx, r in enumerate(rows):
            try:
                data = await backend.get_bytes(r.storage_key)
            except StorageError as exc:
                raise VisionAnalyzeError(
                    f"Storage read failed for {r.id}: {exc}"
                ) from exc
            label = r.original_filename or f"image_{idx + 1}"
            images.append(VisionImage(data=data, mime_type=r.mime_type, label=label))
            analyzed_refs.append(AnalyzedAsset(
                asset_id=r.id,
                kind=r.kind,
                mime_type=r.mime_type,
                size_bytes=int(r.size_bytes or 0),
                label=label,
            ))

        # 4. Pick the prompt + schema for this purpose.
        spec = prompt_for_purpose(purpose, focus=focus)

        request = VisionRequest(
            images=images,
            system_prompt=spec.system_prompt,
            user_message=spec.user_template,
            output_schema=spec.output_schema,
            purpose=purpose,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # 5. Call the provider.
        try:
            result: VisionResult = await self._provider.analyze(request)
        except VisionError as exc:
            raise VisionAnalyzeError(str(exc)) from exc

        # 6. Wrap into the high-level outcome the tool layer wants.
        return AnalyzeOutcome(
            purpose=purpose,
            parsed=dict(result.parsed),
            raw_text=result.raw_text,
            provider=result.provider_name,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            assets=analyzed_refs,
        )
