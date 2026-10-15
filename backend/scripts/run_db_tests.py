"""Create a NEW isolated cluster with supplied PostgreSQL 18 binaries.

No download/install, no shared server, no database drop, no automatic file deletion.
Run from backend: .venv/bin/python scripts/run_db_tests.py --pg-bin /path/to/bin
"""

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL


def run(pg_bin, all_tests=False):
    version = subprocess.check_output(
        [str(pg_bin / "postgres"), "--version"], text=True
    )
    if not version.startswith("postgres (PostgreSQL) 18."):
        raise RuntimeError("PostgreSQL 18 binaries required")
    base = Path(tempfile.mkdtemp(prefix="infrawatch-db-test-"))
    base.chmod(0o700)
    data, log = base / "data", base / "postgres.log"
    password = secrets.token_urlsafe(32)
    pwfile = base / "admin-password"
    pwfile.write_text(password)
    pwfile.chmod(0o600)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    dbname = "infrawatch_test_" + secrets.token_hex(6)
    owner_password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    register_password = secrets.token_urlsafe(32)
    subprocess.run(
        [
            str(pg_bin / "initdb"),
            "-D",
            str(data),
            "-U",
            "cluster_admin",
            "--pwfile",
            str(pwfile),
            "--auth-host=scram-sha-256",
            "--auth-local=scram-sha-256",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    started = False
    try:
        subprocess.run(
            [
                str(pg_bin / "pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(log),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {base}",
                "-w",
                "start",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        started = True
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="cluster_admin",
            password=password,
            dbname="postgres",
            autocommit=True,
        ) as conn:
            for name, pw in [
                ("migration_owner", owner_password),
                ("monitor_app", app_password),
                ("server_registrar", register_password),
            ]:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(name), sql.Literal(pw))
                )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER migration_owner").format(
                    sql.Identifier(dbname)
                )
            )
            conn.execute(
                sql.SQL(
                    "COMMENT ON DATABASE {} IS 'InfraWatch isolated test database v1'"
                ).format(sql.Identifier(dbname))
            )
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(dbname)
                )
            )
            conn.execute(
                sql.SQL(
                    "GRANT CONNECT ON DATABASE {} TO monitor_app, server_registrar"
                ).format(sql.Identifier(dbname))
            )
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="cluster_admin",
            password=password,
            dbname=dbname,
            autocommit=True,
        ) as conn:
            conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            conn.execute(
                "GRANT USAGE ON SCHEMA public TO monitor_app, server_registrar"
            )

        def url(user, pw):
            return URL.create(
                "postgresql+psycopg",
                username=user,
                password=pw,
                host="127.0.0.1",
                port=port,
                database=dbname,
            ).render_as_string(hide_password=False)

        env = os.environ.copy()
        env.update(
            INFRAWATCH_TEST_DB_CONFIRM="isolated",
            INFRAWATCH_TEST_DATABASE_URL=url("migration_owner", owner_password),
            INFRAWATCH_TEST_APP_DATABASE_URL=url("monitor_app", app_password),
        )
        # Apply migration explicitly before granting table-specific runtime INSERT.
        env["INFRAWATCH_TEST_REGISTER_DATABASE_URL"] = url(
            "server_registrar", register_password
        )
        env.update(
            INFRAWATCH_DB_ENABLED="1",
            INFRAWATCH_DATABASE_URL=env["INFRAWATCH_TEST_DATABASE_URL"],
        )
        subprocess.run(
            [sys.executable, "-m", "app.database_cli", "upgrade"], env=env, check=True
        )
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="cluster_admin",
            password=password,
            dbname=dbname,
            autocommit=True,
        ) as conn:
            conn.execute("GRANT INSERT ON metric_samples TO monitor_app")
            conn.execute("GRANT INSERT ON servers TO server_registrar")
            conn.execute(
                "GRANT SELECT ON servers, metric_samples, alembic_version TO monitor_app"
            )
            conn.execute("GRANT SELECT ON servers, alembic_version TO server_registrar")
        print("Independent PostgreSQL tests:", version.strip(), flush=True)
        test_command = [sys.executable, "-m", "pytest"]
        if all_tests:
            env["INFRAWATCH_RUN_LIVE_TESTS"] = "1"
        else:
            test_command.append("tests/test_database_live.py")
        result = subprocess.run(test_command, env=env)
        if result.returncode == 0:
            # One explicit committed registration fixture proves persistence across
            # an actual server restart. It is retained in this private test cluster.
            from uuid import uuid4

            fixture_id = uuid4()

            def owner_connection():
                return psycopg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="migration_owner",
                    password=owner_password,
                    dbname=dbname,
                )

            with owner_connection() as conn:
                conn.execute(
                    "INSERT INTO servers (server_id, public_id, label, platform) VALUES (%s, %s, %s, %s)",
                    (fixture_id, "restart_fixture", "Test system", "darwin"),
                )
            subprocess.run(
                [
                    str(pg_bin / "pg_ctl"),
                    "-D",
                    str(data),
                    "-m",
                    "fast",
                    "-w",
                    "restart",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            with owner_connection() as conn:
                assert (
                    conn.execute(
                        "SELECT server_id FROM servers WHERE public_id = %s",
                        ("restart_fixture",),
                    ).fetchone()[0]
                    == fixture_id
                )
                assert (
                    conn.execute("SELECT version_num FROM alembic_version").fetchone()[
                        0
                    ]
                    == "0001_stage2a"
                )
            print(
                "Restart persistence: registration UUID and migration revision preserved",
                flush=True,
            )
        return result.returncode
    finally:
        if started:
            subprocess.run(
                [str(pg_bin / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        print("Test cluster stopped; retained private files:", base, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include Stage 1 OS measurements and all backend regressions",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.pg_bin.resolve(), args.all))
    except Exception:
        # PostgreSQL log remains in the private directory for deliberate inspection.
        raise SystemExit(
            "Independent DB setup/test failed; inspect private cluster log"
        ) from None
