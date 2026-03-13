from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    render_template,
    flash,
)
from main import limiter, oauth
from config import GOOGLE_CLIENT_ID, PUBLIC_BASE_URL
from services.auth import login_password, login_google, set_session, logout, AuthError

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("2 per second")
def login():
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        try:
            user = login_password(email, password)
            set_session(user)
            return redirect(url_for("admin.index"))
        except AuthError:
            flash("Invalid email or password")

    return render_template("login.html", google_enabled=bool(GOOGLE_CLIENT_ID))


@auth.route("/auth/google")
def google_login():
    if not GOOGLE_CLIENT_ID:
        flash("Google login is not configured.", "error")
        return redirect(url_for("auth.login"))
    redirect_uri = PUBLIC_BASE_URL.rstrip("/") + "/auth/callback"
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")


@auth.route("/auth/callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo")
    if not userinfo:
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    try:
        user = login_google(userinfo)
        set_session(user)
    except AuthError as e:
        flash(e.message, "error")
        return redirect(url_for("auth.login"))

    return redirect(url_for("admin.index"))


@auth.route("/logout", methods=["POST"])
def do_logout():
    logout()
    flash("Logged out successfully")
    return redirect(url_for("admin.index"))
