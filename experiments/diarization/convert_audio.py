#!/usr/bin/env python3
"""
Convert m4a to 16kHz mono WAV for pyannote.

Usage:
    uv run convert_audio.py input.m4a [output.wav]
"""

import subprocess
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".wav")

if not src.exists():
    raise FileNotFoundError(f"Input file not found: {src}")

cmd = [
    "ffmpeg", "-y",
    "-i", str(src),
    "-ar", "16000",   # 16kHz sample rate
    "-ac", "1",       # mono
    "-c:a", "pcm_s16le",  # 16-bit PCM
    str(dst),
]

print(f"Converting {src} → {dst}")
subprocess.run(cmd, check=True)
print(f"Done: {dst}")