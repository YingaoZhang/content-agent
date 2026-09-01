from fastapi import APIRouter


router = APIRouter()


def _runtime():
    # Resolve at request time so app.api remains a small compatibility seam for integrations.
    from .. import api

    return api


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/themes")
async def themes() -> dict[str, list[str]]:
    return {"themes": list(_runtime().THEMES)}
