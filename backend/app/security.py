from flask import session, redirect, url_for, flash, request, jsonify, g
from functools import wraps
from current_user import current_user
import jwt
from services.token import decode_token


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function


def require_role(role_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in first.", "error")
                return redirect(url_for("auth.login"))

            if not current_user.has_role(role_name):
                flash("Access denied.", "error")
                return redirect(url_for("auth.login"))

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_api_auth(f):
    """JWT Bearer token auth for the JSON API. Sets g.token_payload on success."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth_header[len("Bearer ") :]
        try:
            g.token_payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.PyJWTError:
            return jsonify({"error": "Invalid token"}), 401
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
