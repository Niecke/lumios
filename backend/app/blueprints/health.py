from flask import Blueprint, current_app
from config import REDIS_URL
from models import db
from sqlalchemy import text

health = Blueprint("health", __name__)


def _ping_db() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception as ex:
        current_app.logger.error("DB ping failed: %s", ex)
        return False


def _ping_redis() -> bool:
    if not REDIS_URL:
        return True
    try:
        import redis

        r = redis.from_url(REDIS_URL, socket_connect_timeout=2)
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
