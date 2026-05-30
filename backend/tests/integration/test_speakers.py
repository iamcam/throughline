# tests/integration/test_speakers.py
import pytest
from uuid import uuid4
from sqlalchemy import select

from src.ingestion.speaker_store import SpeakerStore
from src.ingestion.speaker_resolver import InferredSpeaker
from src.models.db import EpisodeSpeaker, Feed, Episode


# --- fixtures ---

@pytest.fixture
async def episode(db_session):
    """A minimal episode row with one UNKNOWN speaker already initialised."""
    feed = Feed(
        id=uuid4(),
        rss_url="https://example.com/feed.rss",
        title="Synthetic Minds",
    )
    db_session.add(feed)
    await db_session.flush()

    ep = Episode(
        id=uuid4(),
        feed_id=feed.id,
        guid=str(uuid4()),
        title="Test Episode",
        pipeline_status="TRANSCRIBING",
    )
    db_session.add(ep)
    await db_session.flush()

    speaker = EpisodeSpeaker(
        id=uuid4(),
        episode_id=ep.id,
        speaker_id="UNKNOWN",
        display_name=None,
        name_inferred=False,
        name_confirmed=False,
        confidence=None,
    )
    db_session.add(speaker)
    await db_session.commit()

    return ep



# --- save_inferred ---

@pytest.mark.asyncio
async def test_save_inferred_sets_display_name_and_confidence(db_session, episode):
    store = SpeakerStore()
    result = InferredSpeaker(name="Ada Sinclair", confidence="high")
    await store.save_inferred(episode.id, result, db_session)

    row = await db_session.scalar(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    assert row.display_name == "Ada Sinclair"
    assert row.confidence == "high"
    assert row.name_inferred is True
    assert row.name_confirmed is False


@pytest.mark.asyncio
async def test_save_inferred_none_leaves_row_unchanged(db_session, episode):
    store = SpeakerStore()
    await store.save_inferred(episode.id, None, db_session)

    row = await db_session.scalar(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    assert row.display_name is None
    assert row.name_inferred is False
    assert row.confidence is None


# --- confirm_names ---

@pytest.mark.asyncio
async def test_confirm_name_without_edit_preserves_name_inferred(db_session, episode):
    store = SpeakerStore()

    # First infer a name
    await store.save_inferred(episode.id, InferredSpeaker(name="Ada Sinclair", confidence="high"), db_session)

    # User confirms without changing the name
    await store.confirm_names(
        episode.id,
        [{"speaker_id": "UNKNOWN", "display_name": "Ada Sinclair"}],
        db_session,
    )

    row = await db_session.scalar(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    assert row.name_confirmed is True
    assert row.name_inferred is True  # unchanged


@pytest.mark.asyncio
async def test_confirm_name_with_edit_sets_name_inferred_false(db_session, episode):
    store = SpeakerStore()

    await store.save_inferred(episode.id, InferredSpeaker(name="Ada Sinclair", confidence="high"), db_session)

    # User corrects the name
    await store.confirm_names(
        episode.id,
        [{"speaker_id": "UNKNOWN", "display_name": "Ada S."}],
        db_session,
    )

    row = await db_session.scalar(
        select(EpisodeSpeaker).where(EpisodeSpeaker.episode_id == episode.id)
    )
    assert row.name_confirmed is True
    assert row.name_inferred is False



# --- get_speakers ---

@pytest.mark.asyncio
async def test_get_speakers_returns_all_rows(db_session, episode):
    store = SpeakerStore()
    speakers = await store.get_speakers(episode.id, db_session)
    assert len(speakers) == 1
    assert speakers[0].speaker_id == "UNKNOWN"
