#!/usr/bin/env python3
"""
Experiment C: mlx-whisper transcription-only benchmark — Apple Silicon.

Usage:
    uv run bench_mlx_whisper.py myfile.wav
"""

import time
import sys
import wave
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


AUDIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "trimmed.wav"

MODEL = "mlx-community/whisper-large-v3-turbo"  # good quality/speed balance on Apple Silicon
# MODEL = "mlx-community/whisper-tiny"  # good quality/speed balance on Apple Silicon
# MODEL = "mlx-community/whisper-medium"

if not Path(AUDIO_FILE).exists():
    raise FileNotFoundError(f"Audio file not found: {AUDIO_FILE}")

with wave.open(AUDIO_FILE, "r") as wf:
    audio_duration = wf.getnframes() / wf.getframerate()

print(f"Audio file : {AUDIO_FILE}")
print(f"Model      : {MODEL}")
print(f"Duration   : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print()

# ── 1. Model load ─────────────────────────────────────────────────────────────
print("Loading model...")
t0 = time.perf_counter()

import mlx_whisper

load_time = time.perf_counter() - t0
print(f"  Import done in {load_time:.2f}s")
print()

# ── 2. Transcription ──────────────────────────────────────────────────────────
print("Running transcription...")
t1 = time.perf_counter()

result = mlx_whisper.transcribe(
    AUDIO_FILE,
    path_or_hf_repo=MODEL,
    language="en",
    word_timestamps=True,
    verbose=False,
)

asr_time = time.perf_counter() - t1
print(f"  Completed in {asr_time:.2f}s")
print()

# ── 3. Results ────────────────────────────────────────────────────────────────
segments = result.get("segments", [])

print("── Transcript segments ───────────────────────────────────────────────")
for seg in segments:
    start = seg["start"]
    end = seg["end"]
    text = seg["text"].strip()
    print(f"  [{start:7.2f}s → {end:7.2f}s]  {text}")

print()
print("── Timing summary ────────────────────────────────────────────────────")
time_per_min = asr_time / (audio_duration / 60)
print(f"  Audio duration  : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print(f"  Model load      : {load_time:.2f}s")
print(f"  Inference       : {asr_time:.2f}s")
print(f"  Time per minute : {time_per_min:.2f}s/min (inference per min audio)")
print(f"  Total           : {load_time + asr_time:.2f}s")