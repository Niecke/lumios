import importlib.util
import os
import subprocess

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
    assert calls["run"] == [["db", "upgrade"]]
    assert calls["execv"] == []


def test_migrate_command_retries_until_database_is_ready(entrypoint, monkeypatch):
    results = [1, 1, 0]
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, results[len(runs) - 1])

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 0
    assert len(runs) == 3


def test_migrate_command_fails_after_all_attempts(entrypoint, monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "migrate"])

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 1
    assert len(runs) == entrypoint.MIGRATE_ATTEMPTS


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
