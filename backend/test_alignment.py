# experiments/test_alignment.py
"""
Standalone smoke test for the diarization + alignment pipeline pieces,
run outside the full worker/DB pipeline.

Usage:
    uv run experiments/test_alignment.py path/to/episode.mp3
"""
import asyncio
import sys

from src.config import get_settings
from src.diarization.alignment import align_segments
from src.diarization.local import LocalDiarizationService
from src.transcription.local import LocalTranscriptionService


async def main(audio_path: str) -> None:
    settings = get_settings()

    transcription = LocalTranscriptionService(
        whisper_backend=settings.whisper_backend,
        whisper_model=settings.whisper_model,
        max_workers=1,
    )
    diarization = LocalDiarizationService(max_workers=1)

    try:
        print("Transcribing...")
        transcript = await transcription.transcribe(audio_path)
        print(f"  {len(transcript.segments)} segments, all UNKNOWN\n")

        print("Diarizing...")
        diarized = await diarization.diarize(audio_path)
        print(f"  {diarized.speaker_count} speakers, {len(diarized.turns)} turns\n")

        print("Aligning...")
        aligned = align_segments(transcript.segments, diarized)

        print("\n--- Result ---")
        for s in aligned:
            print(f"[{s.start_ms:>7}ms - {s.end_ms:>7}ms] {s.speaker_id:<12} {s.text}")

    finally:
        transcription.shutdown()
        diarization.shutdown()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))