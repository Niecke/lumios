from flask import Blueprint, session, request, redirect, url_for, render_template, flash, current_app
from models import db, User
from sqlalchemy import select
from main import limiter

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

    return render_template('login.html')

@auth.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Logged out successfully')
    return redirect(url_for('admin.index'))
