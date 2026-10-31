import os
import warnings

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import Enum, text

from models import db
from procrastinate_schema import include_object


def test_alembic_migrations_match_metadata(app):
    """The migration history must produce exactly the schema the models describe."""
    with db.engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_object": include_object}
        )
        diff = compare_metadata(context, db.metadata)
    assert diff == []


def test_queue_tables_exist_but_are_not_models(app):
    """The job queue is created by the migrations and stays out of the model diff."""
    with db.engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        unfiltered = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert {"procrastinate_jobs", "procrastinate_schema_version"} <= tables
    assert any(op[0] == "remove_table" for op in unfiltered)


def test_alembic_enum_values_match_models(app):
    """compare_metadata ignores enum labels, so check them explicitly."""
    mismatches = []
    with db.engine.connect() as conn:
        for table in db.metadata.sorted_tables:
            for column in table.columns:
                if not isinstance(column.type, Enum):
                    continue
                rows = conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :name"
                    ),
                    {"name": column.type.name},
                )
                in_db = {row[0] for row in rows}
                in_model = set(column.type.enums)
                if in_db != in_model:
                    mismatches.append(
                        f"{table.name}.{column.name}: "
                        f"missing in db {sorted(in_model - in_db)}, "
                        f"extra in db {sorted(in_db - in_model)}"
                    )
    assert mismatches == []


MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")


def test_migration_downgrade_and_upgrade(app):
    """env.py runs online migrations without the deprecated get_engine()."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        downgrade(directory=MIGRATIONS_DIR, revision="-1")
        upgrade(directory=MIGRATIONS_DIR, revision="head")
    assert [w for w in caught if "get_engine" in str(w.message)] == []

    with db.engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"include_object": include_object}),
            db.metadata,
        )
    assert diff == []


def test_env_py_does_not_call_deprecated_get_engine():
    with open(os.path.join(MIGRATIONS_DIR, "env.py")) as f:
        source = f.read()
    assert "db.get_engine(" not in source
