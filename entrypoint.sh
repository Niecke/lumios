#!/bin/bash
set -e

echo "Starting DocStore API..."

# Test DB via Flask-Migrate (self-healing)
echo "Testing database connection..."
until flask db current; do
  echo "Database not ready - waiting..."
  sleep 5
done

# Run migrations
echo "Running database migrations..."
flask db upgrade
echo "Migrations complete!"

# Start Gunicorn
echo "Starting Gunicorn..."

GUNICORN_WORKERS="${GUNICORN_WORKERS:-$(( 2 * $(nproc) + 1 ))}"
GUNICORN_ARGS="--bind 0.0.0.0:8080 --workers $GUNICORN_WORKERS --log-level info"

if [ "${DEBUG}" = "true" ]; then
  GUNICORN_ARGS="$GUNICORN_ARGS --reload --reload-engine poll"
fi

exec gunicorn $GUNICORN_ARGS "main:create_app()"