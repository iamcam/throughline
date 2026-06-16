# src/transcription/local.py
import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from opentelemetry import trace

from typing import Literal
import os
from src.transcription.base import TranscriptResult, TranscriptSegment
from src.telemetry.tracer import tracer
_executor = ProcessPoolExecutor(max_workers=1)

logger = logging.getLogger(__name__)

def _transcribe_sync(
    audio_path: str,
    speaker_count_hint: int | None,
    language: str,
    huggingface_token: str,
    whisper_backend: str,
    whisper_model: str,
    diarization_model: str
) -> TranscriptResult:
    """
    Runs in a subprocess. No async, no event loop.
    All imports are local — subprocess does not inherit parent state.
    """
    from pyannote.audio import Pipeline
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(f"Begin transcriptionL {audio_path}")
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

    # --- Pyannote (if enabled) ---


    if not diarization_model:
        logger.info("Skipping diarization")
        # No diarization model configured — assign all words to UNKNOWN
        segments = []

        current_words = []
        current_start = words[0][0] if words else 0.0
        current_end = 0.0

        for word_start, word_end, word_text in words:
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
                    current_start = word_end
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

    # --- else performing speaker diarization ---

    logger.info(f"Begin Diarization with {diarization_model}")
    # mp3 cannot guarantee exact sample counts for given frame boundaries - frames don't align perfectly with arbitrary time boundaries (but wav does).
    wav_path = _make_wav_for_diarization(audio_path)
    try:
        diarization_pipeline = Pipeline.from_pretrained(
            diarization_model,
            token=huggingface_token,
        )
        diarization_pipeline.to(torch.device(device))

        if speaker_count_hint:
            diarization = diarization_pipeline(
                wav_path,
                num_speakers=speaker_count_hint,
            )
        else:
            diarization = diarization_pipeline(wav_path)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)

    speaker_turns = [
        (turn.start, turn.end, speaker)
        for turn, speaker in diarization.speaker_diarization
    ]


    # --- Alignment: Words and speakers ---
    def find_speaker(word_start: float) -> str:
        for turn_start, turn_end, speaker in speaker_turns:
            if turn_start <= word_start < turn_end:
                return speaker
        return "SPEAKER_00"

    logger.info(f"Finished diarizing")
    segments: list[TranscriptSegment] = []
    current_speaker: str = "SPEAKER_00"
    current_words: list[str] = []
    current_start: float = 0.0
    current_end: float = 0.0

    for word_start, word_end, word_text in words:
        speaker = find_speaker(word_start)

        if speaker != current_speaker:
            if current_words:
                segments.append(TranscriptSegment(
                    speaker_id=current_speaker,
                    text=" ".join(current_words).strip(),
                    start_ms=int(current_start * 1000),
                    end_ms=int(current_end * 1000),
                    sequence_order=len(segments)
                ))
            current_speaker = speaker
            current_words = [word_text]
            current_start = word_start
        else:
            current_words.append(word_text)

        current_end = word_end

    if current_words:
        segments.append(TranscriptSegment(
            speaker_id=current_speaker,
            text=" ".join(current_words).strip(),
            start_ms=int(current_start * 1000),
            end_ms=int(current_end * 1000),
            sequence_order=len(segments)
        ))

    logger.info(f"Transcription + Diarization complete: {len(segments)} segments")

    return TranscriptResult(
        segments=segments,
        language=language,
        source="whisper_local",
    )


def _make_wav_for_diarization(audio_path: str) -> str:
    import subprocess
    """
    Convert to 16kHz mono WAV for Pyannote.
    WAV guarantees exact sample counts — MP3 frame boundaries do not.
    Returns path to WAV file — caller is responsible for cleanup.
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


def shutdown_executor():
    """
    Performs a proper shutdown; cleans up any leaked semaphores.
    """
    _executor.shutdown(wait=True)


class LocalTranscriptionService:
    def __init__(
        self,
        huggingface_token: str,
        whisper_backend: str,
        whisper_model: str,
        diarization_model: str | None
    ):
        self._hf_token = huggingface_token
        self._whisper_backend = whisper_backend
        self._model_size = whisper_model
        self._diarization_model = diarization_model


    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en",
    ) -> TranscriptResult:
        with tracer.start_as_current_span("transcription") as span:
            span.set_attribute("transcription.backend", self._whisper_backend)
            span.set_attribute("transcription.model", self._model_size)
            span.set_attribute("transcription.language", language)
            span.set_attribute("transcription.diarization_enabled", bool(self._diarization_model))
            if self._diarization_model:
                span.set_attribute("transcription.diarization_model", self._diarization_model)

            try:

                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    _executor,
                    _transcribe_sync,
                    audio_path,
                    speaker_count_hint,
                    language,
                    self._hf_token,
                    self._whisper_backend,
                    self._model_size,
                    self._diarization_model
                )

                span.set_attribute("transcription.segment_count", len(result.segments))

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
