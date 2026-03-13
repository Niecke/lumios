from flask_sqlalchemy import SQLAlchemy
from password_handler import hash_password, password_hasher
from argon2.exceptions import VerifyMismatchError
from config import MIN_PASSWORD_LENGTH
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)

db = SQLAlchemy()

roles_users = db.Table('roles_users',
    db.Column('user_id', db.Integer(), db.ForeignKey('user.id')),
    db.Column('role_id', db.Integer(), db.ForeignKey('role.id')),
    db.Index('ix_roles_users_user_id', 'user_id'),
    db.Index('ix_roles_users_role_id', 'role_id'),
)

class Role(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))

class User(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean())
    roles = db.relationship('Role', secondary=roles_users, backref=db.backref('users', lazy='dynamic'))

    def is_authenticated(self):
        """Returns True if user is active"""
        return self.active
    
    def set_password(self, password):
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password needs to be longer than {MIN_PASSWORD_LENGTH}")
        self.password = hash_password(password)

    def verify_password(self, password):
        try:
            password_hasher.verify(self.password, password)
        except VerifyMismatchError:
            return False
        if password_hasher.check_needs_rehash(self.password):
            self.set_password(password)
            db.session.commit()
        return True

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    # LargeBinary(length>16777215) maps to LONGBLOB in MySQL (up to 4 GB)
    data = db.Column(db.LargeBinary(length=4294967295), nullable=False)
    thumbnail = db.Column(db.LargeBinary(length=4294967295), nullable=True)
    thumbnail_content_type = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user = db.relationship('User', backref=db.backref('documents', lazy=True))