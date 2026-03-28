import secrets
from flask import Blueprint, current_app, request, jsonify, g, redirect
from jwt import PyJWKClient
import jwt
from urllib.parse import urlencode
from main import limiter
from config import GOOGLE_FRONTEND_CLIENT_ID, REDIS_URL, FRONTEND_URL, MAX_USERS
from services.auth import login_google, login_password, AuthError
from services.token import create_token
from services.mail import notify_activation_email
from services.audit import write_audit_log
from security import require_api_auth, require_api_role
from models import db, User, Role, Library, Image, AuditLogType
from sqlalchemy import select, func, or_
from datetime import datetime, timezone

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
    user_id = int(payload["sub"])
    user = db.session.execute(select(User).filter_by(id=user_id)).scalar_one_or_none()

    storage_used = db.session.execute(
        select(db.func.coalesce(db.func.sum(Image.size), 0))
        .join(Image.library)
        .where(
            Library.user_id == user_id,
            Image.deleted_at.is_(None),
            Library.deleted_at.is_(None),
        )
    ).scalar()

    limits = user.effective_limits if user else {}
    result = {
        "email": payload["email"],
        "created_at": user.created_at.isoformat() if user else None,
        "account_type": user.account_type if user else None,
        "subscription": user.subscription.value if user else None,
        "storage_used_bytes": storage_used,
        "storage_limit_bytes": limits.get("max_storage_bytes"),
        "max_libraries": limits.get("max_libraries"),
        "max_images_per_library": limits.get("max_images_per_library"),
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
        write_audit_log(AuditLogType.login_failed)
        db.session.commit()
        return jsonify({"error": e.message}), e.status

    roles = [r.name for r in user.roles]
    token = create_token(
        user.id,
        user.email,
        roles,
        name=idinfo.get("name"),
        picture=idinfo.get("picture"),
    )
    write_audit_log(AuditLogType.login_frontend, creator_id=user.id)
    db.session.commit()
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
        write_audit_log(AuditLogType.login_failed)
        db.session.commit()
        return redirect("/login?" + urlencode({"error": e.message}))

    roles = [r.name for r in user.roles]
    token = create_token(
        user.id,
        user.email,
        roles,
        name=idinfo.get("name"),
        picture=idinfo.get("picture"),
    )
    write_audit_log(AuditLogType.login_frontend, creator_id=user.id)
    db.session.commit()
    code = _store_login_code(token)
    return redirect("/login?" + urlencode({"code": code}))


@auth_api.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def password_login():
    """Authenticate with email and password, return a lumios JWT."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    try:
        user = login_password(email, password)
    except AuthError as e:
        write_audit_log(AuditLogType.login_failed)
        db.session.commit()
        return jsonify({"error": e.message}), e.status

    roles = [r.name for r in user.roles]
    token = create_token(user.id, user.email, roles)
    write_audit_log(AuditLogType.login_frontend, creator_id=user.id)
    db.session.commit()
    return jsonify(
        {
            "token": token,
            "email": user.email,
            "roles": roles,
            "max_libraries": user.max_libraries,
            "account_type": user.account_type,
        }
    )


@auth_api.route("/change_password", methods=["POST"])
@require_api_auth
@limiter.limit("5 per minute")
def change_password():
    """Change password for the authenticated local account."""
    user_id = int(g.token_payload["sub"])
    user = db.session.get(User, user_id)
    if not user or user.account_type != "local":
        return (
            jsonify({"error": "Password change is only available for local accounts"}),
            400,
        )

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not current_password or not new_password:
        return jsonify({"error": "Current and new passwords are required"}), 400

    if not user.verify_password(current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    try:
        user.set_password(new_password)
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400

    db.session.commit()
    current_app.logger.info(
        "Password changed: %s (self)", user.email, extra={"log_type": "audit"}
    )
    return jsonify({"ok": True})


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


def _check_registration_open() -> tuple[bool, str]:
    """Return (ok, error_message). ok=True when registration is open.

    Counts both active users and activation-pending users so that a pending
    slot cannot be stolen: if user A registers and hasn't activated yet,
    user B cannot push them out by filling the last slot.
    """
    slot_count = db.session.execute(
        select(func.count(User.id)).where(
            or_(User.active.is_(True), User.activation_pending.is_(True)),
            User.deleted_at.is_(None),
        )
    ).scalar()
    if slot_count >= MAX_USERS:
        return False, "Registration is currently closed"
    return True, ""


def _create_pending_user(email: str, account_type: str, auth_string: str | None) -> User:
    """Create an inactive, activation-pending user and return it (not yet committed)."""
    activation_token = secrets.token_urlsafe(32)
    photographer_role = db.session.execute(
        select(Role).where(Role.name == "photographer")
    ).scalar_one_or_none()
    user = User(
        email=email,
        active=False,
        activation_pending=True,
        activation_token=activation_token,
        account_type=account_type,
        auth_string=auth_string,
    )
    if photographer_role:
        user.roles = [photographer_role]
    db.session.add(user)
    return user


@auth_api.route("/register", methods=["POST"])
@limiter.limit("3 per minute")
def register():
    """Register a new local user account.

    The account is created inactive with a pending activation token.
    An activation email is sent; the user must click the link before logging in.
    """
    ok, err = _check_registration_open()
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not data.get("agb_accepted"):
        return jsonify({"error": "You must accept the Terms of Service and Privacy Policy"}), 400

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    if db.session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    ).scalar_one_or_none():
        return jsonify({"error": "An account with this email already exists"}), 409

    user = _create_pending_user(email, "local", None)
    try:
        user.set_password(password)
    except ValueError as ex:
        db.session.rollback()
        return jsonify({"error": str(ex)}), 400

    write_audit_log(
        AuditLogType.user_created,
        related_object_type="user",
        related_object_id=str(user.id),
    )
    db.session.commit()
    notify_activation_email(email, f"{FRONTEND_URL}/activate?token={user.activation_token}")
    current_app.logger.info("User registered: %s (local)", email, extra={"log_type": "audit"})
    return jsonify({"ok": True}), 201


@auth_api.route("/google/register", methods=["POST"])
@limiter.limit("5 per minute")
def google_register():
    """Register a new Google account.

    The frontend verifies the GIS credential and POSTs it here together with
    explicit AGB/Datenschutz consent. A new inactive user is created and an
    activation email is sent.
    """
    if not GOOGLE_FRONTEND_CLIENT_ID:
        return jsonify({"error": "Google login is not configured"}), 501

    data = request.get_json(silent=True) or {}

    if not data.get("agb_accepted"):
        return jsonify({"error": "You must accept the Terms of Service and Privacy Policy"}), 400

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
        current_app.logger.warning("Invalid Google ID token in register")
        return jsonify({"error": "Invalid Google token"}), 401
    except Exception:
        current_app.logger.exception("JWKS verification failed in register")
        return jsonify({"error": "Could not verify Google token"}), 503

    email = (idinfo.get("email") or "").lower()
    google_sub = idinfo.get("sub")

    if not email:
        return jsonify({"error": "Could not get email from Google"}), 400

    ok, err = _check_registration_open()
    if not ok:
        return jsonify({"error": err}), 403

    if db.session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    ).scalar_one_or_none():
        return jsonify({"error": "An account with this email already exists. Please log in instead."}), 409

    user = _create_pending_user(email, "google", google_sub)
    write_audit_log(
        AuditLogType.user_created,
        related_object_type="user",
        related_object_id=str(user.id),
    )
    db.session.commit()
    notify_activation_email(email, f"{FRONTEND_URL}/activate?token={user.activation_token}")
    current_app.logger.info("User registered: %s (google)", email, extra={"log_type": "audit"})
    return jsonify({"ok": True}), 201


@auth_api.route("/activate", methods=["POST"])
@limiter.limit("10 per minute")
def activate_account():
    """Activate a user account using the token from the activation email."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Missing activation token"}), 400

    user = db.session.execute(
        select(User).where(User.activation_token == token)
    ).scalar_one_or_none()

    if not user:
        return jsonify({"error": "Invalid or expired activation token"}), 404

    user.active = True
    user.activation_pending = False
    user.activation_token = None
    write_audit_log(
        AuditLogType.user_activated,
        related_object_type="user",
        related_object_id=str(user.id),
    )
    db.session.commit()

    current_app.logger.info(
        "Account activated: %s", user.email, extra={"log_type": "audit"}
    )
    return jsonify({"ok": True, "email": user.email})
