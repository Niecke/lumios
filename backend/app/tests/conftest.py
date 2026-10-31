"""
Shared pytest fixtures for the lumios-backend test suite.

Environment variables must be set BEFORE any app module is imported,
because config.py has a fail-fast check at module load time.
"""

import os
import sys

# --- Env vars must come first, before any app imports ---
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "lumios")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_DB", "lumios_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DEBUG", "true")  # disables Talisman HTTPS enforcement
os.environ.setdefault("MIN_PASSWORD_LENGTH", "8")

# Use minimal Argon2 parameters so password hashing is fast in tests
os.environ.setdefault("PASSWORD_HASHER_TIME_COST", "1")
os.environ.setdefault("PASSWORD_HASHER_MEMORY_COST", "8")
os.environ.setdefault("PASSWORD_HASHER_PARALLELISM", "1")

# Add the app package to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "migrations"))

# --- Now it is safe to import from the app ---
import psycopg
import pytest
from flask_migrate import upgrade
from psycopg import sql
from sqlalchemy import text

from main import create_app
from models import db as _db, User, Role


def _ensure_test_database_exists():
    """Create the test database if the PostgreSQL server does not have it yet."""
    params = dict(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )
    dbname = os.environ["POSTGRES_DB"]
    if not dbname.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against database {dbname!r}: the suite drops "
            "the whole public schema, so POSTGRES_DB must end in '_test' "
            "(default: lumios_test)."
        )
    try:
        psycopg.connect(dbname=dbname, **params).close()
        return
    except psycopg.OperationalError as exc:
        if exc.sqlstate != "3D000":  # invalid_catalog_name: database missing
            raise RuntimeError(
                f"Cannot reach PostgreSQL at {params['host']}:{params['port']} "
                f"({exc}).\nStart the throwaway test database with "
                "`./scripts/test-db.sh start` (or `podman compose --profile test "
                "up -d postgres-test`), or point POSTGRES_HOST/POSTGRES_PORT at a "
                "running server."
            ) from exc
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def _reset_schema():
    _db.session.remove()
    _db.engine.dispose()
    with _db.engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")


def _close_worker_pool():
    """Close Procrastinate's sync pool, or it fails at interpreter shutdown."""
    try:
        import worker

        worker.close_worker_app()
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus):
    _close_worker_pool()


@pytest.fixture(scope="session")
def app():
    """Create and configure the Flask application once for the entire test session.

    - Connects to a real PostgreSQL (see scripts/test-db.sh); the database is
      created on demand and the schema is built by running the Alembic migrations
    - CSRF and rate limiting are disabled for test convenience
    """
    _ensure_test_database_exists()

    # The database URI comes from config.py (POSTGRES_* env vars set above).
    test_app = create_app(
        test_config={
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            # Use filesystem sessions in /tmp – no Redis needed
            "SESSION_TYPE": "filesystem",
            "SESSION_FILE_DIR": "/tmp/flask_test_sessions",
        }
    )

    # Push a permanent app context so fixtures can access db.session directly
    ctx = test_app.app_context()
    ctx.push()
    _reset_schema()
    upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))

    yield test_app

    _close_worker_pool()
    _reset_schema()
    ctx.pop()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Delete all rows from every table between tests.

    Runs after every test function (autouse=True).
    The yield separates setup (none here) from teardown.
    """
    yield
    _db.session.remove()
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    # The job queue is not part of the models; its events go with the jobs.
    _db.session.execute(text("DELETE FROM procrastinate_jobs"))
    _db.session.commit()


@pytest.fixture(autouse=True)
def reset_login_failures():
    """Forget failed-login counters so tests do not block each other."""
    from services import login_protection

    login_protection._in_memory_failures.clear()
    yield
    login_protection._in_memory_failures.clear()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Reusable data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_role():
    role = Role(name="admin", description="Administrator")
    _db.session.add(role)
    _db.session.commit()
    return role


@pytest.fixture
def admin_user(admin_role):
    user = User(email="admin@test.com", active=True)
    user.set_password("AdminPass123!")
    user.roles.append(admin_role)
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def regular_user():
    user = User(email="user@test.com", active=True)
    user.set_password("UserPass123!")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def inactive_user():
    user = User(email="inactive@test.com", active=False)
    user.set_password("InactivePass123!")
    _db.session.add(user)
    _db.session.commit()
    return user


# ---------------------------------------------------------------------------
# Helper functions (not fixtures) used across multiple test modules
# ---------------------------------------------------------------------------


def do_login(client, email, password):
    """POST to /login and follow the redirect."""
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def do_logout(client):
    """POST to /logout and follow the redirect."""
    return client.post("/logout", follow_redirects=True)
