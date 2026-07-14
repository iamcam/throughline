#!/bin/bash
set -e

echo "Running migrations... ⚙️"
uv run alembic upgrade head

if [ "$1" = "worker" ]; then
    echo "Starting worker... 🚀"
    exec uv run streaq run src.worker:worker
else
    echo "Starting server... 🚀"
    exec uv run uvicorn src.api.main:app --host 0.0.0.0 --port 3001
fi