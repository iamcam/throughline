#!/usr/bin/env python3
"""
Experiment D: mlx-qwen3-asr transcription-only benchmark — Apple Silicon.

Usage:
    uv run bench_mlx_qwen3_asr_only.py myfile.wav
"""

import time
import sys
import wave
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

AUDIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "trimmed.wav"

# MODEL = "mlx-community/Qwen3-ASR-0.6B-bf16"  # or Qwen3-ASR-1.7B-8bit for higher accuracy
MODEL = "mlx-community/Qwen3-ASR-1.7B-8bit"

if not Path(AUDIO_FILE).exists():
    raise FileNotFoundError(f"Audio file not found: {AUDIO_FILE}")

with wave.open(AUDIO_FILE, "r") as wf:
    audio_duration = wf.getnframes() / wf.getframerate()

print(f"Audio file : {AUDIO_FILE}")
print(f"Model      : {MODEL}")
print(f"Duration   : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print()

# ── 1. Transcription (model load is lazy — included in inference time) ────────
print("Running transcription (includes model load on first run)...")
t0 = time.perf_counter()

from mlx_qwen3_asr import transcribe

result = transcribe(
    AUDIO_FILE,
    model=MODEL,
    language="en",
    return_timestamps=True,
    verbose=False,
)

asr_time = time.perf_counter() - t0
print(f"  Completed in {asr_time:.2f}s")
print()

# ── 2. Results ────────────────────────────────────────────────────────────────
segments = result.segments or []

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
print(f"  Inference       : {asr_time:.2f}s (cold start — includes model load)")
print(f"  Time per minute : {time_per_min:.2f}s/min (inference per min audio)")