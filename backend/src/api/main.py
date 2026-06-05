# src/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import get_settings
from src.api.routers import health, feeds, episodes, speakers, query

from src.ingestion.queue import BackgroundTaskQueue
from src.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.ingestion_queue = BackgroundTaskQueue(
        max_concurrent=getattr(settings, "max_concurrent_ingestions", 2)
    )
    yield

app = FastAPI(
    title="Podcast Knowledge Engine",
    version="0.1.4",
    lifespan = lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(feeds.router, prefix="/api/v1")
app.include_router(episodes.router, prefix="/api/v1")
app.include_router(speakers.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")
