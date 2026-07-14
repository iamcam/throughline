# src/api/main.py
from contextlib import asynccontextmanager, AsyncExitStack
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import get_settings
from src.api.middleware.auth import BasicAuthMiddleware
from src.api.routers import health, feeds, episodes, speakers, chat
from src.query.session_store import InMemorySessionStore
from src.telemetry.setup import setup_telemetry
from src.transcription.local import LocalTranscriptionService
from src.ingestion.queue import BackgroundTaskQueue, StreaqQueue
from src.ingestion.pipeline_runner import (
    WorkerContext,
    build_pipeline_services,
    build_transcription_service,
    clear_audio_storage,
    run_ingest,
)
from src.shared.llm import get_llm_client, get_embedding_client

settings = get_settings()

import logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _make_job_runner(worker_context: WorkerContext, settings):
    """
    Closure handed to BackgroundTaskQueue so it can run ingest jobs
    in-process -- the local-dev, no-Redis equivalent of worker.py's
    ingest_episode_job task.
    """
    async def job_runner(episode_id, job_args: dict) -> None:
        services = build_pipeline_services(settings, worker_context)
        await run_ingest(episode_id, job_args, services)
    return job_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_telemetry(settings)
    clear_audio_storage(settings)
    app.state.session_store = InMemorySessionStore()

    async with AsyncExitStack() as stack:
        transcription_service = None
        if settings.redis_url:
            queue = StreaqQueue(redis_url=settings.redis_url)
            await stack.enter_async_context(queue)
            app.state.ingestion_queue = queue
        else:
            transcription_service = build_transcription_service(settings)
            worker_context = WorkerContext(
                llm_client=get_llm_client(),
                embedding_client=get_embedding_client(),
                transcription_service=transcription_service,
            )
            app.state.ingestion_queue = BackgroundTaskQueue(
                max_concurrent=settings.max_concurrent_ingestions,
                job_runner=_make_job_runner(worker_context, settings),
            )

        yield

        if not settings.redis_url and isinstance(transcription_service, LocalTranscriptionService):
            transcription_service.shutdown()


app = FastAPI(
    title="Throughline Knowledge Engine",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(BasicAuthMiddleware)

app.include_router(health.router, prefix="/api/v1")
app.include_router(feeds.router, prefix="/api/v1")
app.include_router(episodes.router, prefix="/api/v1")
app.include_router(speakers.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")