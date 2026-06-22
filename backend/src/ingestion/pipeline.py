# src/ingestion/pipeline.py

import logging
from dataclasses import dataclass
from uuid import UUID
from opentelemetry import trace

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.audio_downloader import AudioDownloader
from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import SpeakerResolver
from src.ingestion.status_service import PipelineStatusService
from src.storage.vector_store import VectorStore
from src.telemetry.tracer import tracer
from src.transcription.base import TranscriptionService, TranscriptSegment
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
    chunker: Chunker
    embedder: Embedder
    vector_store: VectorStore

## For dev and quicker pipeline UI testing....
# async def fake_ingest_episode(
#         episode: Episode,
#         job_args: dict,
#         services: PipelineServices,
#         db: AsyncSession
# ) -> None:
#     """
#     Only used for quickly moving through the pipeline witout producing any work.
#     """
#     import asyncio
#     episode_id = episode.id
#     stages = [
#         # "DOWNLOADING",
#         "TRANSCRIBING",
#         "INFERRING_SPEAKERS",
#         "CHUNKING",
#         "EMBEDDING",
#         "READY",
#     ]
#     for stage in stages:
#         await services.status.set(episode_id, stage, db=db)
#         await asyncio.sleep(1.5)


async def ingest_episode(
        episode: Episode,
        job_args: dict,
        services: PipelineServices,
        db: AsyncSession
) -> None:

    episode_id = episode.id

    with tracer.start_as_current_span("ingest_episode") as span:
        span.set_attribute("episode.id", str(episode_id))
        span.set_attribute("episode.title", episode.title or "untitled")
        span.set_attribute("episode.has_transcript_url", bool(episode.transcript_url))

        try:

            # ~~~~~~ Audio ~~~~~~

            await services.status.set(episode_id, "DOWNLOADING", db=db)

            transcript = None

            if episode.transcript_url:
                try:
                    logger.info("Episode %s: using RSS transcript %s", episode_id, episode.transcript_url)
                    transcript = await fetch_transcript(episode.transcript_url)
                except Exception as e:
                    logger.warning(
                        "Episode %s: failed to parse RSS transcript (%s), "
                        "falling back to audio transcription. Reason: %s",
                        episode_id, episode.transcript_url, e
                    )

            if transcript is None:

                # ~~~~~~ Audio Download ~~~~~~

                async def on_progress(progress: float) -> None:
                    await services.status.set(
                        episode_id, "DOWNLOADING", progress=progress, db=db
                    )

                audio_path = await services.downloader.download(
                    episode_id=episode_id,
                    audio_url=episode.audio_url,
                    on_progress=on_progress
                )

                # ~~~~~~ Transcription ~~~~~~

                await services.status.set(episode_id, "TRANSCRIBING", db=db)
                transcript = await services.transcription.transcribe(
                    audio_path,
                    speaker_count_hint=job_args.get("speaker_count_hint")
                )

            await services.transcript_store.save(episode_id, transcript, db=db)
            await services.speaker_store.initialize_from_transcript(episode_id, transcript, db=db)

            # ~~~~~~ Speaker Inference ~~~~~~
            # Returns None if no name found - not an error, pipeline continues.
            # UNKNOWN row stays as-is; promoted to SPEAKER_00 if name found.

            await services.status.set(episode_id, "INFERRING_SPEAKERS", db=db)
            inferred = await services.speaker_resolver.infer(transcript.segments)
            await services.speaker_store.save_inferred(episode_id, inferred, db=db)

            if inferred:
                logger.info(
                    "Episode %s: inferred speaker '%s' with %s confidence",
                    episode_id, inferred.name, inferred.confidence
                )
            else:
                logger.info("Episode %s: no speaker inferred, continuing with UNKNOWN", episode_id)

            # ~~~~~~ Chunking ~~~~~~
            # Two embedding calls happen here:
            # 1. Embed transcript segments - used by chunker for topic boundary detection, not stored
            # 2. Embed leaf chunk text - stored in chunks.embedding for retrieval

            await services.status.set(episode_id, "CHUNKING", db=db)

            segments = await services.transcript_store.get_segments(episode_id, db=db)

            if not segments:
                logger.warning("Episode %s: no segments found after transcription", episode_id)
                await services.status.set(episode_id, "READY", db=db)
                return

            segment_texts = [s.text for s in segments]
            segment_embeddings = await services.embedder._client.embed(segment_texts)

            chunks = services.chunker.chunk(
                episode_id=episode_id,
                segments=[
                    # Convert DB model rows to TranscriptSegment dataclasses
                    # TranscriptStore.get_segments() returns ORM models, chunker expects dataclasses
                    TranscriptSegment(
                        speaker_id=s.speaker_id,
                        text=s.text,
                        start_ms=s.start_ms,
                        end_ms=s.end_ms,
                        sequence_order=s.sequence_order,
                    )
                    for s in segments
                ],
                segment_embeddings=segment_embeddings,
            )

            num_parents = sum(1 for c in chunks if c.chunk_level == "parent")
            num_leaves = sum(1 for c in chunks if c.chunk_level == "leaf")
            logger.info(
                f"Episode {episode_id}: produced {len(chunks)} chunks ({num_parents} parents, {num_leaves} leaves)"
            )

            span.set_attribute("episode.chunk_count", len(chunks))
            span.set_attribute("episode.parent_chunk_count", num_parents)
            span.set_attribute("episode.leaf_chunk_count", num_leaves)

            # ~~~~~~ Embedding ~~~~~~

            await services.status.set(episode_id, "EMBEDDING", db=db)
            chunks = await services.embedder.embed(chunks)

            await services.vector_store.upsert(chunks, db=db)

            await services.status.set(episode_id, "READY", db=db)

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.exception("Ingestion failed for episode %s", episode_id)
            await services.status.set(episode_id, "ERROR", error=str(e), db=db)
            raise
