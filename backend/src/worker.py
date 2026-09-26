# src/worker.py
"""
streaQ worker process. For cli entry point see worker_cli.py

Builds the WorkerContext dependencies once at process startup and reuses
them across every job -- the LLM/embedding clients and transcription
service each wrap a real connection pool worth keeping warm.
"""
import logging
from typing import AsyncGenerator
from uuid import uuid4, UUID
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
logger = logging.getLogger(__name__)


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
    w_id = uuid4().hex[:8]
    logger.info(f"👷‍♂️ 🧱 build_worker instance {w_id}")
    worker = Worker(
        redis_url=settings.redis_url,
        concurrency=settings.max_concurrent_ingestions,
        idle_timeout=settings.streaq_worker_idle_timeout,
        lifespan=lifespan,
    )
    # streaq buffers 2x concurrency by default, and prefetch=0 can't disable it (0 treated as unset).
    # Buffered tasks aren't renewed, so on long jobs they pass idle_timeout, get reclaimed by the
    # same worker, and run twice concurrently. Only fetch when a slot is actually free.
    worker.prefetch = worker.concurrency

    @worker.task(name=INGEST_EPISODE_JOB, timeout=settings.streaq_task_timeout)
    async def ingest_episode_job(episode_id: UUID, job_args: dict) -> None:
        logger.info(
            "👷‍♂️ 🔰 ingest_episode_job starting: task_id=%s try=%s episode_id=%s worker=%s",
            ingest_episode_job.context.task_id,
            ingest_episode_job.context.tries,
            episode_id,
            w_id,
        )
        services = build_pipeline_services(settings, ingest_episode_job.worker.context)
        await run_ingest(episode_id, job_args, services)

    return worker

