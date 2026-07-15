# src/transcription/remote.py
import httpx
from opentelemetry import trace
import logging

from src.telemetry.tracer import tracer
from src.transcription.base import TranscriptResult, TranscriptSegment
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class RemoteTranscriptionService:
    def __init__(self, service_url: str, api_key: str | None = None):
        # service_url should be the base URL e.g. http://localhost:8001/v1
        self._service_url = service_url.rstrip("/")
        self._api_key = api_key


    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en",
    ) -> TranscriptResult:
        with tracer.start_as_current_span("transcription") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")

            span.set_attribute("transcription.backend", "remote")
            span.set_attribute("transcription.service_url", self._service_url)
            span.set_attribute("transcription.language", language)

            try:
                headers = {}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"

                async with httpx.AsyncClient(timeout=600, headers=headers) as client:
                    with open(audio_path, "rb") as f:
                        response = await client.post(
                            f"{self._service_url}/audio/transcriptions",
                            files={"file": f},
                            data={
                                "model": settings.whisper_model or "whisper-1",
                                "language": language,
                            },
                        )
                response.raise_for_status()
                data = response.json()

                text = data.get("text", "")
                segments = _text_to_segments(text)

                result = TranscriptResult(
                    segments=segments,
                    language=language,
                    source="remote",
                )
                span.set_attribute("transcription.segment_count", len(result.segments))
                span.set_status(trace.StatusCode.OK)
                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise


def _text_to_segments(text: str) -> list[TranscriptSegment]:
    """
    Convert a flat transcript string to segments.
    Splits on sentence boundaries — no timestamps or speaker IDs available
    from the OpenAI-compatible API response.
    All segments assigned UNKNOWN speaker and sequential placeholder timestamps.
    """
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    segments = []
    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue
        segments.append(TranscriptSegment(
            speaker_id="UNKNOWN",
            text=sentence,
            start_ms=0,
            end_ms=0,
            sequence_order=i,
        ))
    return segments