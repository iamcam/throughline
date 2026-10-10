# src/api/routers/episodes.py
import logging
from uuid import UUID
import asyncio

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update, delete, select

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sse_starlette.sse import EventSourceResponse

from src.api.episode_guards import require_ready_episode
from src.api.artwork_proxy import fetch_artwork
from src.api.dependencies import get_ingestion_queue, get_pipeline_status_service

from src.ingestion import feed_service
from src.ingestion.queue import IngestionQueue, QueueConnectionError
from src.ingestion.status_service import PipelineStatusService
from src.models.db import Episode as EpisodeModel, Chunk, TranscriptSegment, EpisodeSpeaker
from src.models.schemas import EpisodeResponse, PipelineStatusUpdate, IngestRequest, TranscriptResponse, TranscriptSegmentResponse
from src.shared.db import AsyncSessionLocal, get_db


router = APIRouter(prefix="/episodes", tags=["episodes"])
logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"READY", "ERROR", "PENDING"}

class _ClaimLost(Exception):
    """Another request claimed the episode between the status pre-check and the claim."""



async def _claim_and_enqueue(
    episode_id: UUID,
    job_args: dict,
    *,
    allowed_from: tuple[str, ...],
    db: AsyncSession,
    queue: IngestionQueue,
    status_service: PipelineStatusService,
) -> str:
    claimed_job_id: str | None = None

    async def claim(job_id: str) -> None:
        nonlocal claimed_job_id
        claimed = await status_service.claim_for_queue(
            episode_id, job_id, db, allowed_from=allowed_from
        )
        if not claimed:
            await db.rollback()
            raise _ClaimLost()
        await feed_service.delete_episode_data(episode_id, db)
        await db.commit()
        claimed_job_id = job_id

    try:
        return await queue.enqueue(
            episode_id=episode_id, job_args=job_args, before_submit=claim
        )
    except _ClaimLost:
        raise HTTPException(status_code=409, detail="Episode was queued by another request.")
    except QueueConnectionError as e:
        if claimed_job_id is not None:
            await status_service.set(
                episode_id,
                "ERROR",
                db,
                error="Could not submit the job to the queue.",
                job_id=claimed_job_id,
            )
        raise HTTPException(status_code=503, detail="Ingestion queue is unavailable.") from e



@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return EpisodeResponse.model_validate(episode)


@router.get("/{episode_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    await require_ready_episode(episode_id, db)

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


@router.post("/{episode_id}/reset", status_code=204)
async def reset_episode_handler(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    if episode.pipeline_status == "PENDING":
        return  # already reset -- idempotent no-op

    observed_status = episode.pipeline_status
    observed_job_id = episode.ingestion_job_id
    try:
        reset = await feed_service.reset_episode(
            episode_id,
            db,
            expected_status=observed_status,
            expected_job_id=observed_job_id,
        )
    except DBAPIError as exc:
        if not isinstance(exc.orig.__cause__, asyncpg.exceptions.LockNotAvailableError):
            raise
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Episode is being written to right now. Try again in a moment.",
        )

    if not reset:
        raise HTTPException(
            status_code=409,
            detail="Episode changed while resetting. Refresh and try again.",
        )

    if observed_job_id and observed_status not in ("READY", "ERROR"):
        try:
            await queue.cancel(observed_job_id)
        except QueueConnectionError:
            # Best-effort: the reset already removed this job's ownership,
            # so if it still runs, the pickup guard / bound writer neutralize it.
            logger.warning("Could not cancel job %s after reset of episode %s", observed_job_id, episode_id)



@router.get("/{episode_id}/status", response_model=PipelineStatusUpdate)
async def get_episode_status(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return PipelineStatusUpdate(
        status=episode.pipeline_status,
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

            yield {
                "data": PipelineStatusUpdate(
                    status = episode.pipeline_status,
                    progress = episode.pipeline_progress,
                ).model_dump_json()
            }

            if episode.pipeline_status in TERMINAL_STATUSES:
                break

            await asyncio.sleep(2)

    return EventSourceResponse(generator())


@router.post("/{episode_id}/ingest")
async def ingest_episode_handler(
    episode_id: UUID,
    body: IngestRequest = IngestRequest(),
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
    status_service: PipelineStatusService = Depends(get_pipeline_status_service),
):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    if episode.pipeline_status not in ("PENDING", "ERROR"):
        raise HTTPException(
            status_code=409,
            detail=f"Episode is already in-flight: {episode.pipeline_status}. Try /reingest when the pipeline is finished.",
        )

    job_args = {"run_label": body.run_label} if body.run_label else {}
    job_id = await _claim_and_enqueue(
        episode_id,
        job_args,
        allowed_from=("PENDING", "ERROR"),
        db=db,
        queue=queue,
        status_service=status_service,
    )

    return {
        "status": "accepted",
        "job_id": job_id,
    }


@router.post("/{episode_id}/reingest")
async def reingest_episode_handler(
    episode_id: UUID,
    body: IngestRequest = IngestRequest(),
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
    status_service: PipelineStatusService = Depends(get_pipeline_status_service),
):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    if episode.pipeline_status == "PENDING":
        raise HTTPException(
            status_code=409,
            detail="Episode must be ingested first at /ingest.",
        )

    if episode.pipeline_status not in ("ERROR", "READY"):
        raise HTTPException(
            status_code=409,
            detail=f"Episode is already in-flight: {episode.pipeline_status}. Try again when the pipeline is finished.",
        )

    job_args = {"run_label": body.run_label} if body.run_label else {}
    job_id = await _claim_and_enqueue(
        episode_id,
        job_args,
        allowed_from=("ERROR", "READY"),
        db=db,
        queue=queue,
        status_service=status_service,
    )

    return {
        "status": "accepted",
        "job_id": job_id,
    }


@router.get("/{episode_id}/artwork")
async def get_episode_artwork(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Request the cover art in cases where the client cannot load the image directly
    (eg, host prevents resources from loading on other domains' pages). fetch_artwork
    will proxy request the image
    """
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not episode.image_url:
        raise HTTPException(status_code=404, detail="Episode has no artwork")
    return await fetch_artwork(episode.image_url)