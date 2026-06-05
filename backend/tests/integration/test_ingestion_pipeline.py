# tests/integration/test_ingestion_pipeline.py
import json
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock
from sqlalchemy import select

from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.storage.vector_store import PgvectorStore
from src.llm.base import EmbeddingClient
from src.ingestion.pipeline import PipelineServices, ingest_episode
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import SpeakerResolver
from src.ingestion.status_service import PipelineStatusService
from src.transcription.base import TranscriptResult, TranscriptSegment, TranscriptionService
from src.transcription.local import LocalTranscriptionService
from src.transcription.remote import RemoteTranscriptionService
from src.llm.base import LLMResponse
from src.models.db import (
    Feed, Episode,
    TranscriptSegment as TranscriptSegmentModel,
    EpisodeSpeaker,
    Chunk
)


# --- shared mock ---

class MockLLMClient:
    """Returns a fixed response. No inference, no network."""
    def __init__(self, response_content: str = '{"name": "Ada Sinclair", "confidence": "high"}'):
        self._content = response_content

    async def complete(self, messages, response_format=None, temperature=0.7):
        return LLMResponse(content=self._content)


class MockEmbeddingClient:
    """
    Returns deterministic vectors based on input index.
    Groups of three consecutive texts share a vector.
    Similarity within a group = 1.0 (no topic cut).
    Similarity between groups = 0.0 (topic cut at every group boundary).
    With threshold 0.75 this produces one topic segment per group of three.
    """
    _VECTOR_A = [1.0, 0.0] + [0.0] * 766
    _VECTOR_B = [0.0, 1.0] + [0.0] * 766

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            self._VECTOR_A if (i // 3) % 2 == 0 else self._VECTOR_B
            for i in range(len(texts))
        ]


# --- fixtures ---

@pytest.fixture
def sample_transcript() -> TranscriptResult:
    with open("tests/fixtures/sample_transcript.json") as f:
        data = json.load(f)
    return TranscriptResult(
        segments=[TranscriptSegment(**s) for s in data["segments"]],
        language=data["language"],
        source=data["source"],
    )


@pytest.fixture
async def episode(db_session):
    feed = Feed(
        id=uuid4(),
        rss_url="https://example.com/feed.rss",
        title="Test Feed",
    )
    ep = Episode(
        id=uuid4(),
        feed_id=feed.id,
        guid="test-episode-001",
        title="Test Episode",
        audio_url="https://example.com/episode.mp3",
        pipeline_status="PENDING",
    )
    db_session.add(feed)
    db_session.add(ep)
    await db_session.commit()
    return ep


@pytest.fixture
def mock_services(sample_transcript) -> PipelineServices:
    """
    PipelineServices with real storage services and mocked I/O.
    TranscriptionService returns sample_transcript directly - no Whisper.
    LLM returns a fixed inference result - no network call.
    EmbeddingClient returns zero vectors - no embedding endpoint call.
    VectorStore uses real PgvectorStore against the test DB.
    """
    mock_transcription = AsyncMock(spec=TranscriptionService)
    mock_transcription.transcribe.return_value = sample_transcript

    mock_downloader = AsyncMock()
    mock_downloader.download.return_value = "/tmp/fake_audio.mp3"

    return PipelineServices(
        status=PipelineStatusService(),
        downloader=mock_downloader,
        transcription=mock_transcription,
        transcript_store=TranscriptStore(),
        speaker_store=SpeakerStore(),
        speaker_resolver=SpeakerResolver(llm_client=MockLLMClient()),
        chunker=Chunker(
            chunk_size_tokens=256,
            chunk_overlap_tokens=32,
            min_tokens=20,
            topic_similarity_threshold=0.75
        ),
        embedder=Embedder(embedding_client=MockEmbeddingClient()),
        vector_store=PgvectorStore(),
    )


# --- tests ---

async def test_ingest_stores_segments_with_unknown_speaker_id(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(TranscriptSegmentModel)
        .where(TranscriptSegmentModel.episode_id == episode.id)
        .order_by(TranscriptSegmentModel.sequence_order)
    )
    segments = result.scalars().all()

    assert len(segments) > 0
    for seg in segments:
        assert seg.speaker_id == "UNKNOWN"


async def test_ingest_creates_episode_speakers_rows(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    speakers = result.scalars().all()
    assert len(speakers) > 0


async def test_display_name_not_stored_in_segments(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(TranscriptSegmentModel)
        .where(TranscriptSegmentModel.episode_id == episode.id)
    )
    segments = result.scalars().all()
    for seg in segments:
        assert not hasattr(seg, "display_name")


async def test_episode_speakers_initialized_with_null_display_name(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    speakers = result.scalars().all()
    assert len(speakers) > 0
    for speaker in speakers:
        assert speaker.name_confirmed is False

async def test_speaker_inference_sets_display_name(
    episode, mock_services, db_session
):
    """MockLLMClient returns Ada Sinclair/high — verify it lands in the DB."""
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    speaker = result.scalars().first()
    assert speaker.display_name == "Ada Sinclair"
    assert speaker.confidence == "high"
    assert speaker.name_inferred is True


async def test_status_transitions_to_ready(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_status == "READY"


async def test_error_stored_on_failure(episode, mock_services, db_session):
    mock_services.downloader.download.side_effect = RuntimeError("network failure")

    with pytest.raises(RuntimeError):
        await ingest_episode(episode, {}, mock_services, db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_status == "ERROR"
    assert "network failure" in episode.pipeline_error


def test_local_satisfies_protocol():
    svc = LocalTranscriptionService(
        huggingface_token="hf_fake",
        whisper_backend="faster_whisper",
        whisper_model_size="tiny",
        diarization_model=None,
    )
    assert isinstance(svc, TranscriptionService)


def test_remote_satisfies_protocol():
    svc = RemoteTranscriptionService(service_url="http://localhost:8001")
    assert isinstance(svc, TranscriptionService)


# ~~~~~~ Chunker ~~~~~~


async def test_ingest_produces_chunks(episode, mock_services, db_session):
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(Chunk.episode_id == episode.id)
    )
    chunks = result.scalars().all()
    assert len(chunks) > 0


async def test_ingest_leaf_chunks_have_embeddings(episode, mock_services, db_session):
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(
            Chunk.episode_id == episode.id,
            Chunk.chunk_level == "leaf",
        )
    )
    leaves = result.scalars().all()
    assert len(leaves) > 0
    for leaf in leaves:
        assert leaf.embedding is not None


async def test_ingest_parent_chunks_have_no_embeddings(episode, mock_services, db_session):
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(
            Chunk.episode_id == episode.id,
            Chunk.chunk_level == "parent",
        )
    )
    parents = result.scalars().all()
    assert len(parents) > 0
    for parent in parents:
        assert parent.embedding is None


async def test_ingest_chunks_carry_speaker_id(episode, mock_services, db_session):
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(Chunk.episode_id == episode.id)
    )
    chunks = result.scalars().all()
    for chunk in chunks:
        assert chunk.speaker_id in ("UNKNOWN", "SPEAKER_00")
        assert not hasattr(chunk, "display_name")

async def test_ingest_produces_correct_parent_count(
    episode, mock_services, db_session
):
    """
    16 segments with groups-of-3 embedding pattern produce 6 topic segments,
    but the last segment is short and merges into its predecessor, leaving 5 parents.
    """
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(
            Chunk.episode_id == episode.id,
            Chunk.chunk_level == "parent",
        )
    )
    parents = result.scalars().all()
    assert len(parents) == 5


async def test_ingest_parent_timestamps_are_contiguous(
    episode, mock_services, db_session
):
    """
    Parent chunks should span the full episode without gaps.
    First parent starts at 0ms, last parent ends at the final segment end_ms.
    """
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk)
        .where(
            Chunk.episode_id == episode.id,
            Chunk.chunk_level == "parent",
        )
        .order_by(Chunk.start_ms)
    )
    parents = result.scalars().all()

    assert parents[0].start_ms == 0
    assert parents[-1].end_ms == 130800  # last segment end_ms from fixture


async def test_ingest_topic_boundaries_at_group_transitions(
    episode, mock_services, db_session
):
    """
    Topic cuts happen at segments 3, 6, 9, 12, 15 — but segment 15 is short
    and merges into group 5, so only 5 parent boundaries appear.
    """
    expected_starts = [
        0,       # segment 0  - group 1 start
        18800,   # segment 3  - group 2 start
        43200,   # segment 6  - group 3 start
        67500,   # segment 9  - group 4 start
        97000,   # segment 12 - group 5 start (absorbs group 6)
    ]

    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk)
        .where(
            Chunk.episode_id == episode.id,
            Chunk.chunk_level == "parent",
        )
        .order_by(Chunk.start_ms)
    )
    parents = result.scalars().all()
    actual_starts = [p.start_ms for p in parents]
    assert actual_starts == expected_starts


async def test_ingest_leaves_all_reference_a_parent(
    episode, mock_services, db_session
):
    """Every leaf chunk's parent_id points to an existing parent chunk."""
    from src.models.db import Chunk
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(Chunk).where(Chunk.episode_id == episode.id)
    )
    all_chunks = result.scalars().all()

    parent_ids = {c.id for c in all_chunks if c.chunk_level == "parent"}
    leaves = [c for c in all_chunks if c.chunk_level == "leaf"]

    assert len(leaves) > 0
    for leaf in leaves:
        assert leaf.parent_id in parent_ids
