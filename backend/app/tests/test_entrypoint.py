import importlib.util
import os
import subprocess
import threading
import types

import pytest

ENTRYPOINT = os.path.join(os.path.dirname(__file__), "..", "..", "entrypoint.py")


@pytest.fixture
def entrypoint(monkeypatch):
    spec = importlib.util.spec_from_file_location("lumios_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    monkeypatch.delenv("RUN_MIGRATIONS", raising=False)
    monkeypatch.delenv("SEED_TEST_DATA", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    return module


@pytest.fixture
def calls(entrypoint, monkeypatch):
    """Record subprocess.run and os.execv calls; `flask db current` succeeds."""
    recorded = {"run": [], "execv": []}

    def fake_run(cmd, **kwargs):
        recorded["run"].append(cmd[3:])
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(
        entrypoint.os, "execv", lambda *a: recorded["execv"].append(a)
    )
    return recorded


def test_migrate_command_runs_upgrade_without_gunicorn(entrypoint, calls, monkeypatch):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 0
    assert calls["run"] == [["db", "current"], ["db", "upgrade"]]
    assert calls["execv"] == []


def test_migrate_command_retries_until_database_is_ready(entrypoint, monkeypatch):
    results = {"current": [1, 1, 0], "upgrade": [0]}
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd[4])
        return subprocess.CompletedProcess(
            cmd, results[cmd[4]].pop(0), stdout=b"", stderr=b""
        )

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 0
    assert runs == ["current", "current", "current", "upgrade"]


def test_migrate_command_does_not_retry_failed_upgrade(entrypoint, monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd[4])
        code = 1 if cmd[4] == "upgrade" else 0
        return subprocess.CompletedProcess(cmd, code, stdout=b"", stderr=b"")

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 1
    assert runs == ["current", "upgrade"]


def test_migrate_command_fails_when_database_never_ready(entrypoint, monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd[4])
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 1
    assert runs == ["current"] * entrypoint.MIGRATE_ATTEMPTS


@pytest.mark.parametrize("value", [None, "true", "TRUE", "1", "yes"])
def test_start_runs_migrations(entrypoint, calls, monkeypatch, value):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py"])
    if value is not None:
        monkeypatch.setenv("RUN_MIGRATIONS", value)

    entrypoint.main()

    assert calls["run"] == [["db", "current"], ["db", "upgrade"]]
    assert len(calls["execv"]) == 1


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_start_skips_migrations_but_waits_for_database(
    entrypoint, calls, monkeypatch, value
):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py"])
    monkeypatch.setenv("RUN_MIGRATIONS", value)

    entrypoint.main()

    assert calls["run"] == [["db", "current"]]
    assert len(calls["execv"]) == 1


def test_start_fails_when_upgrade_fails(entrypoint, monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[3:5] == ["db", "upgrade"]:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    execv = []
    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.os, "execv", lambda *a: execv.append(a))
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py"])

    with pytest.raises(subprocess.CalledProcessError):
        entrypoint.main()

    assert execv == []


@pytest.fixture
def fake_worker(entrypoint, monkeypatch):
    """Stand-in for worker.py so no database or Procrastinate is needed."""
    def start_probe_server(state, port):
        order.append("probe_server")
        servers.append(port)
        return types.SimpleNamespace(shutdown=lambda: order.append("probe_shutdown"))

    def start_schema_monitor(state):
        order.append("monitor")
        return threading.Event(), types.SimpleNamespace(join=lambda timeout=None: None)

    def start_heartbeat(queue):
        order.append("heartbeat")
        stop = threading.Event()
        beats.append({"queue": queue, "stop": stop})
        return stop, types.SimpleNamespace(join=lambda timeout=None: None)

    module = types.SimpleNamespace(
        QUEUES=("default", "video", "photo"),
        worker_app=types.SimpleNamespace(
            run_worker=lambda **kw: (order.append("run_worker"), runs.append(kw))
        ),
        ProbeState=lambda: types.SimpleNamespace(),
        WORKER_PROBE_PORT=8081,
        start_probe_server=start_probe_server,
        wait_for_schema=lambda state: order.append("wait_for_schema"),
        start_schema_monitor=start_schema_monitor,
        start_heartbeat=start_heartbeat,
        close_worker_app=lambda: closed.append(True),
    )
    runs = []
    closed = []
    beats = []
    order = []
    servers = []
    monkeypatch.setattr(entrypoint, "_import_worker", lambda: module)
    module.runs = runs
    module.beats = beats
    module.closed = closed
    module.order = order
    module.servers = servers
    return module


def test_worker_command_waits_for_database_then_runs_worker(
    entrypoint, calls, fake_worker, monkeypatch
):
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["entrypoint.py", "worker", "--queue", "video", "--concurrency", "2"],
    )

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 0
    assert calls["run"] == [["db", "current"]]
    assert fake_worker.runs == [{"queues": ["video"], "concurrency": 2}]
    # the pod reports a heartbeat for its queue while the worker runs, and stops it after
    assert [b["queue"] for b in fake_worker.beats] == ["video"]
    assert fake_worker.beats[0]["stop"].is_set()
    # the connection pool is closed on shutdown
    assert fake_worker.closed == [True]
    assert calls["execv"] == []


def test_worker_command_defaults_to_one_job_at_a_time(
    entrypoint, calls, fake_worker, monkeypatch
):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "worker", "--queue", "photo"])

    with pytest.raises(SystemExit):
        entrypoint.main()

    assert fake_worker.runs == [{"queues": ["photo"], "concurrency": 1}]


def test_worker_command_rejects_unknown_queue(entrypoint, calls, fake_worker, monkeypatch):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "worker", "--queue", "mail"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 2
    assert fake_worker.runs == []
    assert calls["run"] == []


def test_worker_command_requires_queue(entrypoint, calls, fake_worker, monkeypatch):
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "worker"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 2
    assert fake_worker.runs == []


def test_worker_waits_for_schema_between_database_and_worker_loop(
    entrypoint, calls, fake_worker, monkeypatch
):
    monkeypatch.setattr(
        entrypoint.sys, "argv", ["entrypoint.py", "worker", "--queue", "video"]
    )

    with pytest.raises(SystemExit):
        entrypoint.main()

    # the probe server is up before anything blocks, the loop starts last
    assert fake_worker.servers == [8081]
    assert fake_worker.order == [
        "probe_server",
        "wait_for_schema",
        "monitor",
        "heartbeat",
        "run_worker",
        "probe_shutdown",
    ]
    assert calls["run"][0] == ["db", "current"]
