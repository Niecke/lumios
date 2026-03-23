from flask import Blueprint

api = Blueprint("api", __name__, url_prefix="/api/v1")

from .auth import auth_api  # noqa: E402
from .libraries import libraries_api  # noqa: E402
from .images import images_api  # noqa: E402
from .public import public_api  # noqa: E402
from .notifications import notifications_api  # noqa: E402
from .support import support_api  # noqa: E402

api.register_blueprint(auth_api)
api.register_blueprint(libraries_api)
api.register_blueprint(images_api)
api.register_blueprint(public_api)
api.register_blueprint(notifications_api)
api.register_blueprint(support_api)
