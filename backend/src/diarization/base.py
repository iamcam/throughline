# src/diarization/base.py
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SpeakerTurn:
    speaker_id: str  # e.g. "SPEAKER_00" - raw diarization label, not display name
    start_ms: int
    end_ms: int


@dataclass
class DiarizationResult:
    turns: list[SpeakerTurn]
    speaker_count: int  # merged/deduplicated count, not raw


@runtime_checkable
class DiarizationService(Protocol):
    async def diarize(self, audio_path: str) -> DiarizationResult: ...
