from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
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
