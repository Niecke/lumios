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


def main() -> None:
    _log("Starting Lumios Backend...")

    _log("Testing database connection...")
    while not _flask_db_current():
        _log("Database not ready - waiting...", level="warning")
        time.sleep(5)

    _log("Running database migrations...")
    subprocess.run([PYTHON, "-m", "flask", "db", "upgrade"], check=True)
    _log("Migrations complete!")

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
    ]
    if os.environ.get("DEBUG") == "true":
        args += ["--reload", "--reload-engine", "poll"]

    args.append("main:create_app()")
    os.execv(PYTHON, args)


if __name__ == "__main__":
    main()
