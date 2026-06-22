# src/api/routers/episodes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import asyncio
from sqlalchemy import update, delete, select

from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import get_db, get_ingestion_queue, AsyncSessionLocal, get_llm_client, get_embedding_client
from src.ingestion.queue import IngestionQueue
from src.models.db import Episode as EpisodeModel, Chunk, TranscriptSegment, EpisodeSpeaker
from src.models.schemas import EpisodeResponse, PipelineStatusUpdate, IngestRequest, TranscriptResponse, TranscriptSegmentResponse
from src.ingestion import feed_service
from src.ingestion.pipeline import PipelineServices, ingest_episode
from src.ingestion.audio_downloader import AudioDownloader
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import SpeakerResolver
from src.ingestion.status_service import PipelineStatusService
from src.transcription.local import LocalTranscriptionService
from src.transcription.remote import RemoteTranscriptionService
from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.storage.vector_store import PgvectorStore

from src.config import get_settings

router = APIRouter(prefix="/episodes", tags=["episodes"])

TERMINAL_STATUSES = {"READY", "ERROR"}


def _build_pipeline_services(settings) -> PipelineServices:
    """
    Build PipelineServices from current settings.
    Called once per ingest request - all services are stateless.
    """
    if settings.transcription_service_url:
        transcription = RemoteTranscriptionService(
            service_url=settings.transcription_service_url,
            api_key=settings.transcription_api_key
        )
    else:
        transcription = LocalTranscriptionService(
            huggingface_token=settings.huggingface_token,
            whisper_backend=settings.whisper_backend,
            whisper_model=settings.whisper_model,
            diarization_model=settings.diarization_model,
        )

    return PipelineServices(
        status=PipelineStatusService(),
        downloader=AudioDownloader(storage_path=settings.audio_storage_path),
        transcription=transcription,
        transcript_store=TranscriptStore(),
        speaker_store=SpeakerStore(),
        speaker_resolver=SpeakerResolver(
            llm_client=get_llm_client(),
            window_ms=settings.speaker_inference_window_ms,
        ),
        chunker=Chunker(
            chunk_size_tokens=settings.chunk_size_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
            topic_similarity_threshold=settings.topic_similarity_threshold
        ),
        embedder=Embedder(embedding_client=get_embedding_client()),
        vector_store=PgvectorStore(),
    )


async def _run_ingest(episode_id: UUID, job_args: dict, services: PipelineServices):
    """
    Wrapper passed to the queue - creates its own DB session per pipeline call. Does not reuse the request-scoped session from the route handler.
    """
    async with AsyncSessionLocal() as db:
        episode = await feed_service.get_episode(episode_id, db)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

    async with AsyncSessionLocal() as db:
        await ingest_episode(episode, job_args, services, db)
        # If needed to blow through a fake pipeline with status updates,
        # comment out ingest_episode and un-comment the following two lines
        # from src.ingestion.pipeline import fake_ingest_episode
        # await fake_ingest_episode(episode, job_args, services, db)



@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return EpisodeResponse.model_validate(episode)



@router.get("/{episode_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Load segments ordered by sequence
    segments_result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.sequence_order)
    )
    segments = segments_result.scalars().all()

    # Load speaker display names for this episode
    speakers_result = await db.execute(
        select(EpisodeSpeaker)
        .where(EpisodeSpeaker.episode_id == episode_id)
    )
    speakers = {s.speaker_id: s.display_name for s in speakers_result.scalars().all()}

    return TranscriptResponse(
        episode_id=str(episode_id),
        segments=[
            TranscriptSegmentResponse(
                speaker_id=seg.speaker_id,
                display_name=speakers.get(seg.speaker_id),
                text=seg.text,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                sequence_order=seg.sequence_order,
            )
            for seg in segments
        ]
    )


@router.delete("/{episode_id}/transcript", status_code=204)
async def delete_episode_transcription_handler(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await feed_service.delete_episode_transcription(episode_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Episode not found")


@router.get("/{episode_id}/status", response_model=PipelineStatusUpdate)
async def get_episode_status(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return PipelineStatusUpdate(
        status=episode.pipeline_status,
        stage=episode.pipeline_stage,
        progress=episode.pipeline_progress,
        error=episode.pipeline_error,
    )

@router.get("/{episode_id}/status/stream")
async def stream_episode_status(
    episode_id: UUID,
    queue: IngestionQueue = Depends(get_ingestion_queue)
):
    async def generator():
        while True:
            async with AsyncSessionLocal() as db:
                episode = await feed_service.get_episode(episode_id, db)

            if not episode:
                yield {
                    "data": PipelineStatusUpdate(
                        status = "ERROR",
                        error = "Episode not found"
                    ).model_dump_json()
                }
                break

            position = None
            if episode.ingestion_job_id:
                position = await queue.get_position(episode.ingestion_job_id)

            yield {
                "data": PipelineStatusUpdate(
                    status = episode.pipeline_status,
                    stage = episode.pipeline_stage,
                    progress = episode.pipeline_progress,
                    position = position
                ).model_dump_json()
            }

            if episode.pipeline_status in TERMINAL_STATUSES:
                break

            await asyncio.sleep(2)

    return EventSourceResponse(generator())


@router.post("/{episode_id}/ingest")
async def ingest_episode_handler(
    episode_id: UUID,
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    if episode.pipeline_status not in ("PENDING", "ERROR"):
        raise HTTPException(
            status_code=409,
            detail=f"Episode is already {episode.pipeline_status}. Use /reingest to force.",
        )

    settings = get_settings()
    services = _build_pipeline_services(settings)
    job_args = {"speaker_count_hint": body.speaker_count_hint}

    job_id = await queue.enqueue(
        episode_id=episode_id,
        job_args=job_args,
        worker=lambda episode_id, args: _run_ingest(episode_id, args, services),
    )

    # Write job_id and initial QUEUED status to DB immediately
    # so the SSE endpoint can report queue position before the job starts
    await db.execute(
        update(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .values(pipeline_status="QUEUED", ingestion_job_id=job_id)
    )
    await db.commit()

    position = await queue.get_position(job_id)

    return {
        "status": "accepted",
        "job_id": job_id,
        "queue_position": position,
    }


@router.post("/{episode_id}/reingest")
async def reingest_episode_handler(
    episode_id: UUID,
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    settings = get_settings()
    services = _build_pipeline_services(settings)
    job_args = {"speaker_count_hint": body.speaker_count_hint}

    job_id = await queue.enqueue(
        episode_id=episode_id,
        job_args=job_args,
        worker=lambda episode_id, args: _run_ingest(episode_id, args, services),
    )

    await db.execute(delete(Chunk).where(Chunk.episode_id == episode_id))
    await db.execute(delete(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id))
    await db.execute(delete(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode_id))

    await db.execute(
        update(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .values(
            pipeline_status="QUEUED",
            pipeline_stage=None,
            pipeline_progress=None,
            pipeline_error=None,
            ingestion_job_id=job_id
        )
    )
    await db.commit()

    position = await queue.get_position(job_id)

    return {
        "status": "accepted",
        "job_id": job_id,
        "queue_position": position,
    }

