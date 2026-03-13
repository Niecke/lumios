from flask import Blueprint, current_app
from models import db
from sqlalchemy import text

health = Blueprint('health', __name__)

def _ping_db():
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception as ex:
        current_app.logger.error(f"DB ping failed: {ex}")
        return False

@health.route('/health')
def healthcheck():
    is_connected = _ping_db()
    return {
        'status': 'healthy' if is_connected else 'unhealthy',
        'database': 'connected' if is_connected else 'disconnected',
    }
