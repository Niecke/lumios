"""Audit log helper — call write_audit_log() at each auditable event."""

from flask import request
from models import db, AuditLog, AuditLogType


def _get_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def write_audit_log(
    audit_type: AuditLogType,
    *,
    creator_id: int | None = None,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
) -> None:
    """Insert an audit log row into the current session.

    The row is committed together with whatever surrounding transaction calls
    db.session.commit().  If you need the event persisted independently (e.g.
    for a failed login where there is no other commit), call db.session.commit()
    after this function.
    """
    entry = AuditLog(
        audit_type=audit_type,
        ip_address=_get_ip(),
        creator_id=creator_id,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
    )
    db.session.add(entry)
