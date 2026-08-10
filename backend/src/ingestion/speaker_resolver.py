# src/ingestion/speaker_resolver.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from opentelemetry import trace

from src.llm.base import LLMClient
from src.telemetry.tracer import tracer
from src.transcription.base import TranscriptSegment

logger = logging.getLogger(__name__)

@dataclass
class InferredSpeaker:
    """
    Result of a successful speaker inference pass for one diarized speaker.

    confidence is the LLM's self-reported certainty: "high", "medium", or "low".
    Stored on episode_speakers.confidence and shown in the UI so users know whether to trust the pre-filled name.

    None is returned instead of this dataclass when inferencing finds nothing or the response is malformed.
    This is not treated as an error and the pipeline continues with that speaker's row left unnamed.
    """
    name: str
    confidence: str  # "high" | "medium" | "low"

class SpeakerResolver:
    def __init__(
        self,
        llm_client: LLMClient,
        window_ms: int = 900_000,  # 15 min window after a speaker's first utterance
        padding_ms: int = 60_000,  # look-back before it, to catch "my guest today is X" style intros
    ):
        self._llm = llm_client
        self._window_ms = window_ms
        self._padding_ms = padding_ms

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> dict[str, InferredSpeaker | None]:
        speaker_ids = sorted({s.speaker_id for s in segments if s.speaker_id != "UNKNOWN"})

        results: dict[str, InferredSpeaker | None] = {}
        for speaker_id in speaker_ids:
            results[speaker_id] = await self._infer_one(speaker_id, segments)

        return results

    async def _infer_one(
        self,
        speaker_id: str,
        segments: list[TranscriptSegment],
    ) -> InferredSpeaker | None:
        with tracer.start_as_current_span("speaker_inference") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")
            span.set_attribute("speaker.target_id", speaker_id)

            speaker_segments = [s for s in segments if s.speaker_id == speaker_id]
            if not speaker_segments:
                span.set_attribute("speaker.name_found", False)
                span.set_status(trace.StatusCode.OK)
                return None

            first_utterance_ms = min(s.start_ms for s in speaker_segments)
            window_start = max(0, first_utterance_ms - self._padding_ms)
            window_end = first_utterance_ms + self._window_ms

            windowed = sorted(
                (s for s in segments if window_start <= s.start_ms <= window_end),
                key=lambda s: s.sequence_order,
            )
            span.set_attribute("speaker.window_segment_count", len(windowed))

            if not windowed:
                logger.debug("No segments in window for %s, skipping", speaker_id)
                span.set_attribute("speaker.name_found", False)
                span.set_status(trace.StatusCode.OK)
                return None

            transcript_text = "\n".join(f'{s.speaker_id}: "{s.text}"' for s in windowed)

            prompt = (
                f"Below is a transcript excerpt from a podcast, labeled by speaker. "
                f"Who is {speaker_id} (what is their name) and what is your confidence on this answer "
                "from low, medium, or high? "
                "Respond with ONLY a JSON object, no explanation, no markdown, no backticks. "
                'Use exactly this format: {"name": "[person name]", "confidence": "[low|medium|high]"}\n\n'
                f"Transcript:\n{transcript_text}"
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )

            try:
                raw = response.content.strip().strip("```json").strip("```").strip()
                data = json.loads(raw)
                name = data.get("name", "").strip()
                confidence = data.get("confidence", "").strip().lower()
                # TODO - good place to track the success/fail metrics on the prompt/response
                if name and confidence in ("low", "medium", "high"):
                    span.set_attribute("speaker.name_found", True)
                    span.set_attribute("speaker.confidence", confidence)
                    span.set_status(trace.StatusCode.OK)
                    return InferredSpeaker(name=name, confidence=confidence)

                elif name == "":
                    span.set_attribute("speaker_inference.result", "no_speaker_identified")
                    span.set_attribute("speaker.name_found", False)
                    span.set_status(trace.StatusCode.OK)
                else:
                    span.set_attribute("speaker_inference.result", "invalid_confidence")
                    span.set_attribute("speaker.name_found", False)
                    span.set_status(trace.StatusCode.ERROR, f"model returned unrecognized confidence value: {confidence}")

                logger.debug(f"Inference response missing valid name or confidence: {data}")
            except (json.JSONDecodeError, AttributeError):
                span.set_attribute("speaker_inference.result", "invalid_confidence")
                span.set_status(trace.StatusCode.ERROR, "Failed to parse speaker inference response")
                span.set_attribute("speaker.name_found", False)
                logger.warning("Failed to parse speaker inference response")

            return None