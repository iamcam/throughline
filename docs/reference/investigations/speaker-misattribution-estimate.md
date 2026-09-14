# Investigation — Speaker Misattribution from Segment-Granularity Alignment

> Referenced from `FUTURE_SCOPE.md` §2.8f. Not a phase — no code has been changed or shipped for this.
> Copy the script below into `experiments/speaker_misattribution_estimate.py` to run it; it isn't part of the app itself.

## Why this exists

Phase 20.1 fixed a crash caused by Whisper occasionally dropping sentence-ending punctuation on long runs of speech, which had let a transcript segment grow unbounded. The fix (pause-rescue, then hard-cut) stops the crash, but a long unpunctuated run is also exactly the kind of segment most likely to span a genuine speaker change — and today's alignment (`src/diarization/alignment.py`, see §2.8b in `FUTURE_SCOPE.md`) assigns a whole segment's `speaker_id` to whichever diarization turn overlaps it most. Any speaker change inside one of these longer segments is silently misattributed to the dominant speaker rather than split.

§2.8b already named the bar for revisiting word-level alignment: "worth revisiting only if segment-level misattribution proves to be a real, frequently-observed problem in practice — not before." This script exists to answer that question with a number, before committing to the larger pipeline-reordering work (diarizing before/alongside transcription instead of after it) that a real fix would require.

## What it measures

For the segments `LocalTranscriptionService` actually produces (via the real `_build_segments_from_words`), how much word-time inside each segment belongs to a speaker *other than* the segment's dominant speaker — i.e. speech that gets silently misattributed today because alignment can only assign one `speaker_id` per segment. It reuses the project's real segmentation and diarization code rather than reimplementing that logic, so the numbers reflect the actual pipeline, not an approximation of it.

**Caveats — this is a rough estimate, not ground truth:**
- Word-to-turn assignment uses each word's timestamp midpoint against Senko's turn boundaries. Both Whisper's word timestamps and Senko's turn boundaries carry their own uncertainty, so treat this as directional, not exact.
- A word whose midpoint falls in a gap between diarization turns (silence, or Senko simply not covering that instant) is excluded from the totals entirely, rather than guessed.

## Done when

The script has been run against a handful of real episodes (multi-speaker interview/conversation shows are the most informative case), giving a concrete answer — either closing this out as negligible, or providing the evidence to justify the diarize-before-transcribe reordering described in `FUTURE_SCOPE.md` §2.8f.

## Script

```python
"""
FUTURE_SCOPE 2.8f investigation: estimate how much speech time would move
to a different speaker_id if segments respected word-level speaker turns,
instead of today's segment-granularity alignment (a whole segment gets
whichever diarization turn overlaps it most -- src/diarization/alignment.py).

This does NOT change segmentation or alignment. It measures: for the
segments LocalTranscriptionService actually produces, how much word-time
inside each segment belongs to a speaker OTHER than the segment's dominant
speaker -- i.e. speech that gets silently misattributed today because
alignment can only assign one speaker_id per segment.

Caveats (this is a rough estimate, not ground truth):
- Word-to-turn assignment here uses each word's timestamp midpoint against
  Senko's turn boundaries -- both Whisper's word timestamps and Senko's
  turn boundaries carry their own uncertainty, so treat this as directional,
  not exact.
- A word whose midpoint falls in a gap between diarization turns (silence,
  or Senko simply not covering that instant) is excluded from the totals
  entirely, rather than guessed.

Run from the project root so `src` is importable, e.g.:
    uv run python experiments/speaker_misattribution_estimate.py episode.mp3
    uv run python experiments/speaker_misattribution_estimate.py "audio/*.mp3"
"""

import argparse
import asyncio
import glob
from pathlib import Path

import mlx_whisper

from src.config import get_settings
from src.diarization.local import LocalDiarizationService
from src.transcription.local import _build_segments_from_words, _default_tokenizer


def resolve_paths(patterns: list[str]) -> list[str]:
    resolved: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            resolved.extend(matches)
        elif Path(pattern).is_file():
            resolved.append(pattern)
        else:
            print(f"Warning: no files matched '{pattern}', skipping")
    seen = set()
    deduped = []
    for path in resolved:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def get_words(audio_path: str, model: str) -> list[tuple[float, float, str]]:
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=f"mlx-community/whisper-{model}-mlx",
        word_timestamps=True,
    )
    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            words.append((word["start"], word["end"], word["word"].strip()))
    return words


def assign_word_speakers(words, turns) -> list[str | None]:
    """One speaker_id (or None if the word's midpoint falls in a gap) per word."""
    assignments = []
    for start, end, _text in words:
        mid_ms = int((start + end) / 2 * 1000)
        speaker = None
        for turn in turns:
            if turn.start_ms <= mid_ms < turn.end_ms:
                speaker = turn.speaker_id
                break
        assignments.append(speaker)
    return assignments


def analyze_file(audio_path: str, settings, diarization_service) -> dict:
    words = get_words(audio_path, settings.whisper_model)
    segments = _build_segments_from_words(
        words,
        settings.transcription_min_segment_words,
        settings.transcription_max_segment_tokens,
        settings.transcription_pause_threshold_s,
        tokenizer=_default_tokenizer,
    )

    diarization = asyncio.run(diarization_service.diarize(audio_path))
    speaker_by_word = assign_word_speakers(words, diarization.turns)

    total_speech_s = 0.0
    total_misattributed_s = 0.0
    multi_speaker_segments = 0

    for segment in segments:
        # words belonging to this segment, by timestamp midpoint
        seg_word_indices = [
            i for i, (start, end, _) in enumerate(words)
            if segment.start_ms <= int((start + end) / 2 * 1000) < segment.end_ms
        ]

        time_by_speaker: dict[str, float] = {}
        for i in seg_word_indices:
            speaker = speaker_by_word[i]
            if speaker is None:
                continue
            start, end, _ = words[i]
            time_by_speaker[speaker] = time_by_speaker.get(speaker, 0.0) + (end - start)

        if not time_by_speaker:
            continue

        segment_total = sum(time_by_speaker.values())
        dominant_time = max(time_by_speaker.values())
        misattributed = segment_total - dominant_time

        total_speech_s += segment_total
        total_misattributed_s += misattributed
        if len(time_by_speaker) > 1:
            multi_speaker_segments += 1

    return {
        "segment_count": len(segments),
        "multi_speaker_segments": multi_speaker_segments,
        "total_speech_s": total_speech_s,
        "misattributed_s": total_misattributed_s,
    }


def report(stats: dict, label: str) -> None:
    print(f"\n=== {label} ===")
    pct = (stats["misattributed_s"] / stats["total_speech_s"] * 100) if stats["total_speech_s"] else 0.0
    print(f"Segments:                {stats['segment_count']}")
    print(f"Multi-speaker segments:  {stats['multi_speaker_segments']}")
    print(f"Total assigned speech:   {stats['total_speech_s']:.1f}s")
    print(f"Misattributed speech:    {stats['misattributed_s']:.1f}s ({pct:.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_paths", nargs="+")
    args = parser.parse_args()

    paths = resolve_paths(args.audio_paths)
    if not paths:
        print("No matching files found.")
        return

    settings = get_settings()
    diarization_service = LocalDiarizationService(device="auto")

    combined = {"segment_count": 0, "multi_speaker_segments": 0, "total_speech_s": 0.0, "misattributed_s": 0.0}
    for path in paths:
        stats = analyze_file(path, settings, diarization_service)
        report(stats, label=path)
        for key in combined:
            combined[key] += stats[key]

    if len(paths) > 1:
        report(combined, label=f"COMBINED ({len(paths)} files)")


if __name__ == "__main__":
    main()
```
