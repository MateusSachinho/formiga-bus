from typing import Annotated

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/v1")


@router.get("/buses")
async def get_buses(request: Request, linha: Annotated[str | None, Query(max_length=16)] = None):
    return request.app.state.store.get_buses_geojson(linha)


@router.get("/health")
async def health(request: Request):
    return request.app.state.store.health()
