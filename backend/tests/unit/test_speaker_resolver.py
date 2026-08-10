# tests/unit/test_speaker_resolver.py
import pytest
from src.ingestion.speaker_resolver import SpeakerResolver, InferredSpeaker
from src.transcription.base import TranscriptSegment
from tests.conftest import MockLLMClient
from src.llm.base import LLMResponse

def make_segments(entries: list[tuple[str, str, int, int, int]]) -> list[TranscriptSegment]:
    """
    entries: (speaker_id, text, start_ms, end_ms, sequence_order)
    """
    return [
        TranscriptSegment(speaker_id=sid, text=text, start_ms=start, end_ms=end, sequence_order=order)
        for sid, text, start, end, order in entries
    ]


# --- happy path ---

@pytest.mark.asyncio
async def test_infers_name_and_confidence_for_single_speaker():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("SPEAKER_00", "Welcome to Synthetic Minds. I'm Ada Sinclair.", 0, 5000, 0),
    ])
    result = await resolver.infer(segments)
    assert result == {"SPEAKER_00": InferredSpeaker(name="Ada Sinclair", confidence="high")}


@pytest.mark.asyncio
async def test_infers_each_speaker_independently():
    # Different responses per call -- MockLLMClient.responses is consumed in order,
    # and infer() processes speaker_ids sorted alphabetically, so SPEAKER_00 first.
    mock = MockLLMClient(responses=[
        LLMResponse(
            content='{"name": "Ada Sinclair", "confidence": "high"}', tool_calls=[]
        ),
        LLMResponse(
            content='{"name": "Marcus Webb", "confidence": "medium"}', tool_calls=[]
        )
    ])
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("SPEAKER_00", "I'm Ada Sinclair, welcome to the show.", 0, 3000, 0),
        ("SPEAKER_01", "Thanks for having me, I'm Marcus Webb.", 3200, 6000, 1),
    ])
    result = await resolver.infer(segments)
    assert result == {
        "SPEAKER_00": InferredSpeaker(name="Ada Sinclair", confidence="high"),
        "SPEAKER_01": InferredSpeaker(name="Marcus Webb", confidence="medium"),
    }


@pytest.mark.asyncio
async def test_temperature_zero_used():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("SPEAKER_00", "I'm Ada Sinclair.", 0, 3000, 0)])
    await resolver.infer(segments)
    assert mock.last_temperature == 0.0


# --- prompt construction ---

@pytest.mark.asyncio
async def test_prompt_labels_lines_by_speaker():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("SPEAKER_00", "Welcome to the show, my guest today is Marcus.", 0, 3000, 0),
        ("SPEAKER_01", "Thanks for having me.", 3200, 5000, 1),
    ])
    await resolver.infer(segments)
    prompt = mock.last_messages[0]["content"]
    assert 'SPEAKER_00: "Welcome to the show, my guest today is Marcus."' in prompt
    assert 'SPEAKER_01: "Thanks for having me."' in prompt


@pytest.mark.asyncio
async def test_prompt_names_the_target_speaker():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("SPEAKER_00", "Hello.", 0, 1000, 0)])
    await resolver.infer(segments)
    assert "SPEAKER_00" in mock.last_messages[0]["content"]


@pytest.mark.asyncio
async def test_window_scoped_to_each_speakers_own_first_utterance():
    # SPEAKER_01 doesn't start talking until 20_000ms. With window_ms=10_000
    # and padding_ms=0, SPEAKER_01's window is [20_000, 30_000] -- it should
    # NOT see SPEAKER_00's much earlier line.
    mock = MockLLMClient('{"name": "Marcus Webb", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock, window_ms=10_000, padding_ms=0)
    segments = make_segments([
        ("SPEAKER_00", "This is early unrelated chatter.", 0, 3000, 0),
        ("SPEAKER_01", "I'm Marcus Webb.", 20_000, 23_000, 1),
    ])
    await resolver.infer(segments)
    prompt = mock.last_messages[-1]["content"]
    assert "Marcus Webb" in prompt
    assert "unrelated chatter" not in prompt


@pytest.mark.asyncio
async def test_padding_pulls_in_preceding_introduction():
    # SPEAKER_01 first speaks at 20_000ms. With padding_ms=5000, the window
    # starts at 15_000ms -- early enough to catch SPEAKER_00 introducing them at 16_000ms.
    mock = MockLLMClient('{"name": "Marcus Webb", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock, window_ms=10_000, padding_ms=5_000)
    segments = make_segments([
        ("SPEAKER_00", "My guest today is Marcus Webb.", 16_000, 19_000, 0),
        ("SPEAKER_01", "Thanks for having me.", 20_000, 23_000, 1),
    ])
    await resolver.infer(segments)
    prompt = mock.last_messages[-1]["content"]
    assert "My guest today is Marcus Webb" in prompt


# --- per-speaker None cases ---

@pytest.mark.asyncio
async def test_speaker_maps_to_none_when_no_name_found():
    mock = MockLLMClient('{"name": "", "confidence": "low"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("SPEAKER_00", "Welcome to the show.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result == {"SPEAKER_00": None}


@pytest.mark.asyncio
async def test_speaker_maps_to_none_on_malformed_json():
    mock = MockLLMClient("Sorry, I could not determine the speaker.")
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("SPEAKER_00", "Welcome to the show.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result == {"SPEAKER_00": None}


@pytest.mark.asyncio
async def test_speaker_maps_to_none_on_invalid_confidence_value():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "very high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("SPEAKER_00", "I'm Ada Sinclair.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result == {"SPEAKER_00": None}


@pytest.mark.asyncio
async def test_one_speaker_none_others_resolved():
    mock = MockLLMClient(responses=[
        __import__("src.llm.base", fromlist=["LLMResponse"]).LLMResponse(
            content='{"name": "Ada Sinclair", "confidence": "high"}', tool_calls=[]
        ),
        __import__("src.llm.base", fromlist=["LLMResponse"]).LLMResponse(
            content='{"name": "", "confidence": "low"}', tool_calls=[]
        ),
    ])
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("SPEAKER_00", "I'm Ada Sinclair.", 0, 3000, 0),
        ("SPEAKER_01", "Hmm, hard to say who I am.", 3200, 6000, 1),
    ])
    result = await resolver.infer(segments)
    assert result == {
        "SPEAKER_00": InferredSpeaker(name="Ada Sinclair", confidence="high"),
        "SPEAKER_01": None,
    }


# --- edge cases ---

@pytest.mark.asyncio
async def test_unknown_speaker_id_never_gets_inference_call():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("SPEAKER_00", "I'm Ada Sinclair.", 0, 3000, 0),
        ("UNKNOWN", "Some unresolved crosstalk.", 3200, 4000, 1),
    ])
    result = await resolver.infer(segments)
    assert set(result.keys()) == {"SPEAKER_00"}


@pytest.mark.asyncio
async def test_unknown_segments_still_appear_in_context_window():
    # UNKNOWN segments aren't inferred themselves, but they're real dialogue
    # that might carry identifying info for a speaker whose window includes them.
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([
        ("UNKNOWN", "Someone talks over the intro here.", 0, 2000, 0),
        ("SPEAKER_00", "I'm Ada Sinclair.", 2200, 5000, 1),
    ])
    await resolver.infer(segments)
    prompt = mock.last_messages[0]["content"]
    assert "talks over the intro" in prompt


@pytest.mark.asyncio
async def test_returns_empty_dict_on_empty_segments():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    result = await resolver.infer([])
    assert result == {}


@pytest.mark.asyncio
async def test_returns_empty_dict_when_only_unknown_segments():
    mock = MockLLMClient('{"name": "Ada Sinclair", "confidence": "high"}')
    resolver = SpeakerResolver(llm_client=mock)
    segments = make_segments([("UNKNOWN", "No diarized speaker here.", 0, 3000, 0)])
    result = await resolver.infer(segments)
    assert result == {}