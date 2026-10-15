import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.db import (
    DatabaseError,
    DatabaseSettings,
    DatabaseState,
    database_engine,
    database_status,
    transaction,
)
from app.main import create_app


def test_database_is_disabled_without_connecting(monkeypatch):
    monkeypatch.delenv("INFRAWATCH_DB_ENABLED", raising=False)
    monkeypatch.setenv("INFRAWATCH_DATABASE_URL", "secret-invalid")
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr("app.db.sa.create_engine", connect)
    assert database_status() == DatabaseState.DISABLED
    assert not connect.called


@pytest.mark.parametrize(
    "url",
    [
        "",
        "sqlite:///data.db",
        "private-secret",
        "postgresql+psycopg://u@localhost/db?options=bad",
    ],
)
def test_invalid_database_configuration_hides_details(url, caplog):
    with caplog.at_level(logging.DEBUG):
        settings = DatabaseSettings(True, url)
        assert url not in repr(settings) or not url
        assert database_status(settings) == DatabaseState.CONFIGURATION_ERROR
    assert not caplog.text


def test_invalid_enable_setting_is_safe(monkeypatch):
    monkeypatch.setenv("INFRAWATCH_DB_ENABLED", "private")
    assert database_status() == DatabaseState.CONFIGURATION_ERROR


def test_transaction_closes_resources_and_sanitizes_failure(monkeypatch):
    engine = Mock()
    engine.begin.return_value.__enter__ = Mock(side_effect=RuntimeError("private-dsn"))
    engine.begin.return_value.__exit__ = Mock()
    monkeypatch.setattr("app.db.database_engine", lambda _: engine)
    with pytest.raises(DatabaseError, match="^unavailable$"):
        with transaction(DatabaseSettings(True, "unused")):
            pytest.fail("must not yield")
    engine.dispose.assert_called_once()


def test_engine_is_lazy_and_uses_bounded_connections():
    engine = database_engine(
        DatabaseSettings(True, "postgresql+psycopg://example@127.0.0.1:1/example")
    )
    try:
        assert engine.hide_parameters
        assert engine.pool.__class__.__name__ == "NullPool"
    finally:
        engine.dispose()


def test_bad_database_setting_does_not_change_existing_app(monkeypatch):
    monkeypatch.setenv("INFRAWATCH_DB_ENABLED", "1")
    monkeypatch.setenv("INFRAWATCH_DATABASE_URL", "private-invalid")
    connect = Mock(side_effect=AssertionError("API must not touch DB"))
    monkeypatch.setattr("app.db.sa.create_engine", connect)
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "service": "InfraWatch",
        }
        assert client.get("/api/metrics").status_code in {200, 503}
    assert not connect.called


def test_schema_revision_mismatch_is_reported_without_details(monkeypatch):
    engine = Mock()
    connection = Mock()
    connection.scalar.return_value = None
    engine.begin.return_value.__enter__ = Mock(return_value=connection)
    engine.begin.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("app.db.database_engine", lambda _: engine)
    assert database_status(DatabaseSettings(True, "unused")) == "schema_mismatch"
    engine.dispose.assert_called_once()


def test_transaction_rolls_back_and_disposes_after_caller_failure(monkeypatch):
    from contextlib import contextmanager

    lifecycle = []

    @contextmanager
    def begin():
        try:
            lifecycle.append("begin")
            yield object()
        except Exception:
            lifecycle.append("rollback")
            raise
        else:
            lifecycle.append("commit")

    engine = Mock()
    engine.begin = begin
    monkeypatch.setattr("app.db.database_engine", lambda _: engine)
    with pytest.raises(DatabaseError, match="unavailable"):
        with transaction(DatabaseSettings(True, "unused")):
            raise RuntimeError("private")
    assert lifecycle == ["begin", "rollback"]
    engine.dispose.assert_called_once()


def test_initial_revision_is_frozen_and_downgrade_refuses_data_loss():
    import importlib.util
    from pathlib import Path

    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects.postgresql import dialect

    from app.schema import metadata

    path = Path(__file__).parents[1] / "migrations/versions/0001_stage2a.py"
    spec = importlib.util.spec_from_file_location("initial_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in metadata.tables:
        assert str(
            CreateTable(metadata.tables[name]).compile(dialect=dialect())
        ) == str(CreateTable(module.metadata.tables[name]).compile(dialect=dialect()))
    with pytest.raises(RuntimeError, match="Destructive downgrade"):
        module.downgrade()
