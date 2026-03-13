from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from sqlalchemy import select
from models import db, User, Role
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
        account_type = request.form.get('account_type', 'local')
        active = 'active' in request.form

        if account_type not in ('local', 'google'):
            flash('Invalid account type.', 'error')
            return render_template('admin/user_create.html', email=email)

        # Check if user exists
        if db.session.execute(select(User).where(User.email == email)).scalar_one_or_none():
            flash('Email already exists!', 'error')
            return render_template('admin/user_create.html', email=email)

        user = User(email=email, active=active, account_type=account_type)

        if account_type == 'local':
            password = request.form.get('password', '')
            try:
                user.set_password(password)
            except ValueError as ex:
                flash(str(ex), 'error')
                return render_template('admin/user_create.html', email=email)

        db.session.add(user)
        db.session.commit()

        current_app.logger.info('User created: %s (%s)', email, account_type, extra={'log_type': 'audit'})
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

    all_roles = db.session.execute(select(Role)).scalars().all()

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        active = 'active' in request.form
        selected_role_ids = set(int(r) for r in request.form.getlist('roles'))

        changes = []
        if password:
            try:
                user.set_password(password)
            except ValueError as ex:
                flash(str(ex), 'error')
                return render_template('admin/user_edit.html', user=user, all_roles=all_roles)
            changes.append('password')

        if active != user.active:
            changes.append(f'active={active}')
        user.active = active

        new_roles = [r for r in all_roles if r.id in selected_role_ids]
        if set(r.id for r in user.roles) != selected_role_ids:
            changes.append('roles')
        user.roles = new_roles

        db.session.commit()

        current_app.logger.info(
            'User updated: %s (changed: %s)', user.email, ', '.join(changes) or 'none',
            extra={'log_type': 'audit'},
        )
        flash(f'User "{user.email}" updated successfully!', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/user_edit.html', user=user, all_roles=all_roles)



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