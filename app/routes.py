from flask import Blueprint, session, request, redirect, url_for, render_template, flash, current_app
from models import db, User
from sqlalchemy import select
from security import login_required
from main import limiter

bp = Blueprint('main', __name__)

@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
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
            return redirect(url_for('main.index'))
        else:
            current_app.logger.warning('Login failed: %s', email or '<no email>', extra={'log_type': 'audit'})
            flash('Invalid email or password')

    return render_template('login.html')

@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Logged out successfully')
    return redirect(url_for('main.index'))
