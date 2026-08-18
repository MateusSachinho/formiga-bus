import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import config
from .routes import router
from .store import BusStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = BusStore()
    app.state.http_client = httpx.AsyncClient()
    poll_task = asyncio.create_task(app.state.store.poll_forever(app.state.http_client))
    yield
    poll_task.cancel()
    await app.state.http_client.aclose()


app = FastAPI(title="formiga-bus", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(router)
