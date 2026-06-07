# tests/unit/test_speaker_resolver.py
import json
import pytest
from src.ingestion.speaker_resolver import SpeakerResolver, InferredSpeaker
from src.llm.base import LLMResponse
from src.transcription.base import TranscriptSegment
from tests.conftest import MockLLMClient

def make_segments(texts_and_times: list[tuple[str, int, int]]) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(speaker_id="UNKNOWN", text=text, start_ms=start, end_ms=end, sequence_order=order)
        for text, start, end, order in texts_and_times
    ]

# --- happy path ---

@pytest.mark.asyncio
async def test_infers_name_and_confidence_from_intro():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("Welcome to Synthetic Minds. I'm Ada Sinclair.", 0, 5000, 0),
        ("Thanks for having me Ada.", 5200, 9000, 1),
    ])
    result = await resolver.infer(segments)
    assert result == InferredSpeaker(name="Ada Sinclair", confidence="high")


@pytest.mark.asyncio
async def test_accepts_medium_and_low_confidence():
    for confidence in ("medium", "low"):
        mock = MockLLMClient(f'{{"name": "Ada Sinclair", "confidence": "{confidence}"}}')
        resolver = SpeakerResolver(llm_client=mock)
        segments = make_segments([("I'm Ada Sinclair.", 0, 3000, 0)])
        result = await resolver.infer(segments)
        assert result is not None
        assert result.confidence == confidence


@pytest.mark.asyncio
async def test_temperature_zero_used():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("I'm Ada Sinclair.", 0, 3000, 0)])
    await resolver.infer(segments)
    assert mock.last_temperature == 0.0


@pytest.mark.asyncio
async def test_filters_to_intro_window_only():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock, window_ms=10_000)
    segments = make_segments([
        ("I'm Ada Sinclair.", 0, 3000, 0),           # inside window
        ("This is much later in the episode.", 15_000, 20_000, 1),  # outside window
    ])
    await resolver.infer(segments)
    prompt = mock.last_messages[0]["content"]
    assert "Ada Sinclair" in prompt
    assert "much later" not in prompt


# --- None cases ---

@pytest.mark.asyncio
async def test_returns_none_when_no_name_found():
    mock = MockLLMClient('{"name": "", "confidence": "low"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("Welcome to the show.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_json():
    mock = MockLLMClient("Sorry, I could not determine the speaker.")
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("Welcome to the show.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result is None

@pytest.mark.asyncio
async def test_returns_none_on_invalid_confidence_value():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "very high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("I'm Ada Sinclair.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_all_segments_outside_window():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock, window_ms=5_000)
    segments = make_segments([
        ("This segment is outside the window.", 10_000, 15_000, 10),
    ])
    result = await resolver.infer(segments)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_empty_segments():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    result = await resolver.infer([])
    assert result is None