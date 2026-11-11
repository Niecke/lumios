"""
Is the database schema usable by this code?

"Ready" means the database holds every Alembic revision the running code knows,
that is: it is at or past this code's head. There is deliberately no equality
check with the head. During a rolling update the old pods run against a database
the pre-upgrade migration has already advanced, and they must stay ready.

The check reads ``alembic_version`` only (one single-row SELECT) and never
migrates. It works without an app context: it takes a plain SQLAlchemy
connection and reads the revision scripts from disk.
"""

import functools
import os
from dataclasses import dataclass

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)


@functools.cache
def _script() -> ScriptDirectory:
    # Parsed once per process; the revision files do not change while it runs.
    return ScriptDirectory(MIGRATIONS_DIR)


@functools.cache
def code_revisions() -> tuple[str, ...]:
    """Every revision id the code knows, ordered base to head."""
    return tuple(rev.revision for rev in reversed(list(_script().walk_revisions())))


@functools.cache
def code_heads() -> tuple[str, ...]:
    return tuple(sorted(_script().get_heads()))


@dataclass(frozen=True)
class SchemaStatus:
    ready: bool
    db_heads: tuple[str, ...]
    code_heads: tuple[str, ...]
    missing: tuple[str, ...]

    def describe(self) -> str:
        """Log text naming what is missing, the database's revision and the code head."""
        database = ", ".join(self.db_heads) or "<none>"
        code = ", ".join(self.code_heads) or "<none>"
        if self.ready:
            return f"database at {database}, code head {code}"
        return (
            f"missing revisions {', '.join(self.missing)} "
            f"(database at {database}, code head {code})"
        )


def schema_status(connection) -> SchemaStatus:
    """Compare ``alembic_version`` with the revisions of this code.

    ``connection`` is a SQLAlchemy ``Connection``. Query errors propagate: the
    caller decides what an unreachable database means.
    """
    script = _script()
    known = set(code_revisions())
    heads = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
    ahead = bool(heads) and any(head not in known for head in heads)
    if ahead:
        # Migrated by a newer release (old pods still serving, or a rollback).
        return SchemaStatus(True, heads, code_heads(), ())

    applied: set[str] = set()
    for head in heads:
        applied.update(rev.revision for rev in script.iterate_revisions(head, "base"))
    missing = tuple(rev for rev in code_revisions() if rev not in applied)
    return SchemaStatus(not missing, heads, code_heads(), missing)
