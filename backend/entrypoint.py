import argparse
import inspect
import json
import multiprocessing
import os
import subprocess
import sys
import time

PYTHON = sys.executable


def _log(msg: str, level: str = "info") -> None:
    frame = inspect.currentframe().f_back
    print(
        json.dumps(
            {
                "timestamp": time.time(),
                "type": "startup",
                "msg": msg,
                "level": level,
                "method": f"entrypoint.{frame.f_code.co_name}",
            }
        ),
        flush=True,
    )


def _flask_db_current() -> bool:
    result = subprocess.run(
        [PYTHON, "-m", "flask", "db", "current"],
        capture_output=True,
    )
    if result.returncode != 0:
        out = (result.stdout + result.stderr).decode(errors="replace").strip()
        _log(f"flask db current failed: {out}", level="error")
    return result.returncode == 0


MIGRATE_ATTEMPTS = 30
MIGRATE_RETRY_SECONDS = 5


def wait_for_db() -> None:
    _log("Testing database connection...")
    while not _flask_db_current():
        _log("Database not ready - waiting...", level="warning")
        time.sleep(5)


def migrate_db() -> None:
    _log("Running database migrations...")
    subprocess.run([PYTHON, "-m", "flask", "db", "upgrade"], check=True)
    _log("Migrations complete!")


def migrate_with_retry() -> int:
    # The migration Job of a first install starts while PostgreSQL is still
    # coming up, so retry only while the database is unreachable. Once it
    # answers, `flask db upgrade` runs exactly once: a real migration error
    # fails the Job at once instead of being retried.
    for attempt in range(1, MIGRATE_ATTEMPTS + 1):
        if _flask_db_current():
            break
        _log(
            f"Database not ready (attempt {attempt}/{MIGRATE_ATTEMPTS}) - "
            f"retrying in {MIGRATE_RETRY_SECONDS}s",
            level="warning",
        )
        if attempt < MIGRATE_ATTEMPTS:
            time.sleep(MIGRATE_RETRY_SECONDS)
    else:
        _log(f"Database not reachable after {MIGRATE_ATTEMPTS} attempts", level="error")
        return 1

    _log("Running database migrations...")
    result = subprocess.run([PYTHON, "-m", "flask", "db", "upgrade"])
    if result.returncode != 0:
        _log("Migration failed", level="error")
        return 1
    _log("Migrations complete!")
    return 0


def _import_worker():
    # The app modules sit in the working directory (/app), not next to this script.
    sys.path.insert(0, os.getcwd())
    import worker

    return worker


def run_worker(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="entrypoint.py worker")
    parser.add_argument("--queue", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    worker = _import_worker()
    if args.queue not in worker.QUEUES:
        _log(f"Unknown queue {args.queue!r}, expected one of {worker.QUEUES}", level="error")
        return 2

    wait_for_db()
    _log(f"Starting worker for queue {args.queue} (concurrency {args.concurrency})...")
    stop_heartbeat, heartbeat = worker.start_heartbeat(args.queue)
    try:
        worker.worker_app.run_worker(queues=[args.queue], concurrency=args.concurrency)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=5)
        worker.close_worker_app()
    return 0


def worker_health() -> int:
    code = _import_worker().check_worker_health()
    if code != 0:
        _log("Worker health check failed", level="error")
    return code


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        _log("Running migrations only...")
        sys.exit(migrate_with_retry())

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        sys.exit(run_worker(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "worker-health":
        sys.exit(worker_health())

    _log("Starting Lumios Backend...")

    wait_for_db()

    if os.environ.get("RUN_MIGRATIONS", "true").lower() in ("true", "1", "yes"):
        migrate_db()
    else:
        _log("Skipping database migrations (RUN_MIGRATIONS is not true).")

    if os.environ.get("SEED_TEST_DATA") == "true":
        _log("Seeding test data (SEED_TEST_DATA=true)...")
        subprocess.run([PYTHON, "-m", "flask", "seed-test-data"], check=True)
        _log("Test data seeded.")

    _log("Starting Gunicorn...")
    workers = os.environ.get(
        "GUNICORN_WORKERS", str(2 * multiprocessing.cpu_count() + 1)
    )
    args = [
        PYTHON,
        "-m",
        "gunicorn",
        "--bind",
        "0.0.0.0:8080",
        "--workers",
        workers,
        "--worker-tmp-dir",
        "/dev/shm",
        "--control-socket",
        "/dev/shm/gunicorn.ctl",
        "--log-level",
        "info",
        "--log-config",
        "/app/gunicorn_logging.conf",
        "--timeout",
        "60",
        "--graceful-timeout",
        "30",
    ]
    if os.environ.get("DEBUG") == "true":
        args += ["--reload", "--reload-engine", "poll"]

    args.append("main:create_app()")
    os.execv(PYTHON, args)


if __name__ == "__main__":
    main()
