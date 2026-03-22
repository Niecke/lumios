from flask import redirect, url_for, flash, request, jsonify, g, current_app
from functools import wraps
from current_user import current_user
import jwt
from services.token import decode_token


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function


def require_role(role_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))

            if not current_user.has_role(role_name):
                flash("Access denied.", "error")
                return redirect(url_for("auth.login"))

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_api_auth(f):
    """JWT Bearer token auth for the JSON API. Sets g.token_payload on success.

    After decoding the token, the user is loaded from the database to verify
    they are still active and to refresh their roles (so that role changes
    and deactivations take effect immediately, not after token expiry).
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import db, User

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth_header[len("Bearer ") :]
        try:
            g.token_payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            current_app.logger.warning("Expired JWT from %s", request.remote_addr)
            return jsonify({"error": "Token expired"}), 401
        except jwt.PyJWTError:
            current_app.logger.warning("Invalid JWT from %s", request.remote_addr)
            return jsonify({"error": "Invalid token"}), 401

        user = db.session.get(User, int(g.token_payload["sub"]))
        if not user or not user.is_authenticated:
            return jsonify({"error": "Account deactivated"}), 401

        # Refresh roles from the database so require_api_role checks live state
        g.token_payload["roles"] = [r.name for r in user.roles]

        return f(*args, **kwargs)

    return decorated_function


def require_api_role(role_name):
    """JWT role check for the JSON API. Must be used after @require_api_auth."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            payload = getattr(g, "token_payload", None)
            if not payload:
                return jsonify({"error": "Unauthorized"}), 401
            if role_name not in payload.get("roles", []):
                return jsonify({"error": "Forbidden"}), 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator
