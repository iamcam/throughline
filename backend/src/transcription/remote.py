# src/transcription/remote.py
import httpx

from src.transcription.base import TranscriptResult, TranscriptSegment


class RemoteTranscriptionService:
    def __init__(self, service_url: str):
        self._service_url = service_url.rstrip("/")

    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en",
    ) -> TranscriptResult:
        async with httpx.AsyncClient(timeout=600) as client:
            with open(audio_path, "rb") as f:
                response = await client.post(
                    f"{self._service_url}/transcribe",
                    files={"audio": f},
                    data={
                        "language": language,
                        **({"speaker_count_hint": str(speaker_count_hint)}
                           if speaker_count_hint else {}),
                    },
                )
            response.raise_for_status()

        data = response.json()
        return TranscriptResult(
            segments=[
                TranscriptSegment(
                    speaker_id=s["speaker_id"],
                    text=s["text"],
                    start_ms=s["start_ms"],
                    end_ms=s["end_ms"],
                )
                for s in data["segments"]
            ],
            language=data["language"],
            source="remote",
        )