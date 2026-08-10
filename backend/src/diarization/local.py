# src/diarization/local.py
import asyncio
import logging
import subprocess
from concurrent.futures import ProcessPoolExecutor
from opentelemetry import trace

from src.diarization.base import DiarizationResult, SpeakerTurn
from src.telemetry.tracer import tracer

logger = logging.getLogger(__name__)

# Segments shorter than this are diarization noise, not real speaker turns.
# See experiments/diarization/bench_senko.py -- same threshold validated there.
MIN_SEGMENT_S = 0.5

# Set once per subprocess by _init_diarizer, then reused by every
# _diarize_sync call in that subprocess -- this is what keeps the model warm
# across jobs instead of reloading it every call.
_diarizer = None


def _init_diarizer(device: str) -> None:
    """
    ProcessPoolExecutor initializer -- runs once when a subprocess starts,
    before any tasks are submitted to it. No async, no event loop.
    """
    global _diarizer
    import senko

    logger.info(f"Loading Senko diarizer (device={device})")
    _diarizer = senko.Diarizer(device=device, warmup=True)


def _diarize_sync(audio_path: str) -> DiarizationResult:
    """
    Runs in a subprocess, reusing the warm _diarizer set up by _init_diarizer.
    """

    wav_path = _make_wav(audio_path)
    try:
        result = _diarizer.diarize(wav_path)
    finally:
        _cleanup_wav(wav_path)

    turns = [
        SpeakerTurn(
            speaker_id=s["speaker"],
            start_ms=int(s["start"] * 1000),
            end_ms=int(s["end"] * 1000),
        )
        for s in result["merged_segments"]
        if (s["end"] - s["start"]) >= MIN_SEGMENT_S
    ]

    return DiarizationResult(
        turns=turns,
        speaker_count=result["merged_speakers_detected"],
    )


def _make_wav(audio_path: str) -> str:
    """
    Senko requires 16-bit WAV input. WAV also guarantees exact sample-count
    boundaries, unlike mp3, which matters for accurate turn timestamps.
    Returns path to the WAV file -- caller is responsible for cleanup.
    """
    wav_path = audio_path + ".diarization.wav"
    subprocess.run([
        "ffmpeg", "-i", audio_path,
        "-ar", "16000",
        "-ac", "1",
        "-y",
        wav_path
    ], check=True, capture_output=True)
    return wav_path


def _cleanup_wav(wav_path: str) -> None:
    import os
    if os.path.exists(wav_path):
        os.remove(wav_path)


class LocalDiarizationService:
    def __init__(
        self,
        device: str = "auto",
        max_workers: int = 1,
        executor: ProcessPoolExecutor | None = None,
    ):
        self._executor = executor or ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_init_diarizer,
            initargs=(device,),
        )

    def shutdown(self):
        """Performs a proper shutdown; cleans up any leaked semaphores."""
        self._executor.shutdown(wait=True)

    async def diarize(
        self,
        audio_path: str,
    ) -> DiarizationResult:
        with tracer.start_as_current_span("diarization") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")

            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    _diarize_sync,
                    audio_path,
                )

                span.set_attribute("diarization.turn_count", len(result.turns))
                span.set_attribute("diarization.speaker_count", result.speaker_count)
                span.set_status(trace.StatusCode.OK)

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
