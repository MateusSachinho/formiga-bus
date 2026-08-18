from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1")


@router.get("/buses")
async def get_buses(request: Request, linha: str | None = None):
    return request.app.state.store.get_buses_geojson(linha)


@router.get("/health")
async def health(request: Request):
    return request.app.state.store.health()
