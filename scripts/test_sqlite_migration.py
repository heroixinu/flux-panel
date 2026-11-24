#!/usr/bin/env python3
"""CI only: verify PostgreSQL -> SQLite on the existing populated migration database."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing

import psycopg

from migrate_postgresql_to_sqlite import TABLES

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "migrate_postgresql_to_sqlite.py"


def run(dest, success):
    completed = subprocess.run([sys.executable, str(MIGRATION), "--output", str(dest)], check=False)
    assert (completed.returncode == 0) == success, completed.returncode


def main():
    # Database was populated by the MySQL -> PostgreSQL migration test.
    # Add an exact decimal, Unicode text, large counters, and an identity gap.
    with psycopg.connect() as conn:
        conn.execute("UPDATE tunnel SET traffic_ratio=1.3, name='迁移测试' WHERE id=12")
        conn.execute("UPDATE statistics_flow SET flow=9007199254740993 WHERE id=16")
        conn.execute("SELECT setval(pg_get_serial_sequence('vite_config','id'), 999, true)")
    with tempfile.TemporaryDirectory() as directory:
        dest = Path(directory) / "flux.db"
        run(dest, True)
        with closing(sqlite3.connect(dest)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert conn.execute("SELECT name,traffic_ratio FROM tunnel WHERE id=12").fetchone() == ("迁移测试", 1.3)
            assert conn.execute("SELECT flow FROM statistics_flow WHERE id=16").fetchone() == (9007199254740993,)
            for table in TABLES:
                assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] > 0
            conn.execute("INSERT INTO vite_config(name,value,time) VALUES ('migration_test','1',1)")
            assert conn.execute("SELECT id FROM vite_config WHERE name='migration_test'").fetchone()[0] > 999
            conn.commit()
        before = dest.read_bytes()
        run(dest, False)
        assert dest.read_bytes() == before, "Existing SQLite file was modified"
        bad = Path(directory) / "bad.db"
        with psycopg.connect() as conn:
            conn.execute("ALTER TABLE vite_config ADD COLUMN incompatible_extra integer")
        try:
            run(bad, False)
            assert not bad.exists(), "Failed migration published an incomplete target"
            assert not list(Path(directory).glob(".flux-migration-*")), "Migration scratch files leaked"
        finally:
            with psycopg.connect() as conn:
                conn.execute("ALTER TABLE vite_config DROP COLUMN incompatible_extra")
    print("SQLite migration, row verification, identity watermark and rollback passed")


if __name__ == "__main__":
    main()
