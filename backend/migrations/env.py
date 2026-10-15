"""Only explicit Alembic commands connect. No DSN in ini/logging configuration."""

from alembic import context

from app.db import DatabaseError, DatabaseSettings, database_engine
from app.schema import metadata


def run():
    if context.is_offline_mode():
        context.configure(
            dialect_name="postgresql", target_metadata=metadata, literal_binds=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    provided = context.config.attributes.get("connection")
    if provided is not None:
        context.configure(connection=provided, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = database_engine(DatabaseSettings.from_env())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    except DatabaseError:
        raise
    except Exception:
        raise DatabaseError("migration_failed") from None
    finally:
        engine.dispose()


run()
