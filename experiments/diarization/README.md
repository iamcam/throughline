# Diarization Feasibility Experiments

**Date:** 2026-06-23
**Machine:** Apple Silicon Mac (Metal GPU)
**Goal:** Benchmark local and remote speaker diarization and ASR options to inform pipeline architecture decisions.

---

## Setup

```bash
uv init --no-workspace
uv add pyannote.audio mlx-whisper "mlx-qwen3-asr[diarize]" mlx-audio modal
```

Requires `HF_TOKEN` in environment for pyannote experiments (gated model — accept terms at https://huggingface.co/pyannote/speaker-diarization-community-1).

Audio must be converted to 16kHz mono WAV before use:

```bash
uv run convert_audio.py input.m4a
```

---

## Models Tested

### Diarization

- `pyannote/speaker-diarization-community-1` — CPU (PyTorch) and CUDA (Modal GPU)
- `mlx-community/diar_sortformer_4spk-v1-fp16` — MLX/Metal (NVIDIA NeMo Sortformer port via mlx-audio)

### ASR

- `mlx-community/whisper-tiny-mlx`
- `mlx-community/whisper-medium-mlx`
- `mlx-community/whisper-large-v3-turbo`
- `Qwen/Qwen3-ASR-0.6B` via mlx-qwen3-asr
- `Qwen/Qwen3-ASR-1.7B` via mlx-qwen3-asr

---

## Test Audio

- Format: 16kHz mono WAV (converted from m4a via ffmpeg)
- Short clip: 89s (1.48 min), 3 speakers
- Full episode: 5327s (88.79 min), 4 speakers

---

## Results

### ASR Benchmark (warm, post-cache)

| Model                  | Params | Time/min | Notes                          |
| ---------------------- | ------ | -------- | ------------------------------ |
| whisper-tiny-mlx       | 39M    | 4.1s/min | Too small for production       |
| whisper-medium-mlx     | 307M   | 3.0s/min | Best value — fast and accurate |
| whisper-large-v3-turbo | 809M   | 5.2s/min | Higher accuracy, modest cost   |
| Qwen3-ASR-0.6B         | 600M   | 4.7s/min | Comparable to whisper-medium   |
| Qwen3-ASR-1.7B         | 1.7B   | 3.1s/min | Comparable to large-v3-turbo   |

First run includes model download and MLX conversion overhead (30-60s). Subsequent runs hit local cache.

### Diarization Benchmark

| Backend              | Hardware              | Time/min      | 89min episode | Notes                                |
| -------------------- | --------------------- | ------------- | ------------- | ------------------------------------ |
| Sortformer MLX       | Apple Silicon (Metal) | 0.07s/min     | ~4 sec        | Crashes on full episodes (see below) |
| pyannote community-1 | Local CPU             | 36.2s/min     | ~36 min       | Works, slow                          |
| pyannote community-1 | Modal T4 (16GB)       | 3.14s/min     | ~279 sec      |                                      |
| pyannote community-1 | Modal L4 (24GB)       | ~2s/min (est) | ~180 sec      |                                      |
| pyannote community-1 | Modal A10 (24GB)      | 1.81s/min     | ~161 sec      |                                      |
| pyannote community-1 | Modal L40S (48GB)     | 1.13s/min     | ~100 sec      |                                      |

### Modal GPU Pricing (per episode, 89 min)

| GPU  | $/sec     | Time  | Cost/episode |
| ---- | --------- | ----- | ------------ |
| T4   | $0.000164 | 283s  | ~$0.046      |
| L4   | $0.000222 | ~220s | ~$0.049      |
| A10  | $0.000306 | 167s  | ~$0.051      |
| L40S | $0.000542 | 104s  | ~$0.056      |

All GPU options cost under $0.06 per episode. T4 is the recommended default.

---

## Key Findings

### 1. ASR is solved on Apple Silicon

All tested models run via MLX/Metal at 3-5s/min. Whisper is preferred for API compatibility with OpenAI-format endpoints. `whisper-large-v3-turbo` is the recommended production model — best accuracy in the family at 5.2s/min.

### 2. Sortformer MLX is fast but not production-ready

`mlx-community/diar_sortformer_4spk-v1-fp16` runs at 0.07s/min on Metal — 500x faster than pyannote CPU. However it crashes on full-length episodes with a GPU memory page fault. The underlying issue is that the mlx-audio library processes the full feature tensor in a single allocation rather than chunking. The NeMo v2 model was trained on 90-second chunks and requires chunked streaming, but `mlx_audio.vad.Model.generate()` exposes no `chunk_size` parameter as of June 2026. The fix is known upstream but not yet shipped. Worth revisiting in a few months.

### 3. pyannote CPU is viable for infrequent ingestion

At 36s/min a 90-minute episode takes ~36 minutes. Acceptable as an ARQ background job for personal use. Not suitable for bulk processing.

### 4. pyannote on Modal GPU is the production path

T4 completes a 90-minute episode in ~280 seconds at ~$0.046. Scales to zero when idle (no standing cost). Pipeline loads once per container startup and stays warm across requests. All GPU tiers work — T4 is the cost-optimal choice.

### 5. mlx-qwen3-asr diarization offers no performance benefit

`mlx-qwen3-asr --diarize` calls the same pyannote CPU pipeline internally. MLX acceleration only applies to ASR. No wall-time advantage over running pyannote directly.

### 6. Speaker count accuracy requires a hint

Without `min_speakers`/`max_speakers` clamping, pyannote tends to over-count by one speaker, typically from overlapping speech or mic bleed. With clamping, speaker count was correct on both the short clip (3 speakers) and the full episode (4 speakers).

---

## Architecture Recommendation

### ASR

`mlx-community/whisper-large-v3-turbo` on Apple Silicon. Falls back to `faster-whisper` on CUDA. Same pattern as current `WHISPER_BACKEND` config.

### Diarization config (mirrors transcription pattern)

```
# Leave empty to disable diarization (all segments tagged UNKNOWN)
DIARIZATION_SERVICE_URL=

# Required for pyannote — usage tracking enforced by model license
HF_TOKEN=

# Local pyannote config — ignored when DIARIZATION_SERVICE_URL is set
DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
```

- **URL empty** — local pyannote on CPU, uses `DIARIZATION_MODEL` and `HF_TOKEN`
- **URL set** — HTTP POST to that URL; works with Modal deploy, RunPod, local Docker, or any provider exposing the same contract

### HTTP contract (POST /diarize)

Request: `multipart/form-data` with `audio` (WAV file), `min_speakers` (int), `max_speakers` (int)

Response:

```json
{
  "segments": [
    {"speaker": "SPEAKER_00", "start": 0.0, "end": 4.2},
    {"speaker": "SPEAKER_01", "start": 4.2, "end": 8.7}
  ],
  "speaker_count": 2,
  "speakers": ["SPEAKER_00", "SPEAKER_01"],
  "duration": 5327.2,
  "inference_time": 160.74,
  "time_per_minute": 1.81
}
```

---

## Future Work

### Modal deployment

Modal containers are one way to deploy pyannote services behind a fastapi endpoint.

```bash
# one-time secret setup
modal secret create huggingface HF_TOKEN=<your_token>

# deploy (defaults to T4)
modal deploy pyannote_service.py

# deploy with an API key
SERVICE_API_KEY=my-api-key modal deploy pyannote_service.py

# deploy with a different GPU
GPU_MODEL=A10 modal deploy pyannote_service.py

# deploy with a custom secret name
SERVICE_SECRET_NAME=my-hf-secret modal deploy pyannote_service.py
```

Modal prints the service URL after deploy — set it as `DIARIZATION_SERVICE_URL` in your app `.env`.

Scaling note: `max_containers=1` is correct for personal use. Increase for concurrent episode ingestion — each container gets its own GPU and Modal routes requests automatically.

**Transcription with Diarization + CUDA**

If running the application on a CUDA platform, consider a unified tool like WhisperX, which combines faster-whisper with pyannote into a single pipeline. This is worth evaluating during the diarization implementation phase — though it only applies to CUDA deployments, so clients without CUDA GPU hardware would still need a separate diarization service or be satisfied with CPU diarization.

### Service authentication

The diarization service should require an API key to prevent open access. The deploy script reads `SERVICE_API_KEY` from environment and the FastAPI handler validates it on every request:

```python
SERVICE_API_KEY = os.environ.get("SERVICE_API_KEY")

@api.post("/diarize")
async def diarize(
    audio: UploadFile = File(...),
    min_speakers: int = Form(default=1),
    max_speakers: int = Form(default=8),
    x_api_key: str = Header(default=None),
):
    if SERVICE_API_KEY and x_api_key != SERVICE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    ...
```

The app sends it as a request header (`X-Api-Key`). The corresponding app config key is `DIARIZATION_API_KEY` — independent of `TRANSCRIPTION_API_KEY` since the two services are deployed separately and may use different providers.

If `SERVICE_API_KEY` is not set the service runs unauthenticated — useful for local Docker or trusted network deployments.

---

## Scripts

| Script                        | Purpose                                         |
| ----------------------------- | ----------------------------------------------- |
| `convert_audio.py`            | Convert m4a to 16kHz mono WAV via ffmpeg        |
| `bench_pyannote.py`           | pyannote CPU diarization benchmark              |
| `bench_sortformer.py`         | Sortformer MLX diarization benchmark            |
| `bench_mlx_whisper.py`        | mlx-whisper ASR benchmark                       |
| `bench_modal_pyannote.py`     | pyannote on Modal GPU benchmark (ephemeral)     |
