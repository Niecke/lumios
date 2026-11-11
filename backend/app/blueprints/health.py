from flask import Blueprint, current_app
from models import db
from sqlalchemy import text
from services.redis_client import get_redis
from services.schema import schema_status
from config import GIT_HASH, APP_VERSION, BUILD_TIMESTAMP

health = Blueprint("health", __name__)


def _ping_db() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception as ex:
        current_app.logger.error("DB ping failed: %s", ex)
        return False


def _ping_redis() -> bool:
    r = get_redis()
    if r is None:
        return True
    try:
        return r.ping()
    except Exception as ex:
        current_app.logger.error("Redis ping failed: %s", ex)
        return False


@health.route("/health")
def healthcheck():
    healthy = _ping_db() and _ping_redis()
    status = "healthy" if healthy else "unhealthy"
    code = 200 if healthy else 503
    return {"status": status}, code


# Missing revisions of the last failing check, so the warning is logged once per
# process and per change of state instead of on every probe.
_last_logged_missing: tuple[str, ...] = ()


def _check_schema():
    """The schema status, or None when the database cannot answer."""
    try:
        return schema_status(db.session.connection())
    except Exception as ex:
        db.session.rollback()
        current_app.logger.error("Schema check failed: %s", ex)
        return None


def _log_schema_state(status) -> None:
    global _last_logged_missing
    if status.ready:
        if _last_logged_missing:
            current_app.logger.info("Database schema ready: %s", status.describe())
            _last_logged_missing = ()
    elif status.missing != _last_logged_missing:
        current_app.logger.warning("Database schema not ready: %s", status.describe())
        _last_logged_missing = status.missing


@health.route("/health/ready")
def readiness():
    """Readiness: /health plus a schema at or past this code's head.

    Only for the readiness probe. Liveness and startup stay on /health or a
    socket, so a missing schema never restarts the pod. The body carries no
    revision ids; the log does.
    """
    if not (_ping_db() and _ping_redis()):
        return {"status": "unhealthy"}, 503
    status = _check_schema()
    if status is None:
        return {"status": "unhealthy"}, 503
    _log_schema_state(status)
    if not status.ready:
        return {"status": "schema_not_ready"}, 503
    return {"status": "healthy"}, 200


@health.route("/version")
@health.route("/version.json")
def version():
    return {"commit": GIT_HASH, "version": APP_VERSION, "built_at": BUILD_TIMESTAMP}
