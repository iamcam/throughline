# tests/unit/test_tool_dispatcher.py
from __future__ import annotations
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.query.tool_dispatcher import ToolDispatcher
from src.query.session_store import ChatSession
from src.query.result_hydrator import ChunkResult
from src.storage.vector_store import SearchFilters
from src.llm.base import ToolCall


# ~~~~~~ Helpers ~~~~~~

EPISODE_ID = uuid.uuid4()
FEED_ID = uuid.uuid4()
SESSION_ID = "test-session"


def make_session(**kwargs) -> ChatSession:
    return ChatSession(
        session_id=SESSION_ID,
        scope_feed_ids=kwargs.get("scope_feed_ids", []),
        scope_episode_ids=kwargs.get("scope_episode_ids", []),
        messages=[],
    )


def make_chunk_result(**overrides) -> ChunkResult:
    defaults = dict(
        chunk_id=str(uuid.uuid4()),
        text="Leaf text about consciousness.",
        parent_text="Broader discussion about consciousness and AI.",
        episode_id=str(EPISODE_ID),
        episode_title="Synthetic Minds Ep. 1",
        audio_url="https://domain.ext/file.mp3",
        display_name="Marcus Webb",
        timestamp_display="1:03:42",
        start_ms=3_822_000,
        end_ms=3_890_000,
        similarity_score=0.91,
    )
    defaults.update(overrides)
    return ChunkResult(**defaults)


def make_mock_retriever(results=None):
    retriever = MagicMock()
    retriever.search = AsyncMock(
        return_value=results if results is not None else [make_chunk_result()]
    )
    return retriever



def make_mock_db(speaker_pairs_result=None, scalars_result=None):
    """
    Minimal async DB mock.
    speaker_pairs_result: list of (episode_id, speaker_id) tuples returned by
        the speaker-name resolution query (mocked via .all(), matching the
        real query's plain two-column select).
    scalars_result: what scalars().all() returns (get_speaker_profile query).
    """
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = scalars_result or []

    mock_rows = []
    for episode_id, speaker_id in (speaker_pairs_result or []):
        row = MagicMock()
        row.episode_id = episode_id
        row.speaker_id = speaker_id
        mock_rows.append(row)
    execute_result.all.return_value = mock_rows

    db = MagicMock()
    db.execute = AsyncMock(return_value=execute_result)
    return db


# ~~~~~~ Tests ~~~~~~

@pytest.mark.asyncio
async def test_dispatches_search_knowledge_base():
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    db = make_mock_db()
    session = make_session()

    tool_call = ToolCall(
        id="tc1",
        name="search_knowledge_base",
        arguments={"query": "consciousness and AI"},
    )

    result = await dispatcher.dispatch(tool_call, session, db)
    parsed = json.loads(result)

    assert "results" in parsed
    assert len(parsed["results"]) == 1
    retriever.search.assert_called_once()


@pytest.mark.asyncio
async def test_dispatches_get_speaker_profile():
    dispatcher = ToolDispatcher(retriever=make_mock_retriever())

    # Mock two episode_speakers rows for "Marcus Webb"
    mock_speaker_1 = MagicMock()
    mock_speaker_1.episode_id = EPISODE_ID
    mock_speaker_1.speaker_id = "SPEAKER_00"
    mock_speaker_1.name_confirmed = True

    mock_speaker_2 = MagicMock()
    mock_speaker_2.episode_id = uuid.uuid4()
    mock_speaker_2.speaker_id = "SPEAKER_00"
    mock_speaker_2.name_confirmed = False

    db = make_mock_db(scalars_result=[mock_speaker_1, mock_speaker_2])

    tool_call = ToolCall(
        id="tc2",
        name="get_speaker_profile",
        arguments={"speaker_name": "Marcus Webb"},
    )

    result = await dispatcher.dispatch(tool_call, make_session(), db)
    parsed = json.loads(result)

    assert parsed["speaker_name"] == "Marcus Webb"
    assert parsed["appears_in_episodes"] == 2


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_json():
    dispatcher = ToolDispatcher(retriever=make_mock_retriever())
    tool_call = ToolCall(id="tc3", name="nonexistent_tool", arguments={})
    result = await dispatcher.dispatch(tool_call, make_session(), make_mock_db())
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_search_applies_session_feed_scope():
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    session = make_session(scope_feed_ids=[FEED_ID])

    tool_call = ToolCall(
        id="tc4",
        name="search_knowledge_base",
        arguments={"query": "machine learning"},
    )

    await dispatcher.dispatch(tool_call, session, make_mock_db())

    _, kwargs = retriever.search.call_args
    assert kwargs["filters"].feed_ids == [FEED_ID]


@pytest.mark.asyncio
async def test_search_resolves_speaker_name_to_episode_speaker_pairs():
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    db = make_mock_db(speaker_pairs_result=[(EPISODE_ID, "SPEAKER_00")])

    tool_call = ToolCall(
        id="tc5",
        name="search_knowledge_base",
        arguments={"query": "consciousness", "speaker_name": "Marcus Webb"},
    )

    await dispatcher.dispatch(tool_call, make_session(), db)

    _, kwargs = retriever.search.call_args
    assert kwargs["filters"].speaker_pairs == [(EPISODE_ID, "SPEAKER_00")]


@pytest.mark.asyncio
async def test_search_resolves_speaker_name_across_multiple_episodes():
    """Regression test: diarization assigns speaker_id labels independently
    per episode, so the same display name can map to a different speaker_id
    in each one. The filter must carry every pair, not just the first match —
    that's the bug this fix addresses."""
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    other_episode_id = uuid.uuid4()
    db = make_mock_db(speaker_pairs_result=[
        (EPISODE_ID, "SPEAKER_00"),
        (other_episode_id, "SPEAKER_01"),
    ])

    tool_call = ToolCall(
        id="tc5b",
        name="search_knowledge_base",
        arguments={"query": "consciousness", "speaker_name": "Marcus Webb"},
    )

    await dispatcher.dispatch(tool_call, make_session(), db)

    _, kwargs = retriever.search.call_args
    assert kwargs["filters"].speaker_pairs == [
        (EPISODE_ID, "SPEAKER_00"),
        (other_episode_id, "SPEAKER_01"),
    ]


@pytest.mark.asyncio
async def test_search_proceeds_unfiltered_when_speaker_not_found():
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    db = make_mock_db(speaker_pairs_result=None)

    tool_call = ToolCall(
        id="tc6",
        name="search_knowledge_base",
        arguments={"query": "consciousness", "speaker_name": "Unknown Person"},
    )

    await dispatcher.dispatch(tool_call, make_session(), db)

    _, kwargs = retriever.search.call_args
    assert kwargs["filters"].speaker_pairs is None


@pytest.mark.asyncio
async def test_tool_exception_returns_error_json():
    retriever = MagicMock()
    retriever.search = AsyncMock(side_effect=Exception("DB exploded"))
    dispatcher = ToolDispatcher(retriever=retriever)

    tool_call = ToolCall(
        id="tc7",
        name="search_knowledge_base",
        arguments={"query": "anything"},
    )

    result = await dispatcher.dispatch(tool_call, make_session(), make_mock_db())
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_search_returns_empty_message_when_no_results():
    retriever = make_mock_retriever(results=[])
    dispatcher = ToolDispatcher(retriever=retriever)

    tool_call = ToolCall(
        id="tc8",
        name="search_knowledge_base",
        arguments={"query": "something obscure"},
    )

    result = await dispatcher.dispatch(tool_call, make_session(), make_mock_db())
    parsed = json.loads(result)
    assert parsed["results"] == []
    assert "message" in parsed


@pytest.mark.asyncio
async def test_search_populates_session_citations():
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    session = make_session()

    tool_call = ToolCall(
        id="tc1",
        name="search_knowledge_base",
        arguments={"query": "consciousness"},
    )

    await dispatcher.dispatch(tool_call, session, make_mock_db())
    assert len(session.citations) == 1
    assert session.citations[0]["display_name"] == "Marcus Webb"

def test_label_for_llm_prefixes_text_and_parent_text():
    dispatcher = ToolDispatcher(retriever=make_mock_retriever())
    chunk = make_chunk_result()

    labeled = dispatcher._label_for_llm(chunk)

    assert labeled["text"] == 'Marcus Webb: "Leaf text about consciousness."'
    assert labeled["parent_text"] == 'Marcus Webb: "Broader discussion about consciousness and AI."'
    # unrelated fields pass through untouched
    assert labeled["chunk_id"] == chunk.chunk_id
    assert labeled["similarity_score"] == 0.91


def test_label_for_llm_uses_unknown_speaker_when_display_name_missing():
    dispatcher = ToolDispatcher(retriever=make_mock_retriever())
    chunk = make_chunk_result(display_name=None)

    labeled = dispatcher._label_for_llm(chunk)

    assert labeled["text"] == 'Unknown Speaker: "Leaf text about consciousness."'


def test_label_for_llm_leaves_missing_parent_text_as_none():
    dispatcher = ToolDispatcher(retriever=make_mock_retriever())
    chunk = make_chunk_result(parent_text=None)

    labeled = dispatcher._label_for_llm(chunk)

    assert labeled["text"] == 'Marcus Webb: "Leaf text about consciousness."'
    assert labeled["parent_text"] is None


@pytest.mark.asyncio
async def test_search_labels_results_but_leaves_citations_plain():
    """Locks in the split from Piece 1: the LLM-facing 'results' get an
    inline speaker label baked into text/parent_text so the model can
    attribute quotes correctly across multiple speakers in one tool
    response. session.citations -- what the UI shows the user -- keeps
    the original, unmodified text."""
    retriever = make_mock_retriever()
    dispatcher = ToolDispatcher(retriever=retriever)
    session = make_session()

    tool_call = ToolCall(
        id="tc9",
        name="search_knowledge_base",
        arguments={"query": "consciousness"},
    )

    result = await dispatcher.dispatch(tool_call, session, make_mock_db())
    parsed = json.loads(result)

    assert parsed["results"][0]["text"] == 'Marcus Webb: "Leaf text about consciousness."'
    assert session.citations[0]["text"] == "Leaf text about consciousness."