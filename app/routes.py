from flask import Blueprint, session, request, redirect, url_for, render_template, flash, current_app
from models import db, User
from sqlalchemy import text, select
from security import login_required
from main import limiter

bp = Blueprint('main', __name__)

def ping_db():
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception as ex:
        current_app.logger.error(f"DB ping failed: {ex}")
        return False

@bp.route('/health')
def health():
    is_connected = ping_db()
    return {
        'status': 'healthy' if is_connected else 'unhealthy',
        'database': 'connected' if is_connected else 'disconnected',
    }

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
        if user and user.is_authenticated() and user.verify_password(password):
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
