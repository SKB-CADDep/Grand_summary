from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.dependencies import get_app_state
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import health, materials, catalogs, sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = get_app_state()
    app.state.app_state = state
    yield


app = FastAPI(title="Material Library API", lifespan=lifespan, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(materials.router, prefix="/api")
app.include_router(catalogs.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
