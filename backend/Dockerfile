# backend/Dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg gcc g++ python3-dev cmake ninja-build git && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-group diarization --extra-index-url https://download.pytorch.org/whl/cpu
RUN uv pip install --index-url https://download.pytorch.org/whl/cpu torchaudio torchcodec
RUN uv pip install "git+https://github.com/narcotic-sh/senko.git"

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Includes alembic migrations and uvicorn start
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]