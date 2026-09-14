"""
Transcribe one or more podcast episodes with mlx_whisper and report the
distribution of pauses between consecutive words (word_end[i] to
word_start[i+1]), per file and combined.

Purpose: get real numbers to sanity-check TRANSCRIPTION_PAUSE_THRESHOLD_S
(currently 1.2s) against actual speech cadence, rather than guessing.

Usage:
    python experiments/word_pause_stats.py episode1.mp3 episode2.mp3
    python experiments/word_pause_stats.py "downloads/*.mp3" --model medium
    python experiments/word_pause_stats.py ep1.mp3 "more_eps/*.mp3" ep3.mp3
"""

import argparse
import glob
import statistics
from pathlib import Path

import mlx_whisper


def resolve_paths(patterns: list[str]) -> list[str]:
    """Expand each argument as a glob pattern. A plain path with no glob
    characters that doesn't match anything is still checked directly, so a
    literal filename isn't silently dropped if it happens to contain no
    matches (e.g. it was already shell-expanded by the caller's own shell)."""
    resolved: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            resolved.extend(matches)
        elif Path(pattern).is_file():
            resolved.append(pattern)
        else:
            print(f"Warning: no files matched '{pattern}', skipping")

    # de-dupe while preserving order, in case overlapping globs were passed
    seen = set()
    deduped = []
    for path in resolved:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def get_word_pauses(audio_path: str, model: str) -> list[float]:
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=f"mlx-community/whisper-{model}-mlx",
        word_timestamps=True,
    )

    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            words.append((word["start"], word["end"]))

    pauses = []
    for (_, prev_end), (next_start, _) in zip(words, words[1:]):
        gap = next_start - prev_end
        if gap > 0:
            pauses.append(gap)

    return pauses


def report(pauses: list[float], label: str) -> None:
    print(f"\n=== {label} ===")
    if not pauses:
        print("No pauses found.")
        return

    sorted_pauses = sorted(pauses)
    print(f"Word-gap count: {len(pauses)}")
    print(f"Mean pause:     {statistics.mean(pauses):.3f}s")
    print(f"Median pause:   {statistics.median(pauses):.3f}s")
    print(f"Stdev:          {statistics.pstdev(pauses):.3f}s")
    print(f"Min / Max:      {sorted_pauses[0]:.3f}s / {sorted_pauses[-1]:.3f}s")

    for p in (50, 75, 90, 95, 99):
        idx = min(int(len(sorted_pauses) * p / 100), len(sorted_pauses) - 1)
        print(f"p{p}:            {sorted_pauses[idx]:.3f}s")

    print("\nDistribution (0.1s buckets, capped at 3s):")
    bucket_width = 0.1
    max_bucket = 3.0
    buckets: dict[float, int] = {}
    for p in pauses:
        bucket = min(round(p / bucket_width) * bucket_width, max_bucket)
        buckets[bucket] = buckets.get(bucket, 0) + 1

    for bucket in sorted(buckets):
        count = buckets[bucket]
        bar = "#" * max(1, count * 40 // max(buckets.values()))
        label_str = f">{max_bucket}s" if bucket == max_bucket else f"{bucket:.1f}s"
        print(f"  {label_str:>7}: {bar} ({count})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "audio_paths",
        nargs="+",
        help="Audio file paths and/or glob patterns (quote globs to avoid shell expansion, e.g. \"downloads/*.mp3\")",
    )
    parser.add_argument("--model", default="medium", help="Whisper model size")
    args = parser.parse_args()

    paths = resolve_paths(args.audio_paths)
    if not paths:
        print("No matching files found.")
        return

    print(f"Transcribing {len(paths)} file(s) with model={args.model}:")
    for p in paths:
        print(f"  {p}")

    all_pauses: list[float] = []
    for path in paths:
        pauses = get_word_pauses(path, args.model)
        report(pauses, label=path)
        all_pauses.extend(pauses)

    if len(paths) > 1:
        report(all_pauses, label=f"COMBINED ({len(paths)} files)")


if __name__ == "__main__":
    main()