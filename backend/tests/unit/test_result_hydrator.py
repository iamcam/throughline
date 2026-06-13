# tests/unit/test_result_hydrator.py

import uuid
import pytest
from src.query.result_hydrator import ResultHydrator, ChunkResult
from src.storage.vector_store import RawChunkResult


# ~~~~~~ Helpers ~~~~~~

EPISODE_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()


def make_raw(
    chunk_id=None,
    episode_id=None,
    speaker_id="SPEAKER_00",
    start_ms=3_822_000,
    end_ms=3_830_000,
    similarity_score=0.91,
    text="The interesting thing about neural networks is...",
    parent_text="A broader discussion of neural networks.",
) -> RawChunkResult:
    return RawChunkResult(
        chunk_id=chunk_id or CHUNK_ID,
        text=text,
        parent_text=parent_text,
        speaker_id=speaker_id,
        episode_id=episode_id or EPISODE_ID,
        start_ms=start_ms,
        end_ms=end_ms,
        similarity_score=similarity_score,
    )

class MockRow:
    """Minimal stand-in for a SQLAlchemy row with named attribute access."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockResult:
    """Wraps a list of MockRow objects. Supports iteration (fetchall pattern)."""
    def __init__(self, rows: list):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class MockAsyncSession:
    """
    Returns a sequence of MockResults, one per execute() call.
    Responses are consumed in order - first call gets responses[0],
    second call gets responses[1], and so on.
    """
    def __init__(self, responses: list[MockResult]):
        self._responses = iter(responses)

    async def execute(self, stmt):
        return next(self._responses)


# ~~~~~~ Tests ~~~~~~

@pytest.mark.asyncio
async def test_hydrator_resolves_speaker_id_to_display_name():
    raw = [make_raw(speaker_id="SPEAKER_00")]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Synthetic Minds Ep. 12", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].display_name == "Ada Sinclair"


@pytest.mark.asyncio
async def test_hydrator_resolves_episode_title():
    raw = [make_raw()]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Synthetic Minds Ep. 12", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].episode_title == "Synthetic Minds Ep. 12"

@pytest.mark.asyncio
async def test_hydrator_resolves_audio_url():
    EPISODE_ID_2 = uuid.uuid4()
    raw = [
        make_raw(episode_id=EPISODE_ID),
        make_raw(episode_id=EPISODE_ID_2),
    ]
    db = MockAsyncSession([
        MockResult([
            MockRow(id=EPISODE_ID, title="Synthetic Minds Ep. 12", audio_url="https://domain.ext/afile.mp3"),
            MockRow(id=EPISODE_ID_2, title="Synthetic Minds Ep. 13", audio_url="https://example.com/other-file.mp3"),
        ]),
        MockResult([
            MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair"),
            MockRow(episode_id=EPISODE_ID_2, speaker_id="SPEAKER_00", display_name="Ada Sinclair"),
        ]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].to_dict()["audio_url"] == "https://domain.ext/afile.mp3"
    assert results[1].to_dict()["audio_url"] == "https://example.com/other-file.mp3"


@pytest.mark.asyncio
async def test_hydrator_formats_timestamp_correctly():
    """3_822_000ms = 63m 42s = 1:03:42"""
    raw = [make_raw(start_ms=3_822_000)]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Ep. 1", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].timestamp_display == "1:03:42"


@pytest.mark.asyncio
async def test_hydrator_formats_sub_hour_timestamp():
    """125_000ms = 2m 5s = 2:05"""
    raw = [make_raw(start_ms=125_000)]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Ep. 1", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].timestamp_display == "2:05"


@pytest.mark.asyncio
async def test_hydrator_returns_none_display_name_when_missing():
    """UNKNOWN speaker with no display_name in episode_speakers → None, not a string."""
    raw = [make_raw(speaker_id="UNKNOWN")]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Ep. 1", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="UNKNOWN", display_name=None, audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].display_name is None


@pytest.mark.asyncio
async def test_hydrator_batches_lookups_for_multiple_results():
    """
    Three results from two episodes - should still only call execute() twice,
    not once per result row.
    """
    ep_a = uuid.uuid4()
    ep_b = uuid.uuid4()
    raw = [
        make_raw(episode_id=ep_a, speaker_id="SPEAKER_00"),
        make_raw(episode_id=ep_a, speaker_id="SPEAKER_00"),
        make_raw(episode_id=ep_b, speaker_id="SPEAKER_00"),
    ]

    execute_calls = 0

    class CountingSession:
        async def execute(self, stmt):
            nonlocal execute_calls
            execute_calls += 1
            if execute_calls == 1:
                return MockResult([
                    MockRow(id=ep_a, title="Show A", audio_url=None),
                    MockRow(id=ep_b, title="Show B", audio_url=None),
                ])
            return MockResult([
                MockRow(episode_id=ep_a, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None),
                MockRow(episode_id=ep_b, speaker_id="SPEAKER_00", display_name="Renn Okafor", audio_url=None),
            ])

    results = await ResultHydrator().hydrate(raw, CountingSession())
    assert execute_calls == 2


@pytest.mark.asyncio
async def test_hydrator_returns_correct_display_name_per_episode():
    """Same speaker_id in two different episodes maps to different display names."""
    ep_a = uuid.uuid4()
    ep_b = uuid.uuid4()
    raw = [
        make_raw(episode_id=ep_a, speaker_id="SPEAKER_00"),
        make_raw(episode_id=ep_b, speaker_id="SPEAKER_00"),
    ]
    db = MockAsyncSession([
        MockResult([
            MockRow(id=ep_a, title="Show A", audio_url=None),
            MockRow(id=ep_b, title="Show B", audio_url=None),
        ]),
        MockResult([
            MockRow(episode_id=ep_a, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None),
            MockRow(episode_id=ep_b, speaker_id="SPEAKER_00", display_name="Renn Okafor", audio_url=None),
        ]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].display_name == "Ada Sinclair"
    assert results[1].display_name == "Renn Okafor"


@pytest.mark.asyncio
async def test_hydrator_returns_empty_list_for_empty_input():
    db = MockAsyncSession([])
    results = await ResultHydrator().hydrate([], db)
    assert results == []


@pytest.mark.asyncio
async def test_chunk_id_and_episode_id_are_strings_in_output():
    """UUIDs from RawChunkResult should be stringified in ChunkResult."""
    raw = [make_raw()]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Ep. 1", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert isinstance(results[0].chunk_id, str)
    assert isinstance(results[0].episode_id, str)


@pytest.mark.asyncio
async def test_similarity_score_rounded_in_to_dict():
    raw = [make_raw(similarity_score=0.912345678)]
    db = MockAsyncSession([
        MockResult([MockRow(id=EPISODE_ID, title="Ep. 1", audio_url=None)]),
        MockResult([MockRow(episode_id=EPISODE_ID, speaker_id="SPEAKER_00", display_name="Ada Sinclair", audio_url=None)]),
    ])
    results = await ResultHydrator().hydrate(raw, db)
    assert results[0].to_dict()["similarity_score"] == 0.9123

