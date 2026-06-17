#!/bin/bash
set -e

# run alembic DB migrations prior to starting up the server
echo "Running migrations... ⚙️"
uv run alembic upgrade head


# Off we go!
echo "Starting server... 🚀"
exec uv run uvicorn src.api.main:app --host 0.0.0.0 --port 3001