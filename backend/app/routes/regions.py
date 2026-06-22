"""Region catalogue route — powers the frontend market selector."""

from fastapi import APIRouter

from app.services.regions import list_regions

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("")
async def list_regions_route() -> dict:
    """The 8 supported markets with currency + jurisdiction metadata.

    Static (no DB, no auth) — the frontend uses this to render the
    project region selector and to format costs in the right currency.
    """
    return {"regions": list_regions()}
