# src/ingestion/speaker_resolver.py

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from src.llm.base import LLMClient
from src.transcription.base import TranscriptSegment

logger = logging.getLogger(__name__)

@dataclass
class InferredSpeaker:
    """
    Result of a successfu speaker inference pass.

    confidence is the LLM's self-reported certainty: "high", "medium", or "low".
    Stored on episode_speakers.confidence and shown in the UI so users know whether to trust the pre-filled name.

    None is returned instead of this dataclass when inferencing find nothing or the response is malformed.
    This is not treated as an error and the pipelie will continue with speaker_id = "UNKNOWN"
    """
    name: str
    confidence: str  # "high" | "medium" | "low"

class SpeakerResolver:
    def __init__(self, llm_client: LLMClient, window_ms: int = 900_000): # 15 min window
        self._llm = llm_client
        self._window_ms = window_ms

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> InferredSpeaker | None:
        intro = [s for s in segments if s.start_ms < self._window_ms]
        if not intro:
            logger.debug("No segments within inference window, skipping")
            return None

        transcript_text = "\n".join(f'"{s.text}"' for s in intro)

        prompt = (
            "Who is the speaker in this podcast transcript and what is your "
            "confidence on this answer from low, medium, or high? "
            'Use the structured format: {"name": "[person name]", "confidence": "[low|medium|high]"}\n\n'
            f"Transcript:\n{transcript_text}"
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        try:
            data = json.loads(response.content)
            name = data.get("name", "").strip()
            confidence = data.get("confidence", "").strip().lower()
            # TODO - good place to track the success/fail metrics on the prompt/response
            if name and confidence in ("low", "medium", "high"):
                return InferredSpeaker(name=name, confidence=confidence)

            logger.debug("Inference response missing valid name or confidence: %s", data)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Failed to parse speaker inference response")

        return None