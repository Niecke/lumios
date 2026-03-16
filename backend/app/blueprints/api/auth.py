from flask import Blueprint, current_app, request, jsonify, g, redirect
from jwt import PyJWKClient
import jwt
from urllib.parse import urlencode
from main import limiter
from config import GOOGLE_FRONTEND_CLIENT_ID
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
        return jsonify({"error": "Invalid Google token"}), 401
    except Exception:
        # Covers network errors when fetching JWKS (e.g. timeout, DNS failure)
        return jsonify({"error": "Could not verify Google token"}), 503

    try:
        user = login_google({"email": idinfo.get("email"), "sub": idinfo.get("sub")})
    except AuthError as e:
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


@auth_api.route("/google/callback", methods=["POST"])
@limiter.limit("5 per minute")
def google_callback():
    """Handle the GIS redirect flow.

    Google POSTs the credential as a form field. We verify it, create a JWT,
    and redirect back to the frontend login page with the token as a query
    parameter so the SPA can pick it up.
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
    return redirect("/login?" + urlencode({"token": token}))
