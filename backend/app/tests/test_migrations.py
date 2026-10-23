from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Enum, text

from models import db


def test_alembic_migrations_match_metadata(app):
    """The migration history must produce exactly the schema the models describe."""
    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert diff == []


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
