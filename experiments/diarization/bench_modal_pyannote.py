#!/usr/bin/env python3
"""
Experiment F: pyannote speaker-diarization-community-1 on Modal CUDA GPU.

You will need to ensure a "huggingface" secret with HF_TOKEN key configured in the Modal dashboard

Usage:
    modal run bench_modal_pyannote.py
    modal run bench_modal_pyannote.py --audio-file /audio/your_file.wav
"""

import modal

app = modal.App("bench-pyannote-diarization")

audio_volume = modal.Volume.from_name("diarization-audio")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install('ffmpeg')
    .pip_install("pyannote.audio", "torch", "torchaudio")
)

@app.function(
    image=image,
    gpu="T4", #L40S (1.13s/min audio), A10 (1.81s/min audio), T4 (3.8s/min audio) confirmed
    secrets=[modal.Secret.from_name("huggingface")],
    volumes={"/audio": audio_volume},
    timeout=600,
)
def run_diarization(audio_file: str = "/audio/trimmed.wav"):
    import os
    import time
    import wave
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.telemetry import set_telemetry_metrics
    set_telemetry_metrics(False)
    import warnings
    warnings.filterwarnings("ignore", message="std\\(\\): degrees of freedom is <= 0")

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")

    HF_TOKEN = os.environ["HF_TOKEN"]

    with wave.open(audio_file, "r") as wf:
        audio_duration = wf.getnframes() / wf.getframerate()

    print(f"Audio file : {audio_file}")
    print(f"Duration   : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
    print()

    # ── Model load ────────────────────────────────────────────────────────────
    print("Loading pipeline...")
    t0 = time.perf_counter()

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=HF_TOKEN,
    )

    pipeline.to(torch.device("cuda"))
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    print(f"tf32 settings: ----------")
    print(f"  torch.backends.cuda.matmul.allow_tf32 = {torch.backends.cuda.matmul.allow_tf32}")
    print(f"  torch.backends.cudnn.allow_tf32 = {torch.backends.cudnn.allow_tf32}")
    print()

    pipeline.instantiate({
        "segmentation": {"min_duration_off": 0.5},
    })

    load_time = time.perf_counter() - t0
    print(f"  Model loaded in {load_time:.2f}s")
    print()

    # ── Diarization ───────────────────────────────────────────────────────────
    print("Running diarization...")
    t1 = time.perf_counter()

    MIN_SPEAKERS = 1
    MAX_SPEAKERS = 5
    output = pipeline(audio_file, min_speakers=MIN_SPEAKERS, max_speakers=MAX_SPEAKERS)

    infer_time = time.perf_counter() - t1
    print(f"  Completed in {infer_time:.2f}s")
    print()

    # ── Results ───────────────────────────────────────────────────────────────
    MIN_SEGMENT_S = 0.5
    segments = [
        (turn, speaker)
        for turn, speaker in output.speaker_diarization
        if (turn.end - turn.start) >= MIN_SEGMENT_S
    ]
    speakers = sorted({speaker for _, speaker in segments})

    # print("── Segments ──────────────────────────────────────────────────────────")
    for turn, speaker in segments:
        duration = turn.end - turn.start
        print(f"  {speaker}  [{turn.start:7.2f}s → {turn.end:7.2f}s]  ({duration:.2f}s)")

    print()
    print("── Timing summary ────────────────────────────────────────────────────")
    print()
    time_per_min = infer_time / (audio_duration / 60)
    print(f"  Audio duration  : {audio_duration:.1f}s ({audio_duration/60:.2f} min)")
    print(f"  Model load      : {load_time:.2f}s")
    print(f"  Inference       : {infer_time:.2f}s")
    print(f"  Time per minute : {time_per_min:.2f}s/min")
    print(f"  Total           : {load_time + infer_time:.2f}s")

    return {
        "audio_duration": audio_duration,
        "load_time": load_time,
        "infer_time": infer_time,
        "time_per_min": time_per_min,
        "speaker_count": len(speakers),
        "segment_count": len(segments),
        "min_speakers_cap": MIN_SPEAKERS,
        "max_speakers_cap": MAX_SPEAKERS
    }


@app.local_entrypoint()
def main(audio_file: str = "/audio/trimmed.wav"):
    result = run_diarization.remote(audio_file)
    print("\n── Returned to local ─────────────────────────────────────────────────")
    print(f"  Speakers : {result['speaker_count']}")
    print(f"  Segments : {result['segment_count']}")
    print(f"  Time/min : {result['time_per_min']:.2f}s/min (GPU)")