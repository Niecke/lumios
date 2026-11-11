"""services/schema.py: is the database at or past this code's Alembic head?"""

from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import text

from models import db
from services import schema


@pytest.fixture
def conn(app):
    """A connection whose alembic_version changes are rolled back."""
    connection = db.engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


def _set_version(conn, *revisions):
    conn.execute(text("DELETE FROM alembic_version"))
    for rev in revisions:
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:r)"), {"r": rev})


def _previous_revision():
    head = schema.code_heads()[0]
    return schema._script().get_revision(head).down_revision


class TestSchemaStatus:
    def test_ready_at_head(self, conn):
        status = schema.schema_status(conn)

        assert status.ready
        assert status.missing == ()
        assert status.db_heads == schema.code_heads()

    def test_not_ready_one_revision_behind(self, conn):
        _set_version(conn, _previous_revision())

        status = schema.schema_status(conn)

        assert not status.ready
        assert status.missing == schema.code_heads()

    def test_ready_with_a_revision_the_code_does_not_know(self, conn):
        # migrated by a newer release: old pods must stay ready
        _set_version(conn, "ffffffffffff")

        status = schema.schema_status(conn)

        assert status.ready
        assert status.missing == ()

    def test_not_ready_with_empty_alembic_version(self, conn):
        _set_version(conn)

        status = schema.schema_status(conn)

        assert not status.ready
        assert status.missing == schema.code_revisions()
        assert "<none>" in status.describe()

    def test_not_ready_without_alembic_version_table(self, conn):
        conn.execute(text("DROP TABLE alembic_version"))

        status = schema.schema_status(conn)

        assert not status.ready
        assert status.db_heads == ()

    def test_describe_names_missing_revision_and_code_head(self, conn):
        previous = _previous_revision()
        _set_version(conn, previous)

        text_ = schema.schema_status(conn).describe()

        head = schema.code_heads()[0]
        assert f"missing revisions {head}" in text_
        assert f"database at {previous}" in text_
        assert f"code head {head}" in text_

    def test_two_db_heads_where_one_is_unknown_is_ready(self, conn):
        with patch.object(
            MigrationContext, "get_current_heads", return_value=(_previous_revision(), "ffffffffffff")
        ):
            assert schema.schema_status(conn).ready

    def test_two_known_db_heads_count_with_their_ancestors(self, conn):
        head = schema.code_heads()[0]
        with patch.object(
            MigrationContext, "get_current_heads", return_value=(head, _previous_revision())
        ):
            assert schema.schema_status(conn).ready
