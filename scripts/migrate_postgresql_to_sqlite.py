#!/usr/bin/env python3
"""Offline cutover: copy the eight PostgreSQL business tables into a NEW SQLite file.

Stop the old application first. PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD
(or libpq service/password file) configure the read-only source connection.
The final file is published only after all rows and integrity have been verified.
"""
import argparse
from contextlib import closing
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

TABLES = ("app_user", "node", "tunnel", "speed_limit", "forward",
          "user_tunnel", "statistics_flow", "vite_config")
PASSKEY_TABLES = ("passkey_credential", "passkey_policy")
BATCH = 500


def default_schema():
    here = Path(__file__).resolve()
    candidates = (here.with_name("sqlite-schema.sql"),
                  here.parent.parent / "springboot-backend/src/main/resources/db/init/sqlite-schema.sql")
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError("SQLite schema not found; specify --schema")


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def same_row(expected, actual):
    if actual is None or len(expected) != len(actual):
        return False
    for left, right in zip(expected, actual):
        if isinstance(left, Decimal):
            if right is None or Decimal(str(right)) != left:
                return False
        elif left != right or (left is not None and type(left) is not type(right)):
            return False
    return True


def normalize(row):
    # The only decimal column is traffic_ratio (numeric(10,1)).
    # Verify its round trip as Decimal rather than comparing binary floats.
    return tuple(float(value) if isinstance(value, Decimal) else value for value in row)


def copy_tables(source, target):
    from psycopg import sql
    with source.cursor() as meta:
        meta.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        meta.execute("SELECT current_schema()")
        schema = meta.fetchone()[0]
        if not schema:
            raise ValueError("No PostgreSQL schema selected")
        meta.execute("""SELECT table_name FROM information_schema.tables
            WHERE table_schema=%s AND table_type='BASE TABLE'""", (schema,))
        actual_tables = {row[0] for row in meta.fetchall()}
        if actual_tables not in (set(TABLES), set(TABLES + PASSKEY_TABLES)):
            raise ValueError("Source must contain the eight business tables, optionally both Passkey tables")

        for table in TABLES + (PASSKEY_TABLES if set(PASSKEY_TABLES) <= actual_tables else ()):
            columns = [row[1] for row in target.execute("PRAGMA table_info(" + identifier(table) + ")")]
            meta.execute("""SELECT column_name FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s""", (schema, table))
            if not columns or set(columns) != {row[0] for row in meta.fetchall()}:
                raise ValueError("Source/target column mismatch: " + table)
            ordered = sql.SQL("SELECT {} FROM {} ORDER BY id").format(
                sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(schema, table))
            col_sql = ",".join(map(identifier, columns))
            insert = "INSERT INTO " + identifier(table) + " (" + col_sql + ") VALUES (" + ",".join("?" for _ in columns) + ")"
            count = 0
            with source.cursor(name="copy_" + table) as reader:
                reader.execute(ordered)
                while rows := reader.fetchmany(BATCH):
                    target.executemany(insert, map(normalize, rows))
                    count += len(rows)

            # Verify every field in the same source snapshot, with bounded memory.
            with source.cursor(name="verify_" + table) as reader:
                reader.execute(ordered)
                check = target.execute("SELECT " + col_sql + " FROM " + identifier(table) + " ORDER BY id")
                while rows := reader.fetchmany(BATCH):
                    actual = check.fetchmany(len(rows))
                    if len(rows) != len(actual) or not all(same_row(a, b) for a, b in zip(rows, actual)):
                        raise ValueError("Row verification failed: " + table)
                if check.fetchone() is not None:
                    raise ValueError("Unexpected extra rows: " + table)
            if count != target.execute("SELECT count(*) FROM " + identifier(table)).fetchone()[0]:
                raise ValueError("Row count mismatch: " + table)

            # Preserve the source identity high-water mark (even if high IDs
            # were deleted), not just MAX(id). A never-used sequence may be NULL.
            if table == "passkey_policy":
                print(f"{table}: {count} rows verified", flush=True)
                continue  # Singleton ID has no sequence.
            meta.execute("SELECT pg_get_serial_sequence(%s, 'id')", (identifier(schema) + "." + identifier(table),))
            sequence = meta.fetchone()[0]
            if not sequence:
                raise ValueError("Source identity sequence not found: " + table)
            meta.execute("SELECT has_sequence_privilege(%s, 'SELECT')", (sequence,))
            if not meta.fetchone()[0]:
                raise ValueError("Read permission on identity sequence required: " + table)
            meta.execute("SELECT pg_sequence_last_value(%s::regclass)", (sequence,))
            last = meta.fetchone()[0] or 0
            largest = target.execute("SELECT coalesce(max(id),0) FROM " + identifier(table)).fetchone()[0]
            watermark = max(last, largest, 0)
            if not target.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (watermark, table)).rowcount:
                target.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (table, watermark))
            print(f"{table}: {count} rows verified", flush=True)
        if not target.execute("SELECT 1 FROM app_user LIMIT 1").fetchone():
            raise ValueError("Source has no users; refusing a cutover that would create default credentials")
        if target.execute("SELECT 1 FROM app_user GROUP BY lower(username) HAVING count(*)>1 LIMIT 1").fetchone():
            raise ValueError("Source contains conflicting case-insensitive usernames")


def migrate(destination, schema_path):
    import psycopg
    destination = Path(destination).expanduser().absolute()
    if any(os.path.lexists(str(destination) + suffix) for suffix in ("", "-wal", "-shm", "-journal")):
        raise ValueError("Target file or sidecars already exist; refusing overwrite")
    if not destination.parent.is_dir():
        raise ValueError("Create the target directory first")
    fd, scratch = tempfile.mkstemp(prefix=".flux-migration-", suffix=".db", dir=destination.parent)
    os.close(fd)  # mkstemp creates mode 0600
    try:
        with closing(sqlite3.connect(scratch)) as target:
            # Create only the schema. Never run the default-admin seed here.
            target.executescript(Path(schema_path).read_text(encoding="utf-8"))
            target.execute("PRAGMA journal_mode=DELETE")
            target.execute("PRAGMA synchronous=FULL")
            target.execute("BEGIN IMMEDIATE")
            with psycopg.connect() as source:
                copy_tables(source, target)
            if target.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Passkey references a missing user")
            target.commit()
            if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity_check failed")
        with open(scratch, "rb") as handle:
            os.fsync(handle.fileno())
        # Atomic no-clobber publication on the same filesystem.
        os.link(scratch, destination)
        print(f"Migration verified and published: {destination}", flush=True)
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.unlink(scratch + suffix)
            except FileNotFoundError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New SQLite DB file (must not exist)")
    parser.add_argument("--schema", type=Path, help="Path to SQLite schema SQL")
    args = parser.parse_args()
    try:
        migrate(args.output, args.schema or default_schema())
    except Exception as exc:
        # Do not print driver exceptions containing credentials or row contents.
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(f"Migration failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
