"""Explicit DB administration, never invoked by application startup."""

import argparse
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config

from app.db import (
    DatabaseError,
    DatabaseSettings,
    check_revision,
    database_status,
    transaction,
)
from app.metrics import Host
from app.servers import find_server, register_server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check")
    sub.add_parser("upgrade")
    lookup = sub.add_parser("lookup")
    lookup.add_argument("--public-id", required=True)
    register = sub.add_parser("register")
    register.add_argument("--public-id", required=True)
    register.add_argument("--label", required=True)
    register.add_argument(
        "--platform", required=True, choices=["darwin", "linux", "win32", "other"]
    )
    register.add_argument("--server-id", required=True, type=UUID)
    args = parser.parse_args(argv)
    try:
        settings = DatabaseSettings.from_env()
        if args.action == "check":
            state = database_status(settings)
            print(state.value)
            return 0 if state in {"disabled", "ready"} else 1
        if args.action == "upgrade":
            cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            # Use one safe connection and explicit transaction; no DSN config/logging.
            with transaction(settings) as connection:
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
            print("schema_ready")
            return 0
        with transaction(settings) as connection:
            check_revision(connection)
            if args.action == "register":
                host = Host(id=args.public_id, label=args.label, platform=args.platform)
                row = register_server(connection, host, args.server_id)
            else:
                row = find_server(connection, args.public_id)
        print(row["server_id"])
        return 0
    except DatabaseError as exc:
        print(exc.code)
        return 1
    except Exception:
        print("database_operation_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
