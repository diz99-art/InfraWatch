"""Opt-in PostgreSQL tests; never run migrations against an unmarked database."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import DatabaseError, DatabaseSettings, database_engine, database_status
from app.metrics import Host
from app.schema import metadata, metric_samples
from app.servers import find_server, register_server

MARKER = "InfraWatch isolated test database v1"


def checked_engine(variable):
    url = os.environ.get(variable)
    if not url:
        pytest.fail("Missing independent test DB role configuration")
    settings = DatabaseSettings(True, url)
    engine = database_engine(settings)
    # Verification is SELECT only, before any DDL/DML.
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT current_database(), shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()"
            )
        ).one()
        if (
            not re.fullmatch(r"infrawatch_test_[a-f0-9]{12}", row[0])
            or row[1] != MARKER
        ):
            engine.dispose()
            pytest.fail("Refusing unmarked/non-independent database")
    return engine


@pytest.fixture(scope="module")
def migrated():
    if os.environ.get("INFRAWATCH_TEST_DB_CONFIRM") != "isolated":
        pytest.skip("Explicit independent PostgreSQL test environment required")
    engine = checked_engine("INFRAWATCH_TEST_DATABASE_URL")
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        # Never downgrade/drop/reset an existing database. Upgrade is forward-only.
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        yield engine, cfg
    finally:
        engine.dispose()


@pytest.fixture
def connection(migrated):
    engine, _ = migrated
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            yield conn
        finally:
            tx.rollback()


def sample(server_id):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return dict(
        sample_id=uuid4(),
        server_id=server_id,
        run_id=uuid4(),
        sequence=1,
        payload_schema_version=1,
        collection_interval_seconds=5,
        platform="darwin",
        scope="local_system",
        observed_at=now,
        collected_at=now,
        status="ok",
        errors=[],
        cpu_usage_percent=25,
        cpu_window_ms=1000,
        memory_total_bytes=1000,
        memory_available_bytes=600,
        memory_used_bytes=400,
        memory_usage_percent=40,
        disk_target_id="primary",
        disk_total_bytes=1000,
        disk_used_bytes=500,
        disk_free_bytes=400,
        disk_usage_percent=55.6,
        uptime_seconds=10,
        booted_at=now,
    )


def registered(conn):
    host = Host(id="test_" + uuid4().hex[:16], label="Test system", platform="darwin")
    return register_server(conn, host, uuid4()), host


def test_migration_idempotency_schema_and_data_preservation(migrated):
    engine, cfg = migrated
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            row, host = registered(conn)
            conn.execute(metric_samples.insert().values(**sample(row["server_id"])))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            assert find_server(conn, host.id)["server_id"] == row["server_id"]
            assert (
                conn.scalar(sa.select(sa.func.count()).select_from(metric_samples)) >= 1
            )
            assert set(sa.inspect(conn).get_table_names()) == {
                "alembic_version",
                "servers",
                "metric_samples",
            }
            assert {
                x["name"] for x in sa.inspect(conn).get_indexes("metric_samples")
            } >= {"ix_samples_server_time", "ix_samples_cleanup_time", "sample_attempt"}
            assert conn.scalar(sa.text("SHOW timezone")) == "UTC"
            assert conn.scalar(sa.text("SHOW statement_timeout")) == "2s"
            assert conn.scalar(sa.text("SHOW lock_timeout")) == "500ms"
            # Live metadata and frozen migration must agree.
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            assert compare_metadata(MigrationContext.configure(conn), metadata) == []
        finally:
            tx.rollback()


def test_server_registration_is_stable_and_conflicts_are_explicit(connection):
    row, host = registered(connection)
    assert (
        register_server(connection, host, row["server_id"])["server_id"]
        == row["server_id"]
    )
    with pytest.raises(DatabaseError, match="server_conflict"):
        register_server(connection, host, uuid4())
    with pytest.raises(DatabaseError, match="server_not_registered"):
        find_server(connection, "missing")


@pytest.mark.parametrize("state", ["ok", "partial", "failed", "exception", "timeout"])
def test_valid_record_states_and_utc_storage(connection, state):
    row, _ = registered(connection)
    data = sample(row["server_id"])
    if state == "partial":
        data.update(
            status="partial",
            disk_target_id=None,
            disk_total_bytes=None,
            disk_used_bytes=None,
            disk_free_bytes=None,
            disk_usage_percent=None,
            errors=[{"resource": "disk", "code": "COLLECTION_FAILED"}],
        )
    elif state in {"failed", "exception", "timeout"}:
        for key in list(data):
            if (
                key.startswith(("cpu_", "memory_", "disk_", "uptime_"))
                or key == "booted_at"
            ):
                data[key] = None
        data.update(
            status="timeout" if state == "timeout" else "failed",
            failure_reason="COLLECTION_TIMEOUT"
            if state == "timeout"
            else "COLLECTION_FAILED",
        )
        if state == "failed":
            data["errors"] = [
                {"resource": r, "code": "COLLECTION_FAILED"}
                for r in ["cpu", "memory", "disk", "uptime"]
            ]
        else:
            data["collected_at"] = None
    result = (
        connection.execute(
            metric_samples.insert().values(**data).returning(metric_samples)
        )
        .mappings()
        .one()
    )
    assert result["stored_at"].utcoffset().total_seconds() == 0
    assert result["observed_at"] == data["observed_at"]


@pytest.mark.parametrize(
    "changes",
    [
        {"cpu_usage_percent": -1},
        {"cpu_usage_percent": 101},
        {"memory_total_bytes": 0},
        {"memory_available_bytes": 1001},
        {"memory_used_bytes": -1},
        {"memory_usage_percent": 80},
        {"disk_free_bytes": 1001},
        {"disk_target_id": "private"},
        {"uptime_seconds": -1},
        {"cpu_window_ms": 0},
        {"sequence": 0},
        {"sequence": 2**53},
        {"server_id": uuid4()},
        {"status": "failed", "failure_reason": None},
        {"errors": [{"resource": "cpu", "code": "secret"}]},
        {
            "errors": [
                {"resource": "cpu", "code": "COLLECTION_FAILED", "message": "private"}
            ]
        },
        {"disk_used_bytes": None},
        {"collected_at": None},
        {"platform": "private"},
        {"scope": "container"},
    ],
)
def test_invalid_record_constraints(connection, changes):
    row, _ = registered(connection)
    data = sample(row["server_id"]) | changes
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(metric_samples.insert().values(**data))


def test_duplicate_attempt_and_primary_key_rejected(connection):
    row, _ = registered(connection)
    data = sample(row["server_id"])
    connection.execute(metric_samples.insert().values(**data))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(metric_samples.insert().values(**data))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            metric_samples.insert().values(**(data | {"sample_id": uuid4()}))
        )


def test_app_role_permissions_and_revision(migrated):
    app_engine = checked_engine("INFRAWATCH_TEST_APP_DATABASE_URL")
    owner, _ = migrated
    # Explicit committed fixture in a verified isolated DB; retained, never deleted.
    with owner.begin() as conn:
        fixture_row, _ = registered(conn)
    try:
        # No runtime registration/DDL grants. Granting is a separate operator step.
        with app_engine.connect() as conn:
            assert conn.scalar(
                sa.text("SELECT has_table_privilege(current_user, 'servers', 'SELECT')")
            )
            assert conn.scalar(
                sa.text(
                    "SELECT has_table_privilege(current_user, 'metric_samples', 'INSERT')"
                )
            )
            assert not conn.scalar(
                sa.text("SELECT has_table_privilege(current_user, 'servers', 'INSERT')")
            )
            assert not conn.scalar(
                sa.text(
                    "SELECT has_table_privilege(current_user, 'metric_samples', 'DELETE')"
                )
            )
            assert not conn.scalar(
                sa.text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            )
            inserted = conn.execute(
                metric_samples.insert()
                .values(**sample(fixture_row["server_id"]))
                .returning(metric_samples.c.sample_id)
            ).scalar_one()
            assert inserted is not None
            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(sa.text("CREATE TABLE forbidden_table (id integer)"))
            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(sa.text("DELETE FROM metric_samples WHERE false"))
        assert (
            database_status(
                DatabaseSettings(True, os.environ["INFRAWATCH_TEST_APP_DATABASE_URL"])
            )
            == "ready"
        )
    finally:
        app_engine.dispose()


def test_registration_operator_is_separate_from_runtime(migrated):
    engine = checked_engine("INFRAWATCH_TEST_REGISTER_DATABASE_URL")
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                row, host = registered(conn)
                assert find_server(conn, host.id)["server_id"] == row["server_id"]
                with pytest.raises(DBAPIError), conn.begin_nested():
                    conn.execute(
                        metric_samples.insert().values(**sample(row["server_id"]))
                    )
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def test_revision_mismatch_is_detected_without_migrating(connection):
    from app.db import check_revision

    connection.execute(
        sa.text("UPDATE alembic_version SET version_num = 'unexpected_revision'")
    )
    with pytest.raises(DatabaseError, match="schema_mismatch"):
        check_revision(connection)


def test_statement_timeout_and_connection_release(migrated):
    from app.db import transaction

    settings = DatabaseSettings(True, os.environ["INFRAWATCH_TEST_DATABASE_URL"])
    with pytest.raises(DatabaseError, match="unavailable"):
        with transaction(settings) as conn:
            conn.execute(sa.text("SELECT pg_sleep(3)"))
    # A fresh operation remains usable after the failed transaction was closed.
    with transaction(settings) as conn:
        assert conn.scalar(sa.text("SELECT 1")) == 1


def test_authentication_failure_is_safe_and_does_not_log_dsn(migrated, caplog):
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["INFRAWATCH_TEST_APP_DATABASE_URL"]).set(
        password="invalid-test-password"
    )
    assert (
        database_status(
            DatabaseSettings(True, url.render_as_string(hide_password=False))
        )
        == "unavailable"
    )
    assert "invalid-test-password" not in caplog.text
    assert "postgresql+psycopg" not in caplog.text
