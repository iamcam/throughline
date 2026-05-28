# src/transcription/transcript_fetcher.py
import re
import httpx

from src.transcription.base import TranscriptResult, TranscriptSegment


def _parse_timestamp(ts: str) -> int:
    """Convert HH:MM:SS.mmm or HH:MM:SS,mmm to milliseconds."""
    ts = ts.replace(",", ".")
    parts = ts.strip().split(":")
    hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    return int((hours * 3600 + minutes * 60 + seconds) * 1000)

def _parse_vtt(text: str) -> list[TranscriptSegment]:
    segments = []
    # Match timestamp lines: 00:00:01.000 --> 00:00:05.200
    cue_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s-->\s(\d{2}:\d{2}:\d{2}[.,]\d{3})"
    )
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = cue_pattern.match(lines[i].strip())
        if match:
            start_ms = _parse_timestamp(match.group(1))
            end_ms = _parse_timestamp(match.group(2))
            # Collect all text lines until blank line or end
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                line = lines[i].strip()
                # Skip VTT cue identifiers and NOTE blocks
                if not line.startswith("NOTE") and not line.isdigit():
                    text_lines.append(line)
                i += 1
            cue_text = " ".join(text_lines).strip()
            if cue_text:
                segments.append(TranscriptSegment(
                    speaker_id="SPEAKER_00",
                    text=cue_text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                ))
        else:
            i += 1
    return segments

def _parse_srt(text: str) -> list[TranscriptSegment]:
    segments = []
    cue_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2},\d{3})\s-->\s(\d{2}:\d{2}:\d{2},\d{3})"
    )
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = cue_pattern.match(lines[i].strip())
        if match:
            start_ms = _parse_timestamp(match.group(1))
            end_ms = _parse_timestamp(match.group(2))
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                line = lines[i].strip()
                if not line.isdigit():
                    text_lines.append(line)
                i += 1
            cue_text = " ".join(text_lines).strip()
            if cue_text:
                segments.append(TranscriptSegment(
                    speaker_id="SPEAKER_00",
                    text=cue_text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                ))
        else:
            i += 1
    return segments

async def fetch_transcript(transcript_url: str) -> TranscriptResult:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(transcript_url)
        response.raise_for_status()
        text = response.text

    url_lower = transcript_url.lower().split("?")[0]

    if url_lower.endswith(".srt"):
        segments = _parse_srt(text)
    else:
        #default vtt
        segments = _parse_vtt(text)

    if not segments:
        raise ValueError(
            f"Unrecognized transcript format at {transcript_url} - "
            f"expected .vtt or .srt"
        )

    return TranscriptResult(
        segments=segments,
        language="en",
        source="rss_provided"
    )