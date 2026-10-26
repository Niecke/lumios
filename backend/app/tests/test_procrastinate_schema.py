"""Tests for migrations/procrastinate_schema.py against a scratch PostgreSQL schema."""

import pytest

import procrastinate_schema as ps
from models import db

SCHEMA = "ps_scratch"


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


def test_drop_schema_removes_everything(conn):
    ps.ensure_schema(conn, "03.04.00")

    ps.drop_schema(conn)

    assert _tables(conn) == set()
    leftovers = conn.exec_driver_sql(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        f"WHERE n.nspname = '{SCHEMA}'"
    ).scalar()
    assert leftovers == 0


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
