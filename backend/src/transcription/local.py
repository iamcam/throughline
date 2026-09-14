# src/transcription/local.py
import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Callable
from opentelemetry import trace

from src.transcription.base import TranscriptResult, TranscriptSegment
from src.telemetry.tracer import tracer
import tiktoken

logger = logging.getLogger(__name__)

_encoder = tiktoken.get_encoding("cl100k_base")

def _default_tokenizer(text: str) -> int:
    return len(_encoder.encode(text))

def _transcribe_sync(
    audio_path: str,
    language: str,
    whisper_backend: str,
    whisper_model: str,
    min_segment_words: int,
    max_segment_tokens: int,
    pause_threshold_s: float,
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
                words.append((word.start, word.end, word.word.strip()))

    logger.info(f"Finished transcribing.")

    # Speaker assignment happens later, in the diarization + alignment stage.
    # Everything here is UNKNOWN until then.
    segments = _build_segments_from_words(
        words, min_segment_words, max_segment_tokens, pause_threshold_s,
        tokenizer=_default_tokenizer,
    )
    logger.info(f"Segmented into {len(segments)} transcript segments")
    return TranscriptResult(segments=segments, language=language, source="whisper_local")


class LocalTranscriptionService:
    def __init__(
        self,
        whisper_backend: str,
        whisper_model: str,
        min_segment_words: int,
        max_segment_tokens: int,
        pause_threshold_s: float,
        max_workers: int = 1,
        executor: ProcessPoolExecutor | None = None,
    ):
        self._whisper_backend = whisper_backend
        self._model_size = whisper_model
        self._min_segment_words = min_segment_words
        self._max_segment_tokens = max_segment_tokens
        self._pause_threshold_s = pause_threshold_s
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
                    self._min_segment_words,
                    self._max_segment_tokens,
                    self._pause_threshold_s,
                )

                span.set_attribute("transcription.segment_count", len(result.segments))
                span.set_status(trace.StatusCode.OK)

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise

def _build_segments_from_words(
    words: list[tuple[float, float, str]],
    min_segment_words: int,
    max_segment_tokens: int,
    pause_threshold_s: float,
    tokenizer: Callable[[str], int],
) -> list[TranscriptSegment]:
    """Pure -- no I/O, no subprocess dependency. Takes flattened (start, end,
    text) word tuples (from either whisper backend) and returns segments,
    using sentence punctuation as the normal boundary and falling back to a
    pause, then a hard cut, only once an unpunctuated run crosses
    max_segment_tokens."""
    segments: list[TranscriptSegment] = []
    current: list[tuple[float, float, str]] = []

    def _flush(upto: int):
        nonlocal current
        piece = current[:upto]
        segments.append(TranscriptSegment(
            speaker_id="UNKNOWN",
            text=" ".join(w[2] for w in piece).strip(),
            start_ms=int(piece[0][0] * 1000),
            end_ms=int(piece[-1][1] * 1000),
            sequence_order=len(segments),
        ))
        current = current[upto:]

    for word_start, word_end, word_text in words:
        current.append((word_start, word_end, word_text))

        ends_sentence = word_text.strip().endswith((".", "?", "!", "...", "。"))
        if ends_sentence and len(current) >= min_segment_words:
            _flush(len(current))
            continue

        token_count = tokenizer(" ".join(w[2] for w in current))
        if token_count >= max_segment_tokens:
            cut_at = None
            for i in range(min_segment_words, len(current) - 1):
                if current[i + 1][0] - current[i][1] > pause_threshold_s:
                    cut_at = i + 1
                    break
            if cut_at is None:
                logger.warning(
                    "Forcing segment cut at %d tokens, no terminal punctuation or pause "
                    "found -- likely Whisper punctuation dropout on a long run of speech "
                    "(known upstream issue). start=%.2fs end=%.2fs",
                    token_count, current[0][0], current[-1][1],
                )
                cut_at = len(current)
            _flush(cut_at)

    if current:
        _flush(len(current))

    return segments