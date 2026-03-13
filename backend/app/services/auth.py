"""
Shared authentication logic used by both the SSR admin blueprint and the JSON API.
"""

from flask import session, current_app
from sqlalchemy import select
from models import db, User


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def login_password(email: str, password: str) -> User:
    """Verify credentials and return the User. Caller decides what to do with the session."""
    user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()
    if user and user.is_authenticated and user.verify_password(password):
        current_app.logger.info("Login: %s", email, extra={"log_type": "audit"})
        return user

    current_app.logger.warning(
        "Login failed: %s", email or "<none>", extra={"log_type": "audit"}
    )
    raise AuthError("Invalid email or password")


def login_google(userinfo: dict) -> User:
    """Verify Google userinfo and return the User. Caller decides what to do with the session."""
    email = userinfo.get("email")
    google_sub = userinfo.get("sub")

    user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()

    if not user or user.account_type != "google":
        current_app.logger.warning(
            "Google login rejected: %s", email, extra={"log_type": "audit"}
        )
        raise AuthError("No account found for this Google address")

    if not user.is_authenticated:
        raise AuthError("Account is inactive", status=403)

    if user.auth_string is None:
        user.auth_string = google_sub
        db.session.commit()
    elif user.auth_string != google_sub:
        current_app.logger.warning(
            "Google sub mismatch: %s", email, extra={"log_type": "audit"}
        )
        raise AuthError("Google account mismatch")

    current_app.logger.info("Google login: %s", email, extra={"log_type": "audit"})
    return user


def set_session(user: User) -> None:
    """Populate the Flask session (SSR admin blueprint only)."""
    session.clear()
    session["user_id"] = user.id
    session["email"] = user.email


def logout() -> None:
    session.clear()
