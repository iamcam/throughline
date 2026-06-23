#!/usr/bin/env python3
"""
Experiment E: Sortformer MLX diarization benchmark — Apple Silicon.
Model: mlx-community/diar_sortformer_4spk-v1-fp16 (NVIDIA NeMo via mlx-audio)

Usage:
    uv run bench_sortformer.py myfile.wav
"""

import sys
import time
import wave
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

AUDIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "trimmed.wav"
MODEL = "mlx-community/diar_streaming_sortformer_4spk-v2.1-fp16"

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

from mlx_audio.vad import load
model = load(MODEL)

load_time = time.perf_counter() - t0
print(f"  Model loaded in {load_time:.2f}s")
print()

# ── 2. Diarization ────────────────────────────────────────────────────────────
print("Running diarization...")
t1 = time.perf_counter()

result = model.generate(
    AUDIO_FILE,
    threshold=0.5,
    min_duration=0.5,   # drop segments shorter than 0.5s
    merge_gap=0.3,      # merge segments with gaps smaller than 0.3s
    verbose=True,
)

infer_time = time.perf_counter() - t1
print(f"  Completed in {infer_time:.2f}s")
print()

# ── 3. Results ────────────────────────────────────────────────────────────────
MIN_SEGMENT_S = 0.5

segments = [s for s in result.segments if (s.end - s.start) >= MIN_SEGMENT_S]
speakers = sorted({s.speaker for s in segments})

print("── Segments ──────────────────────────────────────────────────────────")
for s in segments:
    duration = s.end - s.start
    print(f"  {s.speaker}  [{s.start:7.2f}s → {s.end:7.2f}s]  ({duration:.2f}s)")

print()
print("── Diarization summary ───────────────────────────────────────────────")
print(f"  Speakers detected : {len(speakers)} — {', '.join(str(s) for s in speakers)}")
print(f"  Segments          : {len(segments)}")
print()

print("── Timing summary ────────────────────────────────────────────────────")
time_per_min = infer_time / (audio_duration / 60)
print(f"  Audio duration  : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
print(f"  Model load      : {load_time:.2f}s")
print(f"  Inference       : {infer_time:.2f}s")
print(f"  Time per minute : {time_per_min:.2f}s/min (inference per min audio)")
print(f"  Total           : {load_time + infer_time:.2f}s")