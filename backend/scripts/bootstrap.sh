#!/bin/bash
set -e

# Load .env
export $(grep -v '^#' .env | grep -v '^\s*$' | sed 's/#.*//' | xargs)

echo "Starting DB..."
podman compose -f ../docker-compose.yml up db --wait

DB_CONTAINER_NAME=$(podman ps --no-trunc --filter name=-db-1 --format "{{.Names}}")
echo "📦 Container name: ${DB_CONTAINER_NAME}"

echo "Running migrations..."
uv run alembic upgrade head

echo "Creating test DB..."
DB_NAME=$(echo $DATABASE_URL | sed 's/.*\///')

podman exec $DB_CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c \
  "CREATE DATABASE ${DB_NAME}_test;" 2>/dev/null || echo "Test DB already exists, skipping."
podman exec $DB_CONTAINER_NAME psql -U $DB_USER -d "${DB_NAME}_test" -c \
  "CREATE EXTENSION IF NOT EXISTS vector;"

echo "✅ Done. Run: uv run uvicorn src.api.main:app --reload --port 3001"