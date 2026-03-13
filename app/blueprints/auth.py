from flask import Blueprint, session, request, redirect, url_for, render_template, flash, current_app
from models import db, User
from sqlalchemy import select
from main import limiter, oauth
from config import GOOGLE_CLIENT_ID

auth = Blueprint('auth', __name__)


@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("2 per second")
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()
        if user and user.is_authenticated and user.verify_password(password):
            session.clear()
            session['user_id'] = user.id
            session['email'] = user.email
            current_app.logger.info('Login successful: %s', email, extra={'log_type': 'audit'})
            return redirect(url_for('admin.index'))
        else:
            current_app.logger.warning('Login failed: %s', email or '<no email>', extra={'log_type': 'audit'})
            flash('Invalid email or password')

    return render_template('login.html', google_enabled=bool(GOOGLE_CLIENT_ID))


@auth.route('/auth/google')
def google_login():
    if not GOOGLE_CLIENT_ID:
        flash('Google login is not configured.', 'error')
        return redirect(url_for('auth.login'))
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, prompt='select_account')


@auth.route('/auth/callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        session.clear()
        flash('Google login failed. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    userinfo = token.get('userinfo')
    if not userinfo:
        session.clear()
        flash('Google login failed. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    email = userinfo.get('email')
    google_sub = userinfo.get('sub')

    user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()

    if not user or user.account_type != 'google':
        session.clear()
        current_app.logger.warning('Google login rejected: %s', email, extra={'log_type': 'audit'})
        flash('No account found for this Google address. Contact an admin.', 'error')
        return redirect(url_for('auth.login'))

    if not user.is_authenticated:
        session.clear()
        flash('Account is inactive.', 'error')
        return redirect(url_for('auth.login'))

    # Store Google sub on first login, verify on subsequent logins
    if user.auth_string is None:
        user.auth_string = google_sub
        db.session.commit()
    elif user.auth_string != google_sub:
        session.clear()
        current_app.logger.warning('Google sub mismatch for: %s', email, extra={'log_type': 'audit'})
        flash('Google account mismatch. Contact an admin.', 'error')
        return redirect(url_for('auth.login'))

    session.clear()
    session['user_id'] = user.id
    session['email'] = user.email
    current_app.logger.info('Google login successful: %s', email, extra={'log_type': 'audit'})
    return redirect(url_for('admin.index'))


@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Logged out successfully')
    return redirect(url_for('admin.index'))
