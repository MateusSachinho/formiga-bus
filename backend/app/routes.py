import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1")


@router.get("/buses")
async def get_buses(request: Request, linha: str | None = None):
    return request.app.state.store.get_buses_geojson(linha)


@router.get("/lines")
async def get_lines(request: Request):
    return request.app.state.store.get_lines()


@router.get("/bus/{ordem}/track")
async def get_track(request: Request, ordem: str, minutes: int = 30):
    try:
        return await request.app.state.store.get_track(request.app.state.http_client, ordem, minutes)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"falha ao consultar API de origem: {e}")


@router.get("/health")
async def health(request: Request):
    return request.app.state.store.health()
