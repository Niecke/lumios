from flask_sqlalchemy import SQLAlchemy
from password_handler import hash_password, password_hasher
from argon2.exceptions import VerifyMismatchError
from config import MIN_PASSWORD_LENGTH
from datetime import datetime, timezone
from flask_migrate import Migrate
import enum
import uuid as uuid_module
from tracing import traced

db = SQLAlchemy()
migrate = Migrate()


class CustomerState(enum.Enum):
    none = "none"
    liked = "liked"


class NotificationType(enum.Enum):
    library_marked = "library_marked"


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
    max_images_per_library = db.Column(db.Integer(), nullable=False, default=500)
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

    @traced()
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
    finished_at = db.Column(db.DateTime, nullable=True)

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
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class Image(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid_module.uuid4()),
    )
    library_id = db.Column(db.Integer(), db.ForeignKey("library.id"), nullable=False)
    s3_key = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(32), nullable=False)
    size = db.Column(db.Integer(), nullable=False)
    width = db.Column(db.Integer(), nullable=True)
    height = db.Column(db.Integer(), nullable=True)
    customer_state = db.Column(
        db.Enum(CustomerState, name="customerstate"),
        nullable=False,
        default=CustomerState.none,
        server_default=CustomerState.none.value,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    library = db.relationship("Library", backref=db.backref("images", lazy="dynamic"))

    def storage_path(self, variant: str = "originals") -> str:
        """Build full GCS key for a variant: originals, previews, or thumbs.

        s3_key stores: {uuid}.{ext}
        Returns:       photos/{photographer_id}/{library_id}/{variant}/{uuid}.{ext}
        """
        return (
            f"photos/{self.library.user_id}/{self.library_id}/{variant}/{self.s3_key}"
        )

    def to_dict(
        self,
        original_url: str | None = None,
        preview_url: str | None = None,
        thumb_url: str | None = None,
    ):
        return {
            "id": self.id,
            "uuid": self.uuid,
            "filename": self.original_filename,
            "content_type": self.content_type,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "customer_state": self.customer_state.value,
            "created_at": self.created_at.isoformat(),
            "original_url": original_url,
            "preview_url": preview_url,
            "thumb_url": thumb_url,
        }


class SupportTicketStatus(enum.Enum):
    open = "open"
    closed = "closed"


class SupportTicket(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(
        db.Integer(), db.ForeignKey("user.id"), nullable=False, index=True
    )
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text(), nullable=False)
    status = db.Column(
        db.Enum(SupportTicketStatus, name="supportticketstatus"),
        nullable=False,
        default=SupportTicketStatus.open,
        server_default=SupportTicketStatus.open.value,
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("support_tickets", lazy="dynamic"))
    comments = db.relationship(
        "SupportTicketComment",
        backref="ticket",
        order_by="SupportTicketComment.created_at",
        lazy="select",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "body": self.body,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "comments": [c.to_dict() for c in self.comments],
        }


class SupportTicketComment(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    ticket_id = db.Column(
        db.Integer(), db.ForeignKey("support_ticket.id"), nullable=False, index=True
    )
    body = db.Column(db.Text(), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        return {
            "id": self.id,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


class Notification(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    seen_at = db.Column(db.DateTime, nullable=True)
    type = db.Column(
        db.Enum(NotificationType, name="notificationtype"),
        nullable=False,
    )
    user_id = db.Column(db.Integer(), db.ForeignKey("user.id"), nullable=False)
    related_object = db.Column(db.String(255), nullable=True)

    user = db.relationship(
        "User", backref=db.backref("notifications", lazy="dynamic")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type.value,
            "created_at": self.created_at.isoformat(),
            "seen_at": self.seen_at.isoformat() if self.seen_at else None,
            "related_object": self.related_object,
        }
