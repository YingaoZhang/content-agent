from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
