from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from sqlalchemy import select
from models import db, User
from security import login_required, require_role

admin = Blueprint('admin', __name__)

@admin.route('/')
@login_required
@require_role('admin')
def index():
    return render_template('index.html')

@admin.route('/admin/dashboard', methods=['GET', 'POST'])
@login_required
@require_role('admin')
def dashboard():
    users = db.session.execute(select(User)).scalars().all()
    return render_template('admin/dashboard.html', users=users)


@admin.route('/admin/user_create', methods=['GET', 'POST'])
@login_required
@require_role('admin')
def user_create():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        active = 'active' in request.form
        
        # Check if user exists
        if db.session.execute(select(User).where(User.email == email)).scalar_one_or_none():
            flash('Email already exists!', 'error')
            return render_template('admin/user_create.html')
        
        user = User(
            email=email,
            active=active,
        )
        try:
            user.set_password(password)
        except ValueError as ex:
            flash(str(ex), 'error')
            return render_template('admin/user_create.html', email=email)
        
        db.session.add(user)
        db.session.commit()

        current_app.logger.info('User created: %s', email, extra={'log_type': 'audit'})
        flash(f'User "{email}" created successfully!', 'success')
        return redirect(url_for('admin.dashboard'))
    
    return render_template('admin/user_create.html')



@admin.route('/admin/user_edit/<int:id>', methods=['GET', 'POST'])
@login_required
@require_role('admin')
def user_edit(id):
    user = db.session.get(User, id)

    if not user:
        flash(f'User ID "{id}" unknown!', 'error')
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        active = 'active' in request.form

        changes = []
        if password:
            try:
                user.set_password(password)
            except ValueError as ex:
                flash(str(ex), 'error')
                return render_template('admin/user_edit.html', user=user)
            changes.append('password')

        if active != user.active:
            changes.append(f'active={active}')

        user.active = active
        db.session.commit()

        current_app.logger.info(
            'User updated: %s (changed: %s)', user.email, ', '.join(changes) or 'none',
            extra={'log_type': 'audit'},
        )
        flash(f'User "{user.email}" updated successfully!', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/user_edit.html', user=user)



@admin.route('/admin/user_delete/<int:id>', methods=['POST'])
@login_required
@require_role('admin')
def user_delete(id):
    user = db.session.get(User, id)

    if not user:
        flash(f'User ID "{id}" unknown!', 'error')
        return redirect(url_for('admin.dashboard'))

    if user.email == "admin":
        flash(f'The internal admin user can not be deleted!', 'error')
        return redirect(url_for('admin.dashboard'))

    db.session.delete(user)
    db.session.commit()

    current_app.logger.info('User deleted: %s', user.email, extra={'log_type': 'audit'})
    flash(f'User "{user.email}" deleted!', 'success')
    return redirect(url_for('admin.dashboard'))