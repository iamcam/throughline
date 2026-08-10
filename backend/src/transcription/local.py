# src/transcription/local.py
import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from opentelemetry import trace

from src.transcription.base import TranscriptResult, TranscriptSegment
from src.telemetry.tracer import tracer

logger = logging.getLogger(__name__)

def _transcribe_sync(
    audio_path: str,
    language: str,
    whisper_backend: str,
    whisper_model: str,
) -> TranscriptResult:
    """
    Runs in a subprocess. No async, no event loop.
    All imports are local -- subprocess does not inherit parent state.
    """
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(f"Begin transcription: {audio_path}")
    # --- Whisper ---
    # MPS not supported by faster-whisper; fall back to CPU on Apple Silicon
    words = []
    if whisper_backend == "mlx_whisper":
        logger.info(f"Using mlx_whisper with model {whisper_model}")
        import mlx_whisper
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=whisper_model,
            word_timestamps=True,
        )
        words = [
            (w["start"], w["end"], w["word"].strip())
            for s in result["segments"]
            for w in s.get("words", [])
        ]
    else:
        logger.info(f"Using faster_whisper with model {whisper_model}")
        from faster_whisper import WhisperModel
        compute_type = "int8" if device == "cpu" else "float16"
        whisper = WhisperModel(whisper_model, device=device, compute_type=compute_type)
        segments_iter, _ = whisper.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
        )
        for segment in segments_iter:
            for word in segment.words:
                words.append((word.start, word.end, word.word))

    logger.info(f"Finished transcribing.")

    # Speaker assignment happens later, in the diarization + alignment stage.
    # Everything here is UNKNOWN until then.
    segments = []
    current_words = []
    current_start = None
    current_end = 0.0

    for word_start, word_end, word_text in words:
        if not current_words:
            current_start = word_start
        current_words.append(word_text)
        current_end = word_end

        # Pick a minimum useful sentence length.
        MIN_SEGMENT_WORDS = 5
        if word_text.strip().endswith((".", "?", "!", "...", "。")):
            if len(current_words) >= MIN_SEGMENT_WORDS:
                segments.append(TranscriptSegment(
                    speaker_id="UNKNOWN",
                    text=" ".join(current_words).strip(),
                    start_ms=int(current_start * 1000),
                    end_ms=int(current_end * 1000),
                    sequence_order=len(segments)
                ))
                current_words = []
            # else keep adding words to the next sentence.

    if current_words:
        segments.append(TranscriptSegment(
            speaker_id="UNKNOWN",
            text=" ".join(current_words).strip(),
            start_ms=int(current_start * 1000),
            end_ms=int(current_end * 1000),
            sequence_order=len(segments)
        ))

    logger.info(f"Finished assigning transcription to 'UNKNOWN' speaker label")
    return TranscriptResult(
        segments=segments,
        language=language,
        source="whisper_local",
    )


class LocalTranscriptionService:
    def __init__(
        self,
        whisper_backend: str,
        whisper_model: str,
        max_workers: int = 1,
        executor: ProcessPoolExecutor | None = None,
    ):
        self._whisper_backend = whisper_backend
        self._model_size = whisper_model
        self._executor = executor or ProcessPoolExecutor(max_workers=max_workers)

    def shutdown(self):
        """Performs a proper shutdown; cleans up any leaked semaphores."""
        self._executor.shutdown(wait=True)

    async def transcribe(
        self,
        audio_path: str,
        language: str = "en",
    ) -> TranscriptResult:
        with tracer.start_as_current_span("transcription") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")

            span.set_attribute("transcription.backend", self._whisper_backend)
            span.set_attribute("transcription.model", self._model_size)
            span.set_attribute("transcription.language", language)

            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    _transcribe_sync,
                    audio_path,
                    language,
                    self._whisper_backend,
                    self._model_size,
                )

                span.set_attribute("transcription.segment_count", len(result.segments))
                span.set_status(trace.StatusCode.OK)

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
