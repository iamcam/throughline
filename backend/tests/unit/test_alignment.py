# tests/unit/test_alignment.py
import pytest

from src.diarization.alignment import align_segments
from src.diarization.base import DiarizationResult, SpeakerTurn
from src.transcription.base import TranscriptSegment


def make_segment(start_ms: int, end_ms: int, sequence_order: int = 0, text: str = "hello") -> TranscriptSegment:
    return TranscriptSegment(
        speaker_id="UNKNOWN",
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        sequence_order=sequence_order,
    )


def make_result(turns: list[SpeakerTurn]) -> DiarizationResult:
    speaker_count = len({t.speaker_id for t in turns})
    return DiarizationResult(turns=turns, speaker_count=speaker_count)


# --- happy path ---

def test_segment_fully_inside_one_turn_gets_that_speaker():
    segments = [make_segment(1000, 2000)]
    diarization = make_result([
        SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=5000),
    ])
    result = align_segments(segments, diarization)
    assert result[0].speaker_id == "SPEAKER_00"


def test_segment_assigned_to_turn_with_greatest_overlap():
    # Segment spans 1000-3000. SPEAKER_00 covers 0-1500 (500ms overlap),
    # SPEAKER_01 covers 1500-4000 (1500ms overlap) -- SPEAKER_01 should win.
    segments = [make_segment(1000, 3000)]
    diarization = make_result([
        SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1500),
        SpeakerTurn(speaker_id="SPEAKER_01", start_ms=1500, end_ms=4000),
    ])
    result = align_segments(segments, diarization)
    assert result[0].speaker_id == "SPEAKER_01"


def test_tie_resolves_to_earlier_turn():
    # Segment spans 0-2000. Both turns overlap exactly 1000ms.
    segments = [make_segment(0, 2000)]
    diarization = make_result([
        SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1000),
        SpeakerTurn(speaker_id="SPEAKER_01", start_ms=1000, end_ms=2000),
    ])
    result = align_segments(segments, diarization)
    assert result[0].speaker_id == "SPEAKER_00"


def test_multiple_segments_multiple_turns():
    segments = [
        make_segment(0, 2000, sequence_order=0),
        make_segment(2000, 5000, sequence_order=1),
        make_segment(5000, 8000, sequence_order=2),
    ]
    diarization = make_result([
        SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=4000),
        SpeakerTurn(speaker_id="SPEAKER_01", start_ms=4000, end_ms=9000),
    ])
    result = align_segments(segments, diarization)
    assert [s.speaker_id for s in result] == ["SPEAKER_00", "SPEAKER_00", "SPEAKER_01"]


# --- no-overlap fallback ---

def test_segment_with_no_overlapping_turn_stays_unknown():
    segments = [make_segment(10_000, 11_000)]
    diarization = make_result([
        SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1000),
    ])
    result = align_segments(segments, diarization)
    assert result[0].speaker_id == "UNKNOWN"


def test_empty_turns_leaves_all_segments_unknown():
    segments = [make_segment(0, 1000), make_segment(1000, 2000)]
    diarization = make_result([])
    result = align_segments(segments, diarization)
    assert all(s.speaker_id == "UNKNOWN" for s in result)


def test_empty_segments_returns_empty_list():
    diarization = make_result([SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1000)])
    result = align_segments([], diarization)
    assert result == []


# --- invariants ---

def test_does_not_mutate_input_segments():
    segments = [make_segment(0, 1000)]
    diarization = make_result([SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1000)])
    align_segments(segments, diarization)
    assert segments[0].speaker_id == "UNKNOWN"


def test_preserves_sequence_order_and_other_fields():
    segments = [make_segment(0, 1000, sequence_order=7, text="a specific sentence")]
    diarization = make_result([SpeakerTurn(speaker_id="SPEAKER_00", start_ms=0, end_ms=1000)])
    result = align_segments(segments, diarization)
    assert result[0].sequence_order == 7
    assert result[0].text == "a specific sentence"
    assert result[0].start_ms == 0
    assert result[0].end_ms == 1000