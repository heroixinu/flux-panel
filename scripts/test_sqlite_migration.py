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
        # A current PostgreSQL source additionally contains the two security
        # tables; verify that passkey-only deployments survive the cutover.
        schema = ROOT.parent / "springboot-backend/src/main/resources/db/init/schema.sql"
        passkey_ddl = schema.read_text().split("-- Passkey tables are additive", 1)[1].split("\n", 1)[1]
        with psycopg.connect() as conn:
            conn.execute(passkey_ddl)
            conn.execute("INSERT INTO passkey_credential(user_id,rp_id,credential_id,user_handle,public_key_cose,signature_count,label,created_at,last_used_at,backup_eligible,backed_up) VALUES(1,'localhost','Y3JlZA','dXNlcg','Y29zZQ',7,'ci',1,2,0,0)")
            conn.execute("INSERT INTO passkey_policy VALUES(1,0)")
        try:
            secured = Path(directory) / "secured.db"
            run(secured, True)
            with closing(sqlite3.connect(secured)) as conn:
                assert conn.execute("SELECT password_enabled FROM passkey_policy").fetchone() == (0,)
                assert conn.execute("SELECT credential_id,signature_count FROM passkey_credential").fetchone() == ("Y3JlZA", 7)
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            with psycopg.connect() as conn:
                conn.execute("DROP TABLE passkey_credential, passkey_policy")
    print("SQLite migration, row verification, identity watermark, Passkey preservation and rollback passed")


if __name__ == "__main__":
    main()
