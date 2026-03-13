from flask import Blueprint, request, jsonify, redirect, g
from main import limiter, oauth
from config import GOOGLE_CLIENT_ID, PUBLIC_BASE_URL, FRONTEND_URL
from services.auth import login_password, login_google, AuthError
from services.token import create_token
from security import require_api_auth

auth_api = Blueprint("auth_api", __name__, url_prefix="/auth")


def _token_response(user):
    roles = [r.name for r in user.roles]
    token = create_token(user.id, user.email, roles)
    return jsonify({"token": token, "email": user.email, "roles": roles})


@auth_api.route("/login", methods=["POST"])
@limiter.limit("2 per second")
def login():
    data = request.get_json(silent=True) or {}
    try:
        user = login_password(data.get("email", "").strip(), data.get("password", ""))
    except AuthError as e:
        return jsonify({"error": e.message}), e.status
    return _token_response(user)


@auth_api.route("/me")
@require_api_auth
def me():
    payload = g.token_payload
    return jsonify({"email": payload["email"], "roles": payload["roles"]})


@auth_api.route("/google")
def google_login():
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google login is not configured"}), 501
    redirect_uri = PUBLIC_BASE_URL.rstrip("/") + "/api/v1/auth/google/callback"
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")


@auth_api.route("/google/callback")
def google_callback():
    try:
        oauth_token = oauth.google.authorize_access_token()
    except Exception:
        return redirect(f"{FRONTEND_URL}/login?error=google_failed")

    userinfo = oauth_token.get("userinfo")
    if not userinfo:
        return redirect(f"{FRONTEND_URL}/login?error=google_failed")

    try:
        user = login_google(userinfo)
    except AuthError as e:
        return redirect(f"{FRONTEND_URL}/login?error={e.message}")

    roles = [r.name for r in user.roles]
    jwt_token = create_token(user.id, user.email, roles)
    return redirect(f"{FRONTEND_URL}/login#token={jwt_token}")
