from fastapi import APIRouter

from ..gzh_adapter import THEMES
from ..prompts import XHS_LAYOUTS, XHS_VISUAL_DIRECTIONS


router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/themes")
async def themes() -> dict[str, list[str]]:
    return {
        "themes": list(THEMES),
        "xhs_styles": list(XHS_VISUAL_DIRECTIONS),
        "xhs_layouts": list(XHS_LAYOUTS),
    }
