# backend/Dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra-index-url https://download.pytorch.org/whl/cpu

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./


# Includes alembic migrations and uvicorn start
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]