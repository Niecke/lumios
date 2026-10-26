"""Bring the Procrastinate job-queue schema to a named library version.

Procrastinate ships its schema as ``schema.sql`` (the state of the installed
version) plus one SQL file per change in ``sql/migrations/``. It keeps no
record of what a database has applied and has no API that applies the files,
so this module records the applied version in its own table and replays the
missing files. Alembic revisions call ``ensure_schema`` with the highest
migration version of the library release they expect.
"""

import os
import re

from procrastinate.schema import SchemaManager

VERSION_TABLE = "procrastinate_schema_version"

_MIGRATION_FILE = re.compile(r"^(\d\d\.\d\d\.\d\d)_(\d\d)_.+\.sql$")


def include_object(obj, name, type_, reflected, compare_to):
    """Alembic ``include_object`` hook: the queue's tables are not in our models."""
    if type_ == "table" and name:
        return not (name.startswith("procrastinate_"))
    return True


def _run_script(bind, script: str) -> None:
    # exec_driver_sql hands psycopg a parameter set, so a literal % (RAISE
    # format strings in the library's functions) has to be doubled.
    bind.exec_driver_sql(script.replace("%", "%%"))


def _migration_files(migrations_path: str) -> list[tuple[str, int, str]]:
    """(version, serial, file name) of every migration, in application order."""
    files = []
    for name in os.listdir(migrations_path):
        match = _MIGRATION_FILE.match(name)
        if match:
            files.append((match.group(1), int(match.group(2)), name))
    return sorted(files)


def ensure_schema(bind, target: str, migrations_path: str | None = None) -> None:
    """Make the Procrastinate schema match the library at migration version ``target``.

    ``target`` is the highest migration version of the library release the
    calling revision was written for, e.g. ``"03.04.00"``. ``pre`` and ``post``
    scripts of one version are applied together: the migrate Job runs while no
    new pod is up, which is the "easy" upgrade path of the Procrastinate docs.
    """
    migrations_path = migrations_path or SchemaManager.get_migrations_path()
    files = _migration_files(migrations_path)
    highest = files[-1][0] if files else ""
    if highest < target:
        raise RuntimeError(
            f"Installed procrastinate ships migrations up to {highest or 'none'}, "
            f"but this revision needs {target}: the library is older than expected"
        )

    bind.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (version text NOT NULL)"
    )
    recorded = bind.exec_driver_sql(f"SELECT version FROM {VERSION_TABLE}").scalar()

    if recorded is None:
        exists = bind.exec_driver_sql(
            "SELECT to_regclass('procrastinate_jobs') IS NOT NULL"
        ).scalar()
        if exists:
            raise RuntimeError(
                "procrastinate_jobs exists but no schema version is recorded: "
                "the queue was created outside Alembic and has to be reconciled by hand"
            )
        # schema.sql is the state of the installed library, i.e. its highest migration.
        _run_script(bind, SchemaManager.get_schema())
        bind.exec_driver_sql(
            f"INSERT INTO {VERSION_TABLE} (version) VALUES (%(v)s)", {"v": highest}
        )
        return

    if recorded >= target:
        return

    for version, _serial, name in files:
        if recorded < version <= target:
            with open(os.path.join(migrations_path, name), encoding="utf-8") as fh:
                _run_script(bind, fh.read())
    bind.exec_driver_sql(
        f"UPDATE {VERSION_TABLE} SET version = %(v)s", {"v": target}
    )


def drop_schema(bind) -> None:
    """Remove every Procrastinate object and the version table."""
    _run_script(
        bind,
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT p.oid::regprocedure AS sig FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE 'DROP ROUTINE ' || r.sig || ' CASCADE';
            END LOOP;
        END $$;
        """,
    )
    bind.exec_driver_sql(
        "DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, "
        f"procrastinate_jobs, procrastinate_workers, {VERSION_TABLE} CASCADE"
    )
    bind.exec_driver_sql(
        "DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, "
        "procrastinate_job_event_type, procrastinate_job_status CASCADE"
    )
