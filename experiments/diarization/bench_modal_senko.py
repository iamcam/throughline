#!/usr/bin/env python3
"""
Experiment G: Senko diarization benchmark — Modal CUDA GPU.
https://github.com/narcotic-sh/senko

Install recipe mirrors backend-worker/app.py's image build (CUDA-enabled
Senko via the `[nvidia]` extra, torchcodec pinned against the matching
PyTorch CUDA wheel index) so this benchmark reflects the same environment
the deployed worker runs in — this is the thing we're actually trying to
reproduce, not a from-scratch Senko install.

Usage:
    modal run bench_modal_senko.py
    modal run bench_modal_senko.py --audio-file /audio/your_file.wav
"""

import modal

app = modal.App("bench-senko-diarization")

audio_volume = modal.Volume.from_name("diarization-audio")

TORCH_INDEX = "https://download.pytorch.org/whl/cu129"

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("ffmpeg", "gcc", "g++", "cmake", "ninja-build", "git")
    .pip_install("uv", "psutil")
    .env({"HF_HOME": "/root/.cache/huggingface"})
    .run_commands(
        "CXX=g++ CC=gcc uv pip install --system 'git+https://github.com/narcotic-sh/senko.git[nvidia]'",
        "uv pip uninstall --system nvidia-cuda-runtime",
        f"uv pip install --system --index-url {TORCH_INDEX} torchcodec",
    )
)


@app.function(
    image=image,
    gpu="T4",  # matches the pyannote bench baseline for apples-to-apples comparison
    volumes={"/audio": audio_volume},
    timeout=600,
)
def run_diarization(audio_file: str = "/audio/trimmed.wav"):
    import gc
    import os
    import time
    import wave
    import warnings

    import psutil
    import torch

    warnings.filterwarnings("ignore")

    def get_rss_mb():
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024

    MIN_SEGMENT_S = 0.5

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")

    with wave.open(audio_file, "r") as wf:
        audio_duration = wf.getnframes() / wf.getframerate()

    print(f"Audio file : {audio_file}")
    print(f"Duration   : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
    print()

    rss_baseline = get_rss_mb()

    # ── Model load ────────────────────────────────────────────────────────────
    print("Loading Senko diarizer...")
    t0 = time.perf_counter()

    import senko
    diarizer = senko.Diarizer(device="auto", warmup=True)

    load_time = time.perf_counter() - t0
    print(f"  Loaded in {load_time:.2f}s")
    print()

    rss_after_load = get_rss_mb()

    # ── Diarization ───────────────────────────────────────────────────────────
    print("Running diarization...")
    t1 = time.perf_counter()

    result = diarizer.diarize(audio_file)

    infer_time = time.perf_counter() - t1
    print(f"  Completed in {infer_time:.2f}s")
    print()

    rss_after_infer = get_rss_mb()

    # ── Results ───────────────────────────────────────────────────────────────
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

    gc.collect()
    rss_after_gc = get_rss_mb()
    print(f"  After gc.collect()   : {rss_after_gc:.1f} MB  ({rss_after_gc - rss_after_infer:+.1f} MB)")

    return {
        "audio_duration": audio_duration,
        "load_time": load_time,
        "infer_time": infer_time,
        "time_per_min": time_per_min,
        "speaker_count": len(speakers),
        "segment_count": len(segments),
    }


@app.local_entrypoint()
def main(audio_file: str = "/audio/trimmed.wav"):
    result = run_diarization.remote(audio_file)
    print("\n── Returned to local ─────────────────────────────────────────────────")
    print(f"  Speakers : {result['speaker_count']}")
    print(f"  Segments : {result['segment_count']}")
    print(f"  Time/min : {result['time_per_min']:.2f}s/min (GPU)")