"""
Shared pytest fixtures for the doc-store-server test suite.

Environment variables must be set BEFORE any app module is imported,
because config.py has a fail-fast check at module load time.
"""
import os
import sys

# --- Env vars must come first, before any app imports ---
os.environ.setdefault("MYSQL_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DEBUG", "true")          # disables Talisman HTTPS enforcement
os.environ.setdefault("MIN_PASSWORD_LENGTH", "8")

# Use minimal Argon2 parameters so password hashing is fast in tests
os.environ.setdefault("PASSWORD_HASHER_TIME_COST", "1")
os.environ.setdefault("PASSWORD_HASHER_MEMORY_COST", "8")
os.environ.setdefault("PASSWORD_HASHER_PARALLELISM", "1")

# Add the app package to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# --- Now it is safe to import from the app ---
import pytest
from sqlalchemy.pool import StaticPool

from main import create_app
from models import db as _db, User, Role


@pytest.fixture(scope="session")
def app():
    """Create and configure the Flask application once for the entire test session.

    - SQLite in-memory database replaces MySQL (no external service needed)
    - StaticPool ensures all connections share the same in-memory database
    - CSRF and rate limiting are disabled for test convenience
    """
    test_app = create_app(
        test_config={
            "TESTING": True,
            # Replace MySQL with an in-memory SQLite database (no external service needed).
            # StaticPool ensures all connections share the same in-memory database.
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
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
    _db.create_all()

    yield test_app

    _db.drop_all()
    ctx.pop()


@pytest.fixture(autouse=True)
def clean_db():
    """Delete all rows from every table between tests.

    Runs after every test function (autouse=True).
    The yield separates setup (none here) from teardown.
    """
    yield
    _db.session.rollback()
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.commit()


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
