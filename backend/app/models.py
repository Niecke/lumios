from flask_sqlalchemy import SQLAlchemy
from password_handler import hash_password, password_hasher
from argon2.exceptions import VerifyMismatchError
from config import MIN_PASSWORD_LENGTH
from datetime import datetime, timezone
from flask_migrate import Migrate
import uuid as uuid_module

db = SQLAlchemy()
migrate = Migrate()

roles_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
    db.Column("role_id", db.Integer(), db.ForeignKey("role.id")),
    db.Index("ix_roles_users_user_id", "user_id"),
    db.Index("ix_roles_users_role_id", "role_id"),
)


class Role(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))


class User(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    active = db.Column(db.Boolean(), nullable=False, default=True)
    account_type = db.Column(db.String(16), nullable=False, default="local")
    auth_string = db.Column(db.String(255), nullable=True)
    max_libraries = db.Column(db.Integer(), nullable=False, default=100)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    deleted_at = db.Column(db.DateTime, nullable=True)
    is_system = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    )

    @property
    def is_authenticated(self):
        return self.active and self.deleted_at is None

    def set_password(self, password):
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password needs to be longer than {MIN_PASSWORD_LENGTH}")
        self.account_type = "local"
        self.auth_string = hash_password(password)

    def verify_password(self, password):
        if self.account_type != "local" or not self.auth_string:
            return False
        try:
            password_hasher.verify(self.auth_string, password)
        except VerifyMismatchError:
            return False
        if password_hasher.check_needs_rehash(self.auth_string):
            self.set_password(password)
            db.session.commit()
        return True


class Library(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid_module.uuid4()),
    )
    user_id = db.Column(db.Integer(), db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    archived_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    photographer = db.relationship(
        "User", backref=db.backref("libraries", lazy="dynamic")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "uuid": self.uuid,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }
