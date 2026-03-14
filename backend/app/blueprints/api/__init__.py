from flask import Blueprint

api = Blueprint("api", __name__, url_prefix="/api/v1")

from .auth import auth_api  # noqa: E402
from .libraries import libraries_api  # noqa: E402

api.register_blueprint(auth_api)
api.register_blueprint(libraries_api)
