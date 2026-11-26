"""Tests for migrations/procrastinate_schema.py against a scratch PostgreSQL schema."""

import pathlib
import re

import pytest

import procrastinate_schema as ps
from models import db

SCHEMA = "ps_scratch"

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
VERSIONS = pathlib.Path(ps.__file__).parent / "versions"


@pytest.fixture
def conn(app):
    """A connection whose search_path is an empty schema; rolled back afterwards."""
    with db.engine.connect() as connection:
        trans = connection.begin()
        connection.exec_driver_sql(f"CREATE SCHEMA {SCHEMA}")
        connection.exec_driver_sql(f"SET LOCAL search_path TO {SCHEMA}")
        yield connection
        trans.rollback()


def _recorded(conn):
    return conn.exec_driver_sql(f"SELECT version FROM {ps.VERSION_TABLE}").scalar()


def _tables(conn):
    return {
        row[0]
        for row in conn.exec_driver_sql(
            f"SELECT tablename FROM pg_tables WHERE schemaname = '{SCHEMA}'"
        )
    }


def _migrations_dir(tmp_path, files):
    for name, sql in files.items():
        (tmp_path / name).write_text(sql)
    return str(tmp_path)


def _highest_shipped():
    return ps._migration_files(ps.SchemaManager.get_migrations_path())[-1][0]


def test_fresh_database_gets_schema_and_records_version(conn):
    ps.ensure_schema(conn, "03.04.00")

    assert {"procrastinate_jobs", "procrastinate_events", ps.VERSION_TABLE} <= _tables(conn)
    assert _recorded(conn) == _highest_shipped()


def test_second_run_is_a_noop(conn):
    ps.ensure_schema(conn, "03.04.00")
    conn.exec_driver_sql("CREATE TABLE marker (x int)")

    ps.ensure_schema(conn, "03.04.00")

    assert "marker" in _tables(conn)
    assert _recorded(conn) == _highest_shipped()


def test_old_database_gets_only_later_migrations(conn, tmp_path):
    path = _migrations_dir(
        tmp_path,
        {
            "01.00.00_01_first.sql": "CREATE TABLE m_first (x int);",
            "02.00.00_01_pre_second.sql": "CREATE TABLE m_second_pre (x int);",
            "02.00.00_50_post_second.sql": "CREATE TABLE m_second_post (x int);",
            "03.00.00_01_third.sql": "CREATE TABLE m_third (x int);",
        },
    )
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('01.00.00')")

    ps.ensure_schema(conn, "02.00.00", migrations_path=path)

    tables = _tables(conn)
    assert {"m_second_pre", "m_second_post"} <= tables
    assert not {"m_first", "m_third"} & tables
    assert _recorded(conn) == "02.00.00"


def test_percent_signs_in_migration_sql_survive(conn, tmp_path):
    path = _migrations_dir(
        tmp_path,
        {
            "02.00.00_01_pct.sql": (
                "CREATE FUNCTION pct() RETURNS text LANGUAGE sql AS $$ SELECT 'a%b' $$;"
            )
        },
    )
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('01.00.00')")

    ps.ensure_schema(conn, "02.00.00", migrations_path=path)

    assert conn.exec_driver_sql("SELECT pct()").scalar() == "a%b"


def test_library_older_than_target_fails(conn, tmp_path):
    path = _migrations_dir(tmp_path, {"01.00.00_01_first.sql": "SELECT 1;"})

    with pytest.raises(RuntimeError, match="older than expected"):
        ps.ensure_schema(conn, "03.04.00", migrations_path=path)


def test_unrecorded_existing_queue_fails(conn):
    conn.exec_driver_sql("CREATE TABLE procrastinate_jobs (id int)")

    with pytest.raises(RuntimeError, match="no schema version"):
        ps.ensure_schema(conn, "03.04.00")


def _types(conn):
    return {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            f"WHERE n.nspname = '{SCHEMA}' AND t.typname LIKE 'procrastinate%%'"
        )
    }


def _indexes(conn):
    return {
        row[0]
        for row in conn.exec_driver_sql(
            f"SELECT indexname FROM pg_indexes WHERE schemaname = '{SCHEMA}'"
        )
    }


def test_drop_schema_removes_everything(conn):
    ps.ensure_schema(conn, "03.04.00")

    ps.drop_schema(conn)

    assert _tables(conn) == set()
    leftovers = conn.exec_driver_sql(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        f"WHERE n.nspname = '{SCHEMA}'"
    ).scalar()
    assert leftovers == 0
    assert _types(conn) == set()


def test_drop_schema_removes_upgraded_database(conn):
    ps._run_script(conn, (FIXTURES / "procrastinate_schema_03_04_00.sql").read_text())
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('03.04.00')")
    ps.ensure_schema(conn, "03.12.00")

    ps.drop_schema(conn)

    assert _tables(conn) == set()
    assert _types(conn) == set()


@pytest.mark.parametrize("statement", ["CREATE INDEX", "create unique index", "DROP INDEX"])
def test_without_concurrently(statement):
    sql = f"{statement} CONCURRENTLY IF EXISTS idx ON t (x);"

    assert ps._without_concurrently(sql) == f"{statement} IF EXISTS idx ON t (x);"


def test_concurrently_statements_run_inside_transaction(conn, tmp_path):
    path = _migrations_dir(
        tmp_path,
        {
            "02.00.00_01_pre_table.sql": "CREATE TABLE m_t (x int);",
            "02.00.00_02_pre_index.sql": "CREATE INDEX CONCURRENTLY m_new_idx ON m_t (x);",
            "02.00.00_03_pre_old.sql": "CREATE INDEX m_old_idx ON m_t (x);",
            "02.00.00_50_post_drop.sql": "DROP INDEX CONCURRENTLY IF EXISTS m_old_idx;",
        },
    )
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('01.00.00')")

    ps.ensure_schema(conn, "02.00.00", migrations_path=path)

    indexes = _indexes(conn)
    assert "m_new_idx" in indexes
    assert "m_old_idx" not in indexes
    assert _recorded(conn) == "02.00.00"


def test_upgrade_from_03_04_00_to_03_12_00(conn):
    # schema.sql of procrastinate 3.10.0, whose highest migration is 03.04.00.
    ps._run_script(conn, (FIXTURES / "procrastinate_schema_03_04_00.sql").read_text())
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('03.04.00')")
    job_id = conn.exec_driver_sql(
        "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args) "
        "VALUES ('video', 'process_video', 'video-x', '{}') RETURNING id"
    ).scalar()

    ps.ensure_schema(conn, "03.12.00")

    assert _recorded(conn) == "03.12.00"
    lock_mode = conn.exec_driver_sql(
        "SELECT lock_mode::text FROM procrastinate_jobs WHERE id = %(id)s", {"id": job_id}
    ).scalar()
    assert lock_mode == "ordered"
    indexes = _indexes(conn)
    assert "procrastinate_jobs_todo_doing_lock_idx_v1" in indexes
    assert "procrastinate_jobs_id_lock_idx_v1" not in indexes
    assert conn.exec_driver_sql(
        "SELECT to_regprocedure("
        "'procrastinate_defer_jobs_v2(procrastinate_job_to_defer_v2[])') IS NOT NULL"
    ).scalar()
    assert "procrastinate_job_to_defer_v1" not in _types(conn)


def test_upgrade_matches_fresh_schema(conn):
    """An upgraded 03.04.00 queue has the same columns, indexes and routines as schema.sql."""

    def shape():
        columns = set(
            conn.exec_driver_sql(
                "SELECT table_name, column_name, data_type, column_default, is_nullable "
                f"FROM information_schema.columns WHERE table_schema = '{SCHEMA}' "
                f"AND table_name <> '{ps.VERSION_TABLE}'"
            ).all()
        )
        routines = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT p.oid::regprocedure::text FROM pg_proc p "
                f"JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = '{SCHEMA}'"
            )
        }
        return columns, _indexes(conn), routines, _types(conn)

    ps.ensure_schema(conn, _highest_shipped())
    fresh = shape()
    ps.drop_schema(conn)

    ps._run_script(conn, (FIXTURES / "procrastinate_schema_03_04_00.sql").read_text())
    conn.exec_driver_sql(f"CREATE TABLE {ps.VERSION_TABLE} (version text NOT NULL)")
    conn.exec_driver_sql(f"INSERT INTO {ps.VERSION_TABLE} VALUES ('03.04.00')")
    ps.ensure_schema(conn, _highest_shipped())

    assert shape() == fresh


def test_schema_target_matches_installed_library():
    targets = [
        match
        for path in VERSIONS.glob("*.py")
        for match in re.findall(
            r'^PROCRASTINATE_VERSION\s*=\s*"(\d\d\.\d\d\.\d\d)"',
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]

    assert targets, "no Alembic revision sets PROCRASTINATE_VERSION"
    assert max(targets) == _highest_shipped(), (
        f"procrastinate ships migrations up to {_highest_shipped()}, but the highest "
        f"ensure_schema target in migrations/versions/ is {max(targets)}: add an Alembic "
        "revision calling ensure_schema with the new version (CLAUDE.md, Schema and upgrades)"
    )


@pytest.mark.parametrize(
    "name,type_,expected",
    [
        ("procrastinate_jobs", "table", False),
        ("procrastinate_schema_version", "table", False),
        ("user", "table", True),
        ("procrastinate_jobs_pkey", "index", True),
    ],
)
def test_include_object(name, type_, expected):
    assert ps.include_object(None, name, type_, True, None) is expected
