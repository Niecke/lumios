#!/usr/bin/env bash
# Throwaway PostgreSQL for the backend tests: data directory on tmpfs, fsync off.
# Usage: scripts/test-db.sh start|stop|status|cleanup
#
# Every checkout gets its own database so parallel runs never collide: the tests use
# `lumios_test` for a checkout directory called `lumios`, else `lumios_test_<dir name>`
# (lowercased, other characters become `_`), created on the first run. An explicit
# POSTGRES_DB wins; it must end in `_test` or start with `lumios_test_`.
# `cleanup [-y]` lists the `lumios_test_*` databases that belong to no existing worktree
# of THIS repository (run it from inside any worktree) and asks before dropping them,
# unless -y is given. `lumios_test` is kept. Databases of other clones and explicit
# `lumios_test_<x>` POSTGRES_DB overrides look orphaned and are listed too.
# Env:   POSTGRES_TEST_PORT (default 5432), POSTGRES_PASSWORD (default test_password),
#        TEST_DB_CLEANUP_PREFIX (cleanup only; default `lumios_test_`, must start with it)
set -euo pipefail

NAME="lumios-postgres-test"
PORT="${POSTGRES_TEST_PORT:-5432}"
PASSWORD="${POSTGRES_PASSWORD:-test_password}"
IMAGE="docker.io/library/postgres:18.6-alpine@sha256:898c60cb390d1085bc97bdd6a1ae968757421df394b071848b52b1c09c89d6a5"

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
  cleanup)
    prefix="${TEST_DB_CLEANUP_PREFIX:-lumios_test_}"
    case "$prefix" in
      lumios_test_*) ;;
      *) echo "error: TEST_DB_CLEANUP_PREFIX must start with lumios_test_" >&2; exit 1 ;;
    esac
    case "$prefix" in
      *[!a-z0-9_]*) echo "error: TEST_DB_CLEANUP_PREFIX may contain only a-z, 0-9 and _" >&2; exit 1 ;;
    esac
    psql_admin() { "$RUNTIME" exec "$NAME" psql -U lumios -d postgres -X -A -t -q "$@"; }
    if ! psql_admin -c 'SELECT 1' >/dev/null 2>&1; then
      echo "error: $NAME is not running, start it with: $0 start" >&2
      exit 1
    fi
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "error: run cleanup from inside a git worktree of the repository" >&2
      exit 1
    fi
    # Database names of the worktrees that still exist (same rule as conftest.py)
    active=""
    while IFS= read -r line; do
      case "$line" in
        "worktree "*)
          dir="${line#worktree }"
          [ -d "$dir" ] || continue
          suffix="$(basename "$dir" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/^_//;s/_$//')"
          active="$active lumios_test_${suffix}"
          ;;
      esac
    done < <(git worktree list --porcelain)
    like_prefix="$(printf '%s' "$prefix" | sed 's/_/\\_/g')"
    orphans=()
    while IFS= read -r db; do
      [ -n "$db" ] || continue
      [ "$db" = "lumios_test" ] && continue
      keep=0
      for a in $active; do
        [ "$(printf '%s' "$a" | cut -c1-63)" = "$db" ] && keep=1
      done
      [ "$keep" = 1 ] || orphans+=("$db")
    done < <(psql_admin -c "SELECT datname FROM pg_database WHERE datname LIKE '${like_prefix}%' ORDER BY datname")
    if [ "${#orphans[@]}" = 0 ]; then
      echo "0 test database(s) dropped"
      exit 0
    fi
    echo "These databases belong to no worktree of this repository and would be dropped:"
    printf '  %s\n' "${orphans[@]}"
    if [ "${2:-}" != "-y" ]; then
      read -r -p "Drop them? [y/N] " answer || answer=""
      case "$answer" in
        y|Y|yes) ;;
        *) echo "aborted, nothing dropped"; exit 1 ;;
      esac
    fi
    for db in "${orphans[@]}"; do
      psql_admin -c "DROP DATABASE \"$db\" WITH (FORCE)" >/dev/null
      echo "dropped $db"
    done
    echo "${#orphans[@]} test database(s) dropped"
    ;;
  *)
    echo "usage: $0 start|stop|status|cleanup [-y]" >&2
    exit 2
    ;;
esac
