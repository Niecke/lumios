import secrets
from flask import Blueprint, current_app, request, jsonify, g, redirect
from jwt import PyJWKClient
import jwt
from urllib.parse import urlencode
from main import limiter
from config import GOOGLE_FRONTEND_CLIENT_ID, REDIS_URL
from services.auth import login_google, AuthError
from services.token import create_token
from security import require_api_auth, require_api_role
from models import db, User
from sqlalchemy import select

auth_api = Blueprint("auth_api", __name__, url_prefix="/auth")

# JWKS client for verifying Google ID tokens — keys are cached automatically.
# Works with any OIDC provider: swap the URI and issuer to support others.
# Timeout prevents the first request from hanging if Google is unreachable.
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_google_jwks = PyJWKClient(_GOOGLE_JWKS_URI, cache_keys=True, timeout=5)


@auth_api.route("/me")
@require_api_auth
@require_api_role("photographer")
def me():
    payload = g.token_payload
    user = db.session.execute(
        select(User).filter_by(id=int(payload["sub"]))
    ).scalar_one_or_none()
    result = {
        "email": payload["email"],
        "roles": payload["roles"],
        "max_libraries": user.max_libraries if user else None,
    }
    if payload.get("name"):
        result["name"] = payload["name"]
    if payload.get("picture"):
        result["picture"] = payload["picture"]
    return jsonify(result)


@auth_api.route("/google/verify", methods=["POST"])
@limiter.limit("5 per minute")
def google_verify():
    """Verify a Google ID token obtained directly by the frontend via GIS.

    The frontend performs the full OAuth dance with Google and passes the
    resulting credential (an ID token JWT) here. We verify it with Google's
    public JWKS — no backend redirect to Google is required.
    """
    if not GOOGLE_FRONTEND_CLIENT_ID:
        return jsonify({"error": "Google login is not configured"}), 501

    data = request.get_json(silent=True) or {}
    credential = data.get("credential", "")
    if not credential:
        return jsonify({"error": "Missing credential"}), 400

    try:
        signing_key = _google_jwks.get_signing_key_from_jwt(credential)
        idinfo = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=GOOGLE_FRONTEND_CLIENT_ID,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except jwt.PyJWTError:
        current_app.logger.warning("Invalid Google ID token submitted")
        return jsonify({"error": "Invalid Google token"}), 401
    except Exception:
        current_app.logger.exception("JWKS verification failed (network/timeout)")
        return jsonify({"error": "Could not verify Google token"}), 503

    try:
        user = login_google({"email": idinfo.get("email"), "sub": idinfo.get("sub")})
    except AuthError as e:
        current_app.logger.warning("Google login rejected: %s", e.message)
        return jsonify({"error": e.message}), e.status

    roles = [r.name for r in user.roles]
    token = create_token(
        user.id,
        user.email,
        roles,
        name=idinfo.get("name"),
        picture=idinfo.get("picture"),
    )
    return jsonify(
        {
            "token": token,
            "email": user.email,
            "roles": roles,
            "max_libraries": user.max_libraries,
        }
    )


def _store_login_code(token: str) -> str:
    """Store a JWT under a random one-time code in Redis (TTL 60s).

    Falls back to an in-memory dict when Redis is unavailable (local dev).
    """
    code = secrets.token_urlsafe(32)
    if REDIS_URL:
        import redis as _redis

        r = _redis.from_url(REDIS_URL)
        r.setex(f"login_code:{code}", 60, token)
    else:
        _login_codes[code] = token
    return code


def _consume_login_code(code: str) -> str | None:
    """Retrieve and delete a one-time login code. Returns the JWT or None."""
    if REDIS_URL:
        import redis as _redis

        r = _redis.from_url(REDIS_URL)
        pipe = r.pipeline()
        key = f"login_code:{code}"
        pipe.get(key)
        pipe.delete(key)
        token_bytes, _ = pipe.execute()
        return token_bytes.decode() if token_bytes else None
    return _login_codes.pop(code, None)


# In-memory fallback for local dev without Redis
_login_codes: dict[str, str] = {}


@auth_api.route("/google/callback", methods=["POST"])
@limiter.limit("5 per minute")
def google_callback():
    """Handle the GIS redirect flow.

    Google POSTs the credential as a form field. We verify it, create a JWT,
    store it under a short-lived one-time code, and redirect back to the
    frontend with ?code=... so the SPA can exchange it for the JWT via POST.
    """
    if not GOOGLE_FRONTEND_CLIENT_ID:
        return jsonify({"error": "Google login is not configured"}), 501

    credential = request.form.get("credential", "")
    if not credential:
        return redirect("/login?" + urlencode({"error": "Missing credential"}))

    try:
        signing_key = _google_jwks.get_signing_key_from_jwt(credential)
        idinfo = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=GOOGLE_FRONTEND_CLIENT_ID,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except jwt.PyJWTError:
        current_app.logger.warning("Invalid Google ID token in callback")
        return redirect("/login?" + urlencode({"error": "Invalid Google token"}))
    except Exception:
        current_app.logger.exception("JWKS verification failed in callback")
        return redirect(
            "/login?" + urlencode({"error": "Could not verify Google token"})
        )

    try:
        user = login_google({"email": idinfo.get("email"), "sub": idinfo.get("sub")})
    except AuthError as e:
        current_app.logger.warning("Google login rejected: %s", e.message)
        return redirect("/login?" + urlencode({"error": e.message}))

    roles = [r.name for r in user.roles]
    token = create_token(
        user.id,
        user.email,
        roles,
        name=idinfo.get("name"),
        picture=idinfo.get("picture"),
    )
    code = _store_login_code(token)
    return redirect("/login?" + urlencode({"code": code}))


@auth_api.route("/exchange", methods=["POST"])
@limiter.limit("10 per minute")
def exchange_code():
    """Exchange a one-time login code for a JWT.

    The code is consumed on first use and expires after 60 seconds.
    """
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    if not code:
        return jsonify({"error": "Missing code"}), 400

    token = _consume_login_code(code)
    if not token:
        return jsonify({"error": "Invalid or expired code"}), 401

    return jsonify({"token": token})
