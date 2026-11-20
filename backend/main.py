from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.routers import health, objects, updates, workbooks
from src.app_info import APP_VERSION
from src.paths import frontend_dist


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Grand Summary API", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(objects.router, prefix="/api")
app.include_router(updates.router, prefix="/api")
app.include_router(workbooks.router, prefix="/api")

DIST = frontend_dist()
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")


def run() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
