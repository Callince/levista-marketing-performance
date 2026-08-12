"""Create the Levista database on Postgres and apply the schema.

    python setup_postgres.py            # create database + tables + views
    python setup_postgres.py --check    # just test the connection

Reads DATABASE_URL from .env. Your password stays in that file and is never
printed — the summary below masks it.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

import config
from db.models import get_engine, init_db, metadata


def _fail(message: str, *hints: str):
    print(f"\n  {message}")
    for hint in hints:
        print(f"    - {hint}")
    sys.exit(1)


def _url():
    if config.USING_FALLBACK_DB:
        _fail("No DATABASE_URL is set, so the pipeline is still on the SQLite fallback.",
              "Copy .env.example to .env",
              "Put your own Postgres password in the DATABASE_URL line",
              "Postgres 17 is on port 5432 (16 is on 5433, 13 on 5434)")
    url = make_url(config.DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        _fail(f"DATABASE_URL points at {url.drivername}, not Postgres.",
              "Expected: postgresql+psycopg2://postgres:PASSWORD@localhost:5432/levista")
    if url.password in (None, "", "YOUR_PASSWORD"):
        _fail("DATABASE_URL still has the placeholder password.",
              "Replace YOUR_PASSWORD in .env with your real Postgres password")
    return url


def _connect_admin(url):
    """Connect to the maintenance database so the target can be created."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT",
                          connect_args={"connect_timeout": 5})
    try:
        conn = admin.connect()
    except OperationalError as exc:
        detail = str(exc.orig).strip().splitlines()[0] if exc.orig else str(exc)
        hints = ["Check the password in .env"] if "password" in detail.lower() else [
            f"Is Postgres listening on port {url.port}?",
            "Services: postgresql-x64-17 -> 5432, -16 -> 5433, -13 -> 5434",
        ]
        _fail(f"Could not connect to Postgres: {detail}", *hints)
    return conn


def main(check_only: bool = False):
    url = _url()
    target = url.database
    print(f"Postgres  {url.username}@{url.host}:{url.port}  database {target!r}")

    conn = _connect_admin(url)
    with conn:
        version = conn.execute(text("SHOW server_version")).scalar()
        print(f"  connected — server version {version}")
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target}).scalar()

        if check_only:
            print(f"  database {target!r} {'exists' if exists else 'does not exist yet'}")
            return

        if exists:
            print(f"  database {target!r} already exists — leaving its data alone")
        else:
            # Identifier cannot be parameterised; quote it so odd names stay safe.
            conn.execute(text(f'CREATE DATABASE "{target}"'))
            print(f"  created database {target!r}")

    engine = get_engine()
    try:
        init_db(engine)
    except (OperationalError, ProgrammingError) as exc:
        _fail(f"Schema creation failed: {str(exc.orig or exc).strip().splitlines()[0]}")

    inspector = inspect(engine)
    tables = sorted(set(inspector.get_table_names()) & set(metadata.tables))
    views = sorted(inspector.get_view_names())
    print(f"  {len(tables)} tables: {', '.join(tables)}")
    print(f"  {len(views)} views:  {', '.join(views)}")

    with engine.connect() as check:
        rows = check.execute(text("SELECT COUNT(*) FROM performance_metrics")).scalar()
    print(f"  performance_metrics holds {rows:,} rows")
    if not rows:
        print("\nNext: python run_all.py   (loads the exports and builds both reports)")


if __name__ == "__main__":
    main(check_only="--check" in sys.argv)
