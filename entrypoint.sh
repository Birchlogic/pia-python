#!/bin/sh

# The database might not be immediately available; this simple loop will wait
# Note: For production, a more robust wait-for-it script is recommended.
echo "Waiting for PostgreSQL to start..."
sleep 5

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Uvicorn server..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
