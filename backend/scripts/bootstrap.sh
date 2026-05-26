#!/bin/bash
set -e

# Load .env
export $(grep -v '^#' .env | xargs)

echo "Starting DB..."
podman compose -f docker-compose.dev.yml up --wait

echo "Running migrations..."
uv run alembic upgrade head

echo "Creating test DB..."
DB_NAME=$(echo $DATABASE_URL | sed 's/.*\///')
podman exec backend-db-1 psql -U $DB_USER -d $DB_NAME -c \
  "CREATE DATABASE ${DB_NAME}_test;" 2>/dev/null || echo "Test DB already exists, skipping."

echo "Done. Run: uv run uvicorn src.api.main:app --reload --port 3001"