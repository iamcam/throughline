# src/diarization/local.py
import asyncio
import logging
import subprocess
from concurrent.futures import ProcessPoolExecutor
import faulthandler
from opentelemetry import trace
from concurrent.futures.process import BrokenProcessPool

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


def _init_diarizer(device: str, log_level: int) -> None:
    """
    ProcessPoolExecutor initializer -- runs once when a subprocess starts,
    before any tasks are submitted to it. No async, no event loop.
    """
    faulthandler.enable()  # dumps a traceback on SIGSEGV/SIGABRT instead of a silent kill

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        force=True,
    )

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
    except Exception as e:
        logger.exception(e)
        raise

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
        self._device = device
        self._max_workers = max_workers
        self._executor = executor or self._build_executor()


    def shutdown(self):
        """Performs a proper shutdown; cleans up any leaked semaphores."""
        self._executor.shutdown(wait=True)

    def _build_executor(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(
            max_workers=self._max_workers,
            initializer=_init_diarizer,
            initargs=(self._device, logging.getLogger().getEffectiveLevel()),
        )

    async def diarize(self, audio_path: str) -> DiarizationResult:
        with tracer.start_as_current_span("diarization") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._executor, _diarize_sync, audio_path,
                )
                span.set_attribute("diarization.turn_count", len(result.turns))
                span.set_attribute("diarization.speaker_count", result.speaker_count)
                span.set_status(trace.StatusCode.OK)
                return result
            except BrokenProcessPool as e:
                # A subprocess died (OOM-kill, segfault). The pool is permanently dead;
                # without this, every subsequent job fails immediately and hides the
                # real cause. This episode still fails, but the next one gets a fresh pool.
                logger.critical("Senko process pool broken, rebuilding: %s", e)
                self._executor = self._build_executor()
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, "process pool broken, rebuilt")
                raise
            except Exception as e:
                logger.exception(e)
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
