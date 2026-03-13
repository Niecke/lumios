from flask import session, redirect, url_for, flash
from functools import wraps
from current_user import current_user

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def require_role(role_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in first.', 'error')
                return redirect(url_for('auth.login'))
            
            if not current_user.has_role(role_name):
                flash(f'Role "{role_name}" required!', 'error')
                return redirect(url_for('admin.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator