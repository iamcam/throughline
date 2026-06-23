#!/usr/bin/env python3
"""
Experiment A: pyannote speaker-diarization-community-1 — standalone CPU benchmark.

Usage:
    uv run bench_pyannote.py myfile.wav

Env:
    HF_TOKEN  — HuggingFace read token (must have accepted community-1 model terms)
"""

import sys
import os
import time
from pathlib import Path
from pyannote.audio.pipelines.utils.hook import ProgressHook
from pyannote.audio.telemetry import set_telemetry_metrics
set_telemetry_metrics(False)

AUDIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "trimmed.wav"
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("PYANNOTE_AUTH_TOKEN")

if not HF_TOKEN:
    raise EnvironmentError("HF_TOKEN not set in environment")

if not Path(AUDIO_FILE).exists():
    raise FileNotFoundError(f"Audio file not found: {AUDIO_FILE}")

print(f"Audio file : {AUDIO_FILE}")
print(f"HF token   : {HF_TOKEN[:8]}...")
print()

# ── 1. Model load ─────────────────────────────────────────────────────────────
print("Loading pipeline...")
t0 = time.perf_counter()

from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1",
    token=HF_TOKEN,
)

# Suppress short speaker turns and short silences between turns
pipeline.instantiate({
        "segmentation": {"min_duration_off": 0.5},
        "clustering": {"threshold": 0.5},

})

load_time = time.perf_counter() - t0
print(f"  Model loaded in {load_time:.2f}s")
print()

# ── 2. Diarization ────────────────────────────────────────────────────────────
print("Running diarization...")
t1 = time.perf_counter()

with ProgressHook() as hook:
    output = pipeline(AUDIO_FILE, min_speakers=2, max_speakers=3, hook=hook)


# ── 3. Results ────────────────────────────────────────────────────────────────
import wave

with wave.open(AUDIO_FILE, "r") as wf:
    audio_duration = wf.getnframes() / wf.getframerate()

MIN_SEGMENT_S = 0.5  # ignore segments shorter than this

segments = [
    (turn, speaker)
    for turn, speaker in output.speaker_diarization
    if (turn.end - turn.start) >= MIN_SEGMENT_S
]
speakers = sorted({speaker for _, speaker in segments})


print("── Segments ──────────────────────────────────────────────────────────")
for turn, speaker in segments:
    duration = turn.end - turn.start
    print(f"  {speaker}  [{turn.start:7.2f}s → {turn.end:7.2f}s]  ({duration:.2f}s)")

print()
print("── Diarization summary ────────────────────────────────────────────────────")
infer_time = time.perf_counter() - t1
print(f"  Diarization completed in {infer_time:.2f}s")
print()
print(f"Audio duration    : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print(f"Speakers detected : {len(speakers)} — {', '.join(speakers)}")
print(f"Segments          : {len(segments)}")
print()

print("── Timing summary ────────────────────────────────────────────────────")
time_per_min = infer_time / (audio_duration / 60)
print(f"  Audio duration  : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print(f"  Model load      : {load_time:.2f}s")
print(f"  Inference       : {infer_time:.2f}s")
print(f"  Time per minute : {time_per_min:.2f}s/min (inference per min audio)")
print(f"  Total           : {load_time + infer_time:.2f}s")