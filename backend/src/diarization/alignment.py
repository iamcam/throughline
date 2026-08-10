# src/diarization/alignment.py
import logging
from dataclasses import replace

from src.diarization.base import DiarizationResult
from src.transcription.base import TranscriptSegment

logger = logging.getLogger(__name__)


def align_segments(
    segments: list[TranscriptSegment],
    diarization: DiarizationResult,
) -> list[TranscriptSegment]:
    """
    Assigns a speaker_id to each transcript segment based on which
    diarization turn it overlaps with most.

    Segments and turns come from two independent timelines (Whisper and
    Senko), so this is a best-effort match, not an exact one. A segment
    with no overlapping turn at all is left as UNKNOWN rather than guessed.

    Returns a new list -- does not mutate the input segments.
    """
    aligned = []
    unresolved_count = 0

    for segment in segments:
        best_turn = None
        best_overlap_ms = 0

        for turn in diarization.turns:
            overlap_ms = min(segment.end_ms, turn.end_ms) - max(segment.start_ms, turn.start_ms)
            if overlap_ms > best_overlap_ms:
                best_overlap_ms = overlap_ms
                best_turn = turn

        if best_turn is None:
            unresolved_count += 1
            aligned.append(segment)
        else:
            aligned.append(replace(segment, speaker_id=best_turn.speaker_id))

    if unresolved_count:
        logger.warning(
            "Alignment: %d/%d segments had no overlapping diarization turn, left as UNKNOWN",
            unresolved_count, len(segments),
        )

    return aligned