# src/ingestion/pipeline.py
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.audio_downloader import AudioDownloader
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.status_service import PipelineStatusService
from src.transcription.base import TranscriptionService
from src.transcription.transcript_fetcher import fetch_transcript
from src.models.db import Episode

logger = logging.getLogger(__name__)


@dataclass
class PipelineServices:
    status: PipelineStatusService
    downloader: AudioDownloader
    transcription: TranscriptionService
    transcript_store: TranscriptStore
    speaker_store: SpeakerStore


async def ingest_episode(
        episode: Episode,
        job_args: dict,
        services: PipelineServices,
        db: AsyncSession
) -> None:
    episode_id = episode.id
    try:

        # ~~~~~~~~ Audio ~~~~~~~~
        await services.status.set(episode_id, "DOWNLOADING", db=db)

        transcript = None
        audio_path = None

        if episode.transcript_url:

            # rss-provided transcript - fetch and verify prior to audio download
            try:
                logger.info(f"Episode {episode_id}: using RSS transcript {episode.transcript_url}")
                transcript = await fetch_transcript(episode.transcript_url)
            except Exception as e:
                logger.warning(
                    f"Episode {episode_id}: failed to parse rss transcript "
                    f"({episode.transcript_url}), falling back to audio transcription. "
                    f"Reason: {e}"
                )

        # if no transcript provided or there was a formatting error
        if transcript is None:

            # ~~~~~~~~ Audio Download ~~~~~~~~

            async def on_progress(progress: float) -> None:
                await services.status.set(
                    episode_id, "DOWNLOADING", progress=progress, db=db
                )

            audio_path = await services.downloader.download(
                episode_id=episode_id,
                audio_url=episode.audio_url,
                on_progress=on_progress
            )

            # ~~~~~~~~ Transcription ~~~~~~~~

            await services.status.set(episode_id, "TRANSCRIBING", db=db)
            transcript = await services.transcription.transcribe(
                audio_path,
                speaker_count_hint=job_args.get("speaker_count_hint")
            )

        await services.transcript_store.save(episode_id, transcript, db=db)
        await services.speaker_store.initialize_from_transcript(episode_id, transcript, db=db)

        # ~~~~~~~~ Speaker Inference ~~~~~~~~
        await services.status.set(episode_id, "PENDING_NAMES", db=db)

    except Exception as e:
        logger.exception(f"Ingestion failed for episode {episode_id}")
        await services.status.set(episode_id, "ERROR", error=str(e), db=db)
        raise

async def chunk_episode(
    episode_id: UUID,
    services: PipelineServices,
    db: AsyncSession
) -> None:
    """
    TODO: Resolve in phase 4
    Runs after speaker confirmation.
    Chunking and embedding to come in Phase 4.
    Stub kelpt here so the status transition is reserved and the queue can call this by name moving forward
    """
    try:
        await services.status.set(episode_id, "CHUNKING", db=db)

        # Phase 4 fills in here

        await services.status.set(episode_id, "READY", db=db)

    except Exception as e:
        logger.exception(f"Chunking failed for episode {episode_id}")
        await services.status.set(episode_id, "ERROR", error=str(e), db=db)
        raise