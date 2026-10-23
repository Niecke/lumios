#!/usr/bin/env bash
# Throwaway PostgreSQL for the backend tests: data directory on tmpfs, fsync off.
# Usage: scripts/test-db.sh start|stop|status
# Env:   POSTGRES_TEST_PORT (default 5432), POSTGRES_PASSWORD (default test_password)
set -euo pipefail

NAME="lumios-postgres-test"
PORT="${POSTGRES_TEST_PORT:-5432}"
PASSWORD="${POSTGRES_PASSWORD:-test_password}"
IMAGE="docker.io/library/postgres:18-alpine"

if command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
elif command -v docker >/dev/null 2>&1; then
  RUNTIME=docker
else
  echo "error: neither podman nor docker found" >&2
  exit 1
fi

case "${1:-}" in
  start)
    if "$RUNTIME" ps --format '{{.Names}}' | grep -qx "$NAME"; then
      echo "$NAME already running"
    else
      "$RUNTIME" rm -f "$NAME" >/dev/null 2>&1 || true
      "$RUNTIME" run -d --name "$NAME" \
        --tmpfs /var/lib/postgresql:rw \
        -e POSTGRES_USER=lumios \
        -e POSTGRES_PASSWORD="$PASSWORD" \
        -e POSTGRES_DB=lumios_test \
        -p "127.0.0.1:${PORT}:5432" \
        "$IMAGE" \
        -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
    fi
    for _ in $(seq 1 30); do
      if "$RUNTIME" exec "$NAME" pg_isready -U lumios -d lumios_test >/dev/null 2>&1; then
        echo "$NAME ready on 127.0.0.1:${PORT}"
        [ "$PORT" = "5432" ] || echo "run the tests with POSTGRES_PORT=${PORT}"
        exit 0
      fi
      sleep 1
    done
    echo "error: $NAME did not become ready" >&2
    exit 1
    ;;
  stop)
    "$RUNTIME" rm -f "$NAME" >/dev/null 2>&1 || true
    echo "$NAME removed"
    ;;
  status)
    if "$RUNTIME" exec "$NAME" pg_isready -U lumios -d lumios_test >/dev/null 2>&1; then
      echo "$NAME ready"
    else
      echo "$NAME not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac
