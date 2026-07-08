# Diarization Feasibility Experiments

**Date:** 2026-06-23
**Machine:** Apple Silicon Mac (Metal GPU)
**Goal:** Benchmark local and remote speaker diarization and ASR options to inform pipeline architecture decisions.

---

## Setup

```bash
uv init --no-workspace
uv add pyannote.audio mlx-whisper "mlx-qwen3-asr[diarize]" mlx-audio modal
uv add "git+https://github.com/narcotic-sh/senko.git"
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
- `senko` — CoreML/ANE on Apple Silicon, CPU on other platforms (MIT license, no HF token required)

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

| Backend              | Hardware                   | Short clip (89s) | Full episode (89min) | Time/min      |
| -------------------- | -------------------------- | ---------------- | -------------------- | ------------- |
| Senko                | Apple Silicon (CoreML/ANE) | 0.11s            | 5.59s                | **0.06s/min** |
| Sortformer MLX       | Apple Silicon (Metal)      | 0.11s            | 💥 crash              | —             |
| pyannote community-1 | Local CPU                  | 53.7s            | ~2,700s              | 36.2s/min     |
| pyannote community-1 | Modal T4 (16GB)            | —                | 279s                 | 3.14s/min     |
| pyannote community-1 | Modal A10 (24GB)           | —                | 161s                 | 1.81s/min     |
| pyannote community-1 | Modal L40S (48GB)          | —                | 100s                 | 1.13s/min     |

### Senko Pipeline Breakdown (full episode)

| Stage              | Time      |
| ------------------ | --------- |
| VAD                | 0.71s     |
| Fbank features     | 0.91s     |
| Speaker embeddings | 1.82s     |
| Clustering         | 2.15s     |
| **Total**          | **5.59s** |

### Memory Profile (Senko, Apple Silicon)

Measured via `psutil` RSS on full episode (89 min):

| Stage              | RSS       | Delta    |
| ------------------ | --------- | -------- |
| Baseline           | 20.5 MB   | —        |
| After model load   | 849.5 MB  | +829 MB  |
| After inference    | 2622.8 MB | +1773 MB |
| After gc.collect() | 2622.8 MB | +0 MB    |

Inference memory is not released between runs — the library retains intermediate state. Peak RSS is ~2.6GB and is effectively fixed for the worker process lifetime regardless of episode count, since jobs run sequentially. Memory does not accumulate across episodes.

**Implications for deployment:**

- A machine with 8GB RAM handles this comfortably alongside the API process and Postgres
- Running Whisper and Senko in the same worker process adds their footprints — plan for ~3-4GB total for the worker
- Concurrent workers each hold their own ~2.6GB — relevant only if running parallel ingestion, which is not the default for personal use
- The server-as-persistent-API pattern (multiple concurrent requests) is not recommended for Senko — use the ARQ worker queue instead, which bounds memory to a single sequential worker process

### Modal GPU Pricing (per episode, 89 min)

| GPU  | $/sec     | Wall time | Cost/episode |
| ---- | --------- | --------- | ------------ |
| T4   | $0.000164 | 279s      | ~$0.046      |
| L4   | $0.000222 | ~220s     | ~$0.049      |
| A10  | $0.000306 | 161s      | ~$0.051      |
| L40S | $0.000542 | 100s      | ~$0.056      |

All GPU options cost under $0.06 per episode. T4 is the recommended default.

---

## Key Findings

### 1. Senko is the clear local diarization winner

`senko` runs at 0.06s/min on Apple Silicon via CoreML/ANE — matching Sortformer MLX on short clips and completing a full 89-minute episode in 5.59 seconds. Unlike Sortformer, it handles full-length episodes without crashing. MIT license, no HF token required, `device='auto'` picks the right backend. Speaker count was correct on both test clips (3 and 4 speakers) without any manual clamping.

Senko's internal pipeline is chunked by design — VAD segments the audio first, then embeddings and clustering run over those segments. This is why it handles long audio where Sortformer's single-allocation approach fails.

### 2. Sortformer MLX is fast but not production-ready

`mlx-community/diar_sortformer_4spk-v1-fp16` runs at 0.07s/min on short clips but crashes on full-length episodes with a GPU memory page fault. The mlx-audio library processes the full feature tensor in a single allocation rather than chunking. The NeMo v2 model requires chunked streaming but `mlx_audio.vad.Model.generate()` exposes no `chunk_size` parameter as of June 2026. Worth revisiting when mlx-audio ships chunked streaming.

### 3. pyannote CPU is viable for infrequent ingestion

At 36s/min a 90-minute episode takes ~36 minutes. Acceptable as an ARQ background job for personal use. Not suitable for bulk processing.

### 4. pyannote on Modal GPU is viable for remote deployment

T4 completes a 90-minute episode in ~280 seconds at ~$0.046. Scales to zero when idle. All GPU tiers work — T4 is cost-optimal. Useful if the host machine lacks the memory or performance for local diarization, or for bulk processing.

### 5. ASR is solved on Apple Silicon

All tested models run via MLX/Metal at 3-5s/min. Whisper is preferred for API compatibility with OpenAI-format endpoints. `whisper-large-v3-turbo` is the recommended production model.

### 6. mlx-qwen3-asr diarization offers no performance benefit

`mlx-qwen3-asr --diarize` calls the same pyannote CPU pipeline internally. MLX acceleration only applies to ASR. No wall-time advantage over running pyannote directly.

---

## Architecture Recommendation

### ASR

`mlx-community/whisper-large-v3-turbo` on Apple Silicon. Falls back to `faster-whisper` on CUDA. Same pattern as current `WHISPER_BACKEND` config.

### Diarization — local (recommended default)

`senko` with `device='auto'`. No token required. 0.06s/min on Apple Silicon. Handles full-length episodes. MIT license.

### Diarization — remote (optional)

pyannote `community-1` behind a `POST /diarize` HTTP endpoint. Any provider works — Modal deploy, RunPod, local Docker. T4 is cost-optimal at ~$0.05/episode.

### Config (mirrors transcription pattern)

```
# Leave empty to use local Senko
DIARIZATION_SERVICE_URL=

# Required only for pyannote (local or remote) — not needed for Senko
HF_TOKEN=

# Local config — ignored when DIARIZATION_SERVICE_URL is set
DIARIZATION_MODEL=senko
```

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
  "inference_time": 5.59,
  "time_per_minute": 0.06
}
```

---

## Future Work

### Modal deployment

Modal containers are one way to deploy pyannote services behind a FastAPI endpoint.

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

**Transcription with Diarization + CUDA**

If running the application on a CUDA platform, consider a unified tool like WhisperX, which combines faster-whisper with pyannote into a single pipeline. This is worth evaluating during the diarization implementation phase — though it only applies to CUDA deployments, so clients without GPU hardware would still need a separate diarization service.

---

## Scripts

| Script                        | Purpose                                     |
| ----------------------------- | ------------------------------------------- |
| `convert_audio.py`            | Convert m4a to 16kHz mono WAV via ffmpeg    |
| `bench_pyannote.py`           | pyannote CPU diarization benchmark          |
| `bench_sortformer.py`         | Sortformer MLX diarization benchmark        |
| `bench_senko.py`              | Senko diarization benchmark ⭐               |
| `bench_mlx_whisper.py`        | mlx-whisper ASR benchmark                   |
| `bench_mlx_qwen3_asr_only.py` | mlx-qwen3-asr ASR-only benchmark            |
| `bench_modal_pyannote.py`     | pyannote on Modal GPU benchmark (ephemeral) |