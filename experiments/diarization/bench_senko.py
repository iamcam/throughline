#!/usr/bin/env python3
"""
Experiment G: Senko diarization benchmark — Apple Silicon / CPU.
https://github.com/narcotic-sh/senko

Usage:
    uv run bench_senko.py [audio_file]
"""

import sys
import time
import wave
import warnings
from pathlib import Path

import os
import psutil

warnings.filterwarnings("ignore")

def get_rss_mb():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


AUDIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "trimmed.wav"
MIN_SEGMENT_S = 0.5

if not Path(AUDIO_FILE).exists():
    raise FileNotFoundError(f"Audio file not found: {AUDIO_FILE}")

with wave.open(AUDIO_FILE, "r") as wf:
    audio_duration = wf.getnframes() / wf.getframerate()

print(f"Audio file : {AUDIO_FILE}")
print(f"Duration   : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print()

rss_baseline = get_rss_mb()

# ── 1. Model load ─────────────────────────────────────────────────────────────

print("Loading Senko diarizer...")
t0 = time.perf_counter()

import senko
diarizer = senko.Diarizer(device='auto', warmup=True)

load_time = time.perf_counter() - t0
print(f"  Loaded in {load_time:.2f}s")
print()

rss_after_load = get_rss_mb()

# ── 2. Diarization ────────────────────────────────────────────────────────────
print("Running diarization...")
t1 = time.perf_counter()

result = diarizer.diarize(AUDIO_FILE)

infer_time = time.perf_counter() - t1
print(f"  Completed in {infer_time:.2f}s")
print()

rss_after_infer = get_rss_mb()

# ── 3. Results ────────────────────────────────────────────────────────────────
segments = [
    s for s in result["merged_segments"]
    if (s["end"] - s["start"]) >= MIN_SEGMENT_S
]
speakers = sorted({s["speaker"] for s in segments})

print("── Segments ──────────────────────────────────────────────────────────")
for s in segments:
    duration = s["end"] - s["start"]
    print(f"  {s['speaker']}  [{s['start']:7.2f}s → {s['end']:7.2f}s]  ({duration:.2f}s)")


print()
print("── Pipeline breakdown ────────────────────────────────────────────────")
stats = result["timing_stats"]
for stage, t in stats.items():
    if stage != "total_time":
        print(f"  {stage:<20} {t:.3f}s")
print(f"  {'total_time':<20} {stats['total_time']:.3f}s")

print()
print("── Diarization summary ───────────────────────────────────────────────")
print(f"  Speakers detected (raw)    : {result['raw_speakers_detected']}")
print(f"  Speakers detected (merged) : {result['merged_speakers_detected']}")
print(f"  Segments (filtered)        : {len(segments)}")
print(f"  Speakers                   : {', '.join(speakers)}")

print()
print("── Timing summary ────────────────────────────────────────────────────")
time_per_min = infer_time / (audio_duration / 60)
print(f"  Audio duration  : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print(f"  Model load      : {load_time:.2f}s")
print(f"  Inference       : {infer_time:.2f}s")
print(f"  Time per minute : {time_per_min:.2f}s/min")
print(f"  Total           : {load_time + infer_time:.2f}s")

print()
print("── Memory usage ──────────────────────────────────────────────────────")
print(f"  Baseline (pre-load)  : {rss_baseline:.1f} MB")
print(f"  After model load     : {rss_after_load:.1f} MB  (+{rss_after_load - rss_baseline:.1f} MB)")
print(f"  After inference      : {rss_after_infer:.1f} MB  (+{rss_after_infer - rss_after_load:.1f} MB)")
print(f"  Peak delta           : {rss_after_infer - rss_baseline:.1f} MB")

import gc
gc.collect()
rss_after_gc = get_rss_mb()
print(f"  After gc.collect()   : {rss_after_gc:.1f} MB  ({rss_after_gc - rss_after_infer:+.1f} MB)")