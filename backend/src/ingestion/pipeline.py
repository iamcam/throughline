# src/ingestion/pipeline.py
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.audio_downloader import AudioDownloader
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import SpeakerResolver
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
    speaker_resolver: SpeakerResolver


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
        # Attempt to identify the host from the intro window
        # Returns None if no name is found. This is not an error - pipeline continues regardless.
        # UNKNOWN row stays as-is; SPEAKER_00 promoted if name found.
        await services.status.set(episode_id, "INFERRING_SPEAKERS", db=db)
        inferred = await services.speaker_resolver.infer(transcript.segments)
        await services.speaker_store.save_inferred(episode_id, inferred, db=db)

        if inferred:
            logger.info(
                f"Episode {episode_id}: inferred speaker '{inferred.name}' "
                f"with {inferred.confidence} confidence"
            )
        else:
            logger.info(f"Episode {episode_id}: no speaker inferred, continuing with speaker label 'UNKNOWN'")

        # ~~~~~~~~ Chunking + Embedding ~~~~~~~~
        # Phase 4 implementation coming
        await services.status.set(episode_id, "CHUNKING", db=db)

        await services.status.set(episode_id, "READY", db=db)


    except Exception as e:
        logger.exception(f"Ingestion failed for episode {episode_id}")
        await services.status.set(episode_id, "ERROR", error=str(e), db=db)
        raise

