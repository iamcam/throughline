# src/ingestion/pipeline.py

import asyncio
import logging
import time
from dataclasses import dataclass
from uuid import UUID
import anyio
from opentelemetry import trace

from sqlalchemy.ext.asyncio import AsyncSession

from src.diarization.alignment import align_segments
from src.diarization.base import DiarizationService
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
from src.models.db import Episode


logger = logging.getLogger(__name__)

@dataclass
class PipelineServices:
    status: PipelineStatusService
    downloader: AudioDownloader
    transcription: TranscriptionService
    diarization: DiarizationService
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
#     statuses = [
#         # "DOWNLOADING",
#         "TRANSCRIBING",
#         "DIARIZING",
#         "INFERRING_SPEAKERS",
#         "CHUNKING",
#         "EMBEDDING",
#         "READY",
#     ]
#     for status in statuses:
#         await services.status.set(episode_id, status, db=db)
#         await asyncio.sleep(1.5)


async def ingest_episode(
        episode: Episode,
        job_args: dict,
        services: PipelineServices,
        db: AsyncSession
) -> None:

    episode_id = episode.id

    with tracer.start_as_current_span("ingest_episode") as span:
        span.set_attribute("openinference.span.kind", "CHAIN")

        span.set_attribute("episode.id", str(episode_id))
        span.set_attribute("episode.title", episode.title or "untitled")
        span.set_attribute("episode.duration_seconds", episode.duration_seconds)
        if run_label := job_args.get("run_label"):
            span.set_attribute("run_label", run_label)

        audio_path = None

        try:

            async def enter_stage(status: str) -> bool:
                """Write the next stage's status. False means this job no longer
                owns the episode (reset, superseded, or deleted) -- stop quietly."""
                if await services.status.set(episode_id, status, db=db):
                    return True
                logger.info(
                    "Episode %s: job no longer owns this episode; stopping before %s",
                    episode_id, status,
                )
                span.set_attribute("ingest.stopped_before", status)
                return False

            async def may_write(what: str) -> bool:
                """Check ownership immediately before a data write."""
                if await services.status.still_owns(episode_id, db):
                    return True
                logger.info(
                    "Episode %s: job no longer owns this episode; skipping %s",
                    episode_id, what,
                )
                span.set_attribute("ingest.stopped_before", what)
                return False

            # ~~~~~~ Audio ~~~~~~

            if not await enter_stage("DOWNLOADING"):
                return

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

            if not await enter_stage("TRANSCRIBING"):
                return

            transcript = await services.transcription.transcribe(audio_path)

            # ~~~~~~ Diarization ~~~~~~
            # Assigns real speaker_id labels onto transcript.segments, replacing
            # the UNKNOWN placeholders transcription left behind. See
            # src/diarization/alignment.py for how segments get matched to turns.

            if not await enter_stage( "DIARIZING"):
                return

            logger.info(f"Audio path: {audio_path}")
            diarization = await services.diarization.diarize(audio_path)
            transcript.segments = await asyncio.to_thread(
                align_segments, transcript.segments, diarization
            )

            span.set_attribute("episode.speaker_count", diarization.speaker_count)

            if not await may_write("transcript save"):
                return
            await services.transcript_store.save(episode_id, transcript, db=db)

            if not await may_write("speaker init"):
                return
            await services.speaker_store.initialize_from_transcript(episode_id, transcript, db=db)

            # ~~~~~~ Speaker Inference ~~~~~~
            # One inference pass per diarized speaker. A speaker mapped to None
            # means inference found nothing - that row stays unnamed and the
            # pipeline continues; the user can name it later via PUT /speakers.

            if not await enter_stage("INFERRING_SPEAKERS"):
                return

            inferred = await services.speaker_resolver.infer(transcript.segments)
            if not await may_write("speaker names"):
                return
            await services.speaker_store.save_inferred(episode_id, inferred, db=db)

            for speaker_id, result in inferred.items():
                if result:
                    logger.info(
                        "Episode %s: inferred %s as '%s' with %s confidence",
                        episode_id, speaker_id, result.name, result.confidence
                    )
                else:
                    logger.info(
                        "Episode %s: no name inferred for %s, continuing unnamed",
                        episode_id, speaker_id
                    )

            # ~~~~~~ Chunking ~~~~~~
            # Two embedding calls happen here:
            # 1. Embed transcript segments - used by chunker for topic boundary detection, not stored
            # 2. Embed leaf chunk text - stored in chunks.embedding for retrieval

            if not await enter_stage("CHUNKING"):
                return

            segments = await services.transcript_store.get_segments(episode_id, db=db)

            if not segments:
                logger.warning("Episode %s: no segments found after transcription", episode_id)
                await services.status.set(episode_id, "READY", db=db)

                if audio_path:
                    await services.downloader.delete(audio_path)

                return

            segment_texts = [s.text for s in segments]

            # Log any oversized transcript segments prior to embedding
            for i, text in enumerate(segment_texts):
                token_count = services.chunker.count_tokens(text)
                if token_count > services.embedder.max_input_tokens:
                    logger.warning(
                        "Oversized transcript segment before embedding: episode_id=%s; index=%d tokens=%d "
                        "words=%d start_ms=%d end_ms=%d preview=%r",
                        episode_id, i, token_count, len(text.split()),
                        segments[i].start_ms, segments[i].end_ms, text[:100],
                    )
            t0 = time.monotonic()
            segment_embeddings = await services.embedder.embed_texts(segment_texts)
            logger.info(
                "Episode %s: embedded %s segments for topic detection in %.1fs",
                episode_id, len(segment_texts), time.monotonic() - t0
            )

            chunks = await asyncio.to_thread(
                services.chunker.chunk,
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

            if not await enter_stage("EMBEDDING"):
                return

            chunks = await services.embedder.embed(chunks)

            if not await may_write("chunk upsert"):
                return
            await services.vector_store.upsert(chunks, db=db)

            # ~~~~~~ Wrap Up ~~~~~~
            span.set_status(trace.StatusCode.OK)

            await services.status.set(episode_id, "READY", db=db)
            if audio_path:
                await services.downloader.delete(audio_path)

        except asyncio.CancelledError as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, "cancelled")
            logger.warning("Ingestion cancelled or timed out for episode %s", episode_id)
            with anyio.CancelScope(shield=True):
                await services.status.set(
                    episode_id, "ERROR", error="Ingestion cancelled or timed out", db=db
                )
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.exception("Ingestion failed for episode %s", episode_id)
            await services.status.set(episode_id, "ERROR", error=str(e), db=db)
            raise