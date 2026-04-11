from flask import Blueprint, current_app
from models import db
from sqlalchemy import text
from services.redis_client import get_redis

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
