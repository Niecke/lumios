"""Tests for the test database helpers in conftest.py and scripts/test-db.sh."""

import os
import shutil
import subprocess
import uuid

import psycopg
import pytest
from psycopg import sql

import conftest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "test-db.sh")


def _params(**extra):
    return dict(
        host="127.0.0.1",
        port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        **extra,
    )


def _database_exists(name):
    with psycopg.connect(dbname="postgres", **_params()) as conn:
        return (
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            is not None
        )


def _drop(name):
    with psycopg.connect(dbname="postgres", autocommit=True, **_params()) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def test_default_test_db_name_respects_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "custom_test")
    assert conftest._default_test_db_name("/srv/worktrees/561") == "custom_test"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/srv/worktrees/lumios/561", "lumios_test_561"),
        ("/srv/worktrees/feature-branch", "lumios_test_feature_branch"),
        ("/srv/worktrees/My Work.Tree", "lumios_test_my_work_tree"),
        ("/home/me/git/lumios", "lumios_test"),
        ("/home/me/git/Lumios", "lumios_test"),
    ],
)
def test_default_test_db_name_derives_from_worktree_path(monkeypatch, path, expected):
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    assert conftest._default_test_db_name(path) == expected


def test_default_test_db_name_fits_identifier_limit(monkeypatch):
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    assert len(conftest._default_test_db_name("/srv/" + "x" * 100)) == 63


def test_is_database_missing_error():
    class WithState(Exception):
        sqlstate = "3D000"

    assert conftest._is_database_missing_error(WithState("boom"), "x_test")
    assert conftest._is_database_missing_error(
        Exception('FATAL:  database "x_test" does not exist'), "x_test"
    )
    assert not conftest._is_database_missing_error(Exception("connection refused"), "x_test")
    assert not conftest._is_database_missing_error(
        Exception('role "lumios" does not exist'), "x_test"
    )


def test_ensure_test_database_exists_rejects_unsafe_db(monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "lumios")
    with pytest.raises(RuntimeError, match="Refusing"):
        conftest._ensure_test_database_exists()


def test_ensure_test_database_exists_creates_missing_db(monkeypatch):
    name = f"lumios_test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("POSTGRES_DB", name)
    try:
        assert not _database_exists(name)
        conftest._ensure_test_database_exists()
        assert _database_exists(name)
        conftest._ensure_test_database_exists()  # idempotent
        assert _database_exists(name)
    finally:
        _drop(name)


def test_ensure_test_database_exists_unreachable_server(monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "lumios_test_unreachable")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens here
    with pytest.raises(RuntimeError, match=r"test-db\.sh start"):
        conftest._ensure_test_database_exists()


def test_cleanup_script_removes_orphan_test_databases():
    if shutil.which("podman") is None and shutil.which("docker") is None:
        pytest.skip("no container runtime")
    if subprocess.run([SCRIPT, "status"], capture_output=True).returncode != 0:
        pytest.skip("test database container is not running")

    orphan = f"lumios_test_orphan_{uuid.uuid4().hex[:8]}"
    keep = conftest._default_test_db_name()
    with psycopg.connect(dbname="postgres", autocommit=True, **_params()) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(orphan)))
    try:
        # the current worktree's database must exist so we can check it survives
        os.environ.setdefault("POSTGRES_DB", keep)
        conftest._ensure_test_database_exists()
        result = subprocess.run(
            [SCRIPT, "cleanup"], capture_output=True, text=True, cwd=os.path.dirname(SCRIPT)
        )
        assert result.returncode == 0, result.stderr
        assert f"dropped {orphan}" in result.stdout
        assert not _database_exists(orphan)
        assert _database_exists(keep)
        assert _database_exists("lumios_test")
    finally:
        _drop(orphan)
