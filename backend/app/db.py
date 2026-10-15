"""Explicit PostgreSQL access. Importing or creating FastAPI never connects."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

REVISION = "0001_stage2a"


class DatabaseError(Exception):
    """Only fixed public-safe codes may escape the database boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class DatabaseState(StrEnum):
    DISABLED = "disabled"
    CONFIGURATION_ERROR = "configuration_error"
    UNAVAILABLE = "unavailable"
    SCHEMA_MISMATCH = "schema_mismatch"
    READY = "ready"


@dataclass(frozen=True)
class DatabaseSettings:
    enabled: bool = False
    url: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        enabled = os.environ.get("INFRAWATCH_DB_ENABLED", "0")
        if enabled not in {"0", "1"}:
            raise DatabaseError("configuration_error")
        return cls(enabled == "1", os.environ.get("INFRAWATCH_DATABASE_URL", ""))


def database_engine(settings):
    if not settings.enabled:
        raise DatabaseError("disabled")
    try:
        url = make_url(settings.url)
        if (
            url.drivername != "postgresql+psycopg"
            or not url.database
            or not url.host
            or not url.username
            or url.query
        ):
            raise ValueError
        # Query options are forbidden: callers cannot replace timeout or search_path.
        return sa.create_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            echo=False,
            connect_args={
                "connect_timeout": 2,
                "options": "-c timezone=UTC -c statement_timeout=2000 "
                "-c lock_timeout=500 -c idle_in_transaction_session_timeout=5000 "
                "-c search_path=public",
            },
        )
    except Exception:
        raise DatabaseError("configuration_error") from None


@contextmanager
def transaction(settings):
    """Blocking internal boundary: use only in DB workers/CLI, never async routes.

    One physical connection per operation, commit on success, rollback on failure,
    close and dispose in all cases. No background connection/retry/pool thread.
    """
    engine = database_engine(settings)
    try:
        with engine.begin() as connection:
            yield connection
    except DatabaseError:
        raise
    except Exception:
        raise DatabaseError("unavailable") from None
    finally:
        engine.dispose()


def check_revision(connection):
    if (
        connection.scalar(sa.text("SELECT to_regclass('public.alembic_version')"))
        is None
    ):
        raise DatabaseError("schema_mismatch")
    revisions = connection.scalars(sa.text("SELECT version_num FROM alembic_version"))
    if list(revisions) != [REVISION]:
        raise DatabaseError("schema_mismatch")


def database_status(settings=None):
    try:
        settings = settings or DatabaseSettings.from_env()
        if not settings.enabled:
            return DatabaseState.DISABLED
        with transaction(settings) as connection:
            check_revision(connection)
        return DatabaseState.READY
    except DatabaseError as exc:
        return DatabaseState(exc.code)
