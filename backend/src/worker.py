# src/worker.py
"""
streaQ worker process. For cli entry point see worker_cli.py

Builds the WorkerContext dependencies once at process startup and reuses
them across every job -- the LLM/embedding clients and transcription
service each wrap a real connection pool worth keeping warm.
"""
import logging
from typing import AsyncGenerator
from uuid import UUID
from contextlib import asynccontextmanager

from streaq import Worker

from src.telemetry.setup import setup_telemetry
from src.config import get_settings
from src.ingestion.pipeline_runner import (
    WorkerContext,
    build_pipeline_services,
    build_transcription_service,
    build_diarization_service,
    clear_audio_storage,
    run_ingest,
)
from src.shared.jobs import INGEST_EPISODE_JOB
from src.shared.llm import get_llm_client, get_embedding_client
from src.diarization.local import LocalDiarizationService
from src.transcription.local import LocalTranscriptionService

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

@asynccontextmanager
async def lifespan() -> AsyncGenerator[WorkerContext, None]:
    setup_telemetry(settings)
    clear_audio_storage(settings)
    transcription_service = build_transcription_service(settings)
    diarization_service = build_diarization_service(settings)
    yield WorkerContext(
        llm_client=get_llm_client(),
        embedding_client=get_embedding_client(),
        transcription_service=transcription_service,
        diarization_service=diarization_service,
    )
    if isinstance(transcription_service, LocalTranscriptionService):
        transcription_service.shutdown()

    if isinstance(diarization_service, LocalDiarizationService):
        diarization_service.shutdown()


def build_worker() -> Worker:
    worker = Worker(
        redis_url=settings.redis_url,
        concurrency=settings.max_concurrent_ingestions,
        lifespan=lifespan,
    )

    @worker.task(name=INGEST_EPISODE_JOB)
    async def ingest_episode_job(episode_id: UUID, job_args: dict) -> None:
        services = build_pipeline_services(settings, ingest_episode_job.worker.context)
        await run_ingest(episode_id, job_args, services)

    return worker
