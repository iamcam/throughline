from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import get_settings
from src.api.routers import health

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup - run-once code goes here
    yield
    # shutdown - cleanup here

app = FastAPI(
    title="Podcast Knowledge Engine",
    version="0.1.0",
    lifespan = lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(health.router, prefix="/api/v1")