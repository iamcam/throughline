# src/transcription/base.py
from dataclasses import dataclass
from typing import Protocol, Literal, runtime_checkable


@dataclass
class TranscriptSegment:
    speaker_id: str  # eg "SPEAKER_00" - assigned by diarization, not display name
    text: str
    start_ms: int
    end_ms: int
    sequence_order: int


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    source: Literal["whisper_local", "remote", "rss_provided"]

@runtime_checkable
class TranscriptionService(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en",
    ) -> TranscriptResult: ...

