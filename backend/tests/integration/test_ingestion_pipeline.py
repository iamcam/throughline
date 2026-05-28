# tests/integration/test_ingestion_pipeline.py
import json
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select

from src.ingestion.pipeline import PipelineServices, ingest_episode
from src.ingestion.transcript_store import TranscriptStore
from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.status_service import PipelineStatusService
from src.transcription.base import TranscriptResult, TranscriptSegment
from src.transcription.local import LocalTranscriptionService
from src.transcription.remote import RemoteTranscriptionService
from src.transcription.base import TranscriptionService
from src.models.db import (
    Feed, Episode,
    TranscriptSegment as TranscriptSegmentModel,
    EpisodeSpeaker,
)


@pytest.fixture
def sample_transcript() -> TranscriptResult:
    with open("tests/fixtures/sample_transcript.json") as f:
        data = json.load(f)
    return TranscriptResult(
        segments=[
            TranscriptSegment(**s) for s in data["segments"]
        ],
        language=data["language"],
        source=data["source"],
    )


@pytest.fixture
async def episode(db_session):
    """Create a minimal feed + episode in the test DB."""
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
    TranscriptionService mock returns sample_transcript directly —
    no Whisper, no Pyannote, no subprocess.
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
    )


async def test_ingest_stores_segments_with_speaker_id(
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
        assert seg.speaker_id.startswith("SPEAKER_")


async def test_ingest_creates_episode_speakers_rows(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(EpisodeSpeaker)
        .where(EpisodeSpeaker.episode_id == episode.id)
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

    # Confirm the model doesn't even have a display_name column
    for seg in segments:
        assert not hasattr(seg, "display_name")


async def test_episode_speakers_initialized_with_null_display_name(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    result = await db_session.execute(
        select(EpisodeSpeaker)
        .where(EpisodeSpeaker.episode_id == episode.id)
    )
    speakers = result.scalars().all()

    for speaker in speakers:
        assert speaker.display_name is None
        assert speaker.name_inferred is False
        assert speaker.name_confirmed is False


async def test_status_transitions_correctly(
    episode, mock_services, db_session
):
    await ingest_episode(episode, {}, mock_services, db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_status == "PENDING_NAMES"


async def test_error_stored_on_failure(episode, mock_services, db_session):
    mock_services.downloader.download.side_effect = RuntimeError("network failure")

    with pytest.raises(RuntimeError):
        await ingest_episode(episode, {}, mock_services, db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_status == "ERROR"
    assert "network failure" in episode.pipeline_error


def test_local_satisfies_protocol():
    from src.transcription.base import TranscriptionService
    svc = LocalTranscriptionService(
        huggingface_token="hf_fake",
        whisper_backend="faster_whisper",
        whisper_model_size="tiny",
        diarization_model="pyannote/speaker-diarization-community-1",
    )
    assert isinstance(svc, TranscriptionService)


def test_remote_satisfies_protocol():
    from src.transcription.base import TranscriptionService
    svc = RemoteTranscriptionService(service_url="http://localhost:8001")
    assert isinstance(svc, TranscriptionService)