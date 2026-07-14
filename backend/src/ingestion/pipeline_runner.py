# src/ingestion/pipeline_runner.py
"""
Worker-side assembly and execution of the ingestion pipeline.

Mirrors how dependencies.py separates API-side wiring from route handlers --
this is the worker-side equivalent. Only the worker process imports this
module; the API process enqueues jobs by name only and never touches
pipeline code directly.
"""
from dataclasses import dataclass
from pathlib import Path
from src.llm.base import LLMClient
from src.llm.client import OpenAICompatibleEmbeddingClient
from src.transcription.local import LocalTranscriptionService
from src.transcription.remote import RemoteTranscriptionService

from uuid import UUID
from src.shared.db import AsyncSessionLocal
from src.ingestion import feed_service
from src.ingestion.pipeline import PipelineServices, ingest_episode
from src.ingestion.audio_downloader import AudioDownloader
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import SpeakerResolver
from src.ingestion.status_service import PipelineStatusService
from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.storage.vector_store import PgvectorStore

@dataclass
class WorkerContext:
    llm_client: LLMClient
    embedding_client: OpenAICompatibleEmbeddingClient
    transcription_service: LocalTranscriptionService | RemoteTranscriptionService

def build_transcription_service(settings):
    # Branching between Local and Remote transcription only needs to happen once, at startup, not per job.
    if settings.transcription_service_url:
        return RemoteTranscriptionService(
            service_url=settings.transcription_service_url,
            api_key=settings.transcription_api_key,
        )
    return LocalTranscriptionService(
        huggingface_token=settings.huggingface_token,
        whisper_backend=settings.whisper_backend,
        whisper_model=settings.whisper_model,
        diarization_model=settings.diarization_model,
        max_workers=settings.transcription_max_workers,
    )

def build_pipeline_services(settings, worker_context) -> PipelineServices:
    """
    Assemble PipelineServices for a single ingest job.

    LLM client, embedding client, and transcription service come from
    worker_context -- built once at worker startup and reused across jobs,
    since each wraps a real connection pool worth keeping warm. Everything
    else here is cheap and stateless, so it's built fresh per job.
    """
    return PipelineServices(
        status=PipelineStatusService(),
        downloader=AudioDownloader(storage_path=settings.audio_storage_path),
        transcription=worker_context.transcription_service,
        transcript_store=TranscriptStore(),
        speaker_store=SpeakerStore(),
        speaker_resolver=SpeakerResolver(
            llm_client=worker_context.llm_client,
            window_ms=settings.speaker_inference_window_ms,
        ),
        chunker=Chunker(
            chunk_size_tokens=settings.chunk_size_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
            topic_similarity_threshold=settings.topic_similarity_threshold,
        ),
        embedder=Embedder(embedding_client=worker_context.embedding_client),
        vector_store=PgvectorStore(),
    )


async def run_ingest(episode_id: UUID, job_args: dict, services: PipelineServices) -> None:
    """
    Run the ingestion pipeline for one episode.

    Called from the worker's @worker.task-decorated function (src/worker.py).
    Opens its own DB session, same two-phase pattern as before the queue was
    decoupled: one session to look up the episode, a second held for the
    duration of the actual pipeline run.
    """
    async with AsyncSessionLocal() as db:
        episode = await feed_service.get_episode(episode_id, db)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

    async with AsyncSessionLocal() as db:
        await ingest_episode(episode, job_args, services, db)

def clear_audio_storage(settings) -> None:
    """
    Wipe audio_storage_path on startup. Nothing here should be trusted to
    survive a restart -- files are meant to live only as long as a single
    ingest job takes to run.
    """
    storage_path = Path(settings.audio_storage_path)
    if not storage_path.exists():
        return
    for f in storage_path.iterdir():
        if f.is_file():
            f.unlink(missing_ok=True)