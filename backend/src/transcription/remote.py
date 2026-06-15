# src/transcription/remote.py
import httpx
from opentelemetry import trace

from src.telemetry.tracer import tracer
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
        with tracer.start_as_current_span("transcription") as span:
            span.set_attribute("transcription.backend", "remote")
            span.set_attribute("transcription.service_url", self._service_url)
            span.set_attribute("transcription.language", language)

            try:
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
                result = TranscriptResult(
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
                span.set_attribute("transcription.segment_count", len(result.segments))
                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise