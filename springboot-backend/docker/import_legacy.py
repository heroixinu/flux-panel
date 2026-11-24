#!/usr/bin/env python3
"""Startup-only, offline legacy backup import. Never execute SQL from a dump."""
import argparse
from contextlib import closing
from decimal import Decimal
import gzip
import hashlib
from io import StringIO
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

TABLES = {"app_user", "forward", "node", "speed_limit", "statistics_flow",
          "tunnel", "user_tunnel", "vite_config"}
PASSKEY_TABLES = {"passkey_credential", "passkey_policy"}
IDENT = r'(?:\x60(?:[^\x60]|\x60\x60)+\x60|"(?:[^"]|"")+"|[A-Za-z_][A-Za-z_0-9]*)'
QUALIFIED = IDENT + r'(?:\s*\.\s*' + IDENT + r')?'
MAX_STATEMENT = 32 * 1024 * 1024
NUMBER_OR_NULL = re.compile(r"(?i)NULL\b|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
EXTENSIONS = (".sql", ".sql.gz", ".dump", ".dump.gz", ".backup", ".backup.gz", ".pgdump", ".pgdump.gz", ".pgdmp", ".pgdmp.gz")


class ImportFailure(ValueError):
    pass


def fail(message):
    raise ImportFailure(message)


def unquote(name):
    name = name.strip()
    if name.startswith(('"', chr(96))):
        return name[1:-1].replace(name[0] * 2, name[0])
    return name.lower()


def table_name(name, mysql):
    parts = [unquote(part.group()) for part in re.finditer(IDENT, name)]
    if not parts:
        fail("Missing table identifier")
    if len(parts) == 2 and not mysql and parts[0] != "public":
        fail("Only the PostgreSQL public schema is supported")
    table = parts[-1]
    if mysql and table == "user":
        table = "app_user"
    if table not in TABLES | PASSKEY_TABLES:
        fail("Unexpected business table in backup")
    return table


def column_name(name, table, mysql):
    name = unquote(name)
    return "username" if mysql and table == "app_user" and name == "user" else name


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def sql_statements(stream, mysql):
    """Yield complete statements; COPY data is consumed by the caller from stream."""
    pieces, length, quote_char, block = StringIO(), 0, None, False
    escaped = False
    backslash_string = False
    for line in stream:
        if not length and not block and not quote_char:
            stripped = line.strip()
            if not stripped or stripped.startswith("--") or (mysql and stripped.startswith("#")):
                continue
            if not mysql and re.fullmatch(r'\\(?:un)?restrict\s+[A-Za-z0-9]+', stripped):
                continue
        pos = 0
        while pos < len(line):
            ch = line[pos]
            following = line[pos:pos+2]
            if block:
                end = line.find("*/", pos)
                if end < 0:
                    break
                block = False
                pos = end + 2
                if length:
                    pieces.write(" ")
                    length += 1
                continue
            if quote_char:
                pieces.write(ch)
                length += 1
                if escaped:
                    escaped = False
                elif ch == "\\" and quote_char == "'" and backslash_string:
                    escaped = True
                elif ch == quote_char:
                    if following == quote_char * 2:
                        pieces.write(ch)
                        length += 1
                        pos += 1
                    else:
                        quote_char = None
                pos += 1
            elif following == "/*":
                block = True
                pos += 2
            elif following == "--" or (mysql and ch == "#"):
                break
            elif ch in ("'", '"', chr(96)):
                quote_char = ch
                backslash_string = mysql or (ch == "'" and pos > 0 and line[pos-1] in "Ee" and (pos == 1 or not (line[pos-2].isalnum() or line[pos-2] == "_")))
                pieces.write(ch)
                length += 1
                pos += 1
            elif ch == ";":
                stmt = pieces.getvalue().strip()
                pieces, length = StringIO(), 0
                pos += 1
                if stmt:
                    if re.match(r"(?i)^COPY\b", stmt) and line[pos:].strip():
                        fail("COPY header must end its line")
                    yield stmt
            else:
                if length or not ch.isspace():
                    pieces.write(ch)
                    length += 1
                pos += 1
            if length > MAX_STATEMENT:
                fail("SQL statement exceeds 32 MiB; regenerate without oversized INSERT batches")
    if quote_char or block or pieces.getvalue().strip():
        fail("Incomplete SQL statement or truncated dump")


def split_fields(body):
    """Split table definitions on top-level commas (not type parameters/defaults)."""
    start, level, q, pos = 0, 0, None, 0
    while pos < len(body):
        c = body[pos]
        if q:
            if c == q:
                if body[pos:pos+2] == q * 2:
                    pos += 1
                else:
                    q = None
            elif c == "\\" and q == "'":
                pos += 1
        elif c in ("'", '"', chr(96)):
            q = c
        elif c == "(":
            level += 1
        elif c == ")":
            level -= 1
        elif c == "," and level == 0:
            yield body[start:pos].strip()
            start = pos + 1
        pos += 1
    if q or level != 0:
        fail("Malformed table definition")
    yield body[start:].strip()


def columns_list(body, table, mysql):
    columns = []
    for field in split_fields(body):
        if not re.fullmatch(IDENT, field):
            fail("Unsupported column identifier")
        columns.append(column_name(field, table, mysql))
    return columns


def string_value(text, pos, mysql, pg_escape=False):
    result = StringIO()
    pos += 1
    escapes = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a"}
    while pos < len(text):
        ch = text[pos]
        pos += 1
        if ch == "'":
            if pos < len(text) and text[pos] == "'":
                result.write("'")
                pos += 1
            else:
                return result.getvalue(), pos
        elif ch == "\\" and (mysql or pg_escape):
            if pos >= len(text):
                fail("Truncated escaped string")
            ch = text[pos]
            pos += 1
            if pg_escape and (ch in "01234567xXuU"):
                # pg_dump emits plain text or COPY for numeric/unicode escapes.
                # Reject uncommon E-string escapes rather than silently alter data.
                fail("Unsupported PostgreSQL E-string numeric escape; use COPY format")
            result.write(("\f" if pg_escape and ch == "f" else escapes.get(ch, "\\" + ch if mysql and ch in "%_" else ch)))
        else:
            result.write(ch)
    fail("Unterminated INSERT string")


def insert_rows(body, mysql):
    """Only accept NULL, quoted strings and finite decimal/integer literals."""
    pos = 0
    def space():
        nonlocal pos
        while pos < len(body) and body[pos].isspace():
            pos += 1
    def expect(ch):
        nonlocal pos
        space()
        if pos >= len(body) or body[pos] != ch:
            fail("Unsupported INSERT VALUES syntax")
        pos += 1
    while True:
        expect("(")
        values = []
        while True:
            space()
            if pos < len(body) and body[pos] == "'":
                value, pos = string_value(body, pos, mysql)
            elif not mysql and body[pos:pos+2].lower() == "e'":
                value, pos = string_value(body, pos + 1, False, True)
            else:
                token = NUMBER_OR_NULL.match(body, pos)
                if not token:
                    fail("Unsupported INSERT literal (expressions and casts are not allowed)")
                value = None if token.group().upper() == "NULL" else token.group()
                pos += len(token.group())
            values.append(value)
            space()
            if pos < len(body) and body[pos] == ",":
                pos += 1
                continue
            expect(")")
            break
        yield values
        space()
        if pos == len(body):
            return
        expect(",")


def copy_value(value):
    if value == r"\N":
        return None
    data = value.encode("utf-8")
    def replace(match):
        x = match.group(1)
        if x.startswith(b"x") and len(x) > 1:
            return bytes([int(x[1:], 16)])
        if re.fullmatch(rb"[0-7]{1,3}", x):
            return bytes([int(x, 8) & 255])
        return {b"b": b"\b", b"f": b"\f", b"n": b"\n", b"r": b"\r",
                b"t": b"\t", b"v": b"\v"}.get(x, x)
    if data.endswith(b"\\") and len(data) - len(data.rstrip(b"\\")) & 1:
        fail("Invalid COPY escape")
    return re.sub(rb"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)", replace, data).decode("utf-8")


def copy_rows(stream):
    for line in stream:
        line = line.rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]
        if line == r"\.":
            return
        if len(line) > MAX_STATEMENT:
            fail("COPY row exceeds 32 MiB")
        yield [copy_value(value) for value in line.split("\t")]
    fail("Missing COPY terminator (truncated backup)")


class Importer:
    def __init__(self, conn, mysql):
        self.conn, self.mysql = conn, mysql
        self.definitions, self.seen, self.watermarks = {}, set(), {}
        self.counts = dict.fromkeys(TABLES | PASSKEY_TABLES, 0)
        self.types = {table: {row[1]: row[2].lower() for row in conn.execute("PRAGMA table_info(" + quote(table) + ")")}
                      for table in TABLES | PASSKEY_TABLES}

    def validate_columns(self, table, columns):
        if len(columns) != len(set(columns)) or set(columns) != set(self.types[table]):
            fail("Column mismatch in " + table + "; backup must match the eight Flux business tables")
        return columns

    def convert(self, value, typ):
        if value is None:
            return None
        if "int" in typ:
            if not re.fullmatch(r"[+-]?\d+", value):
                fail("Invalid integer in backup")
            number = int(value)
            if not -(2**63) <= number < 2**63:
                fail("Integer outside SQLite signed 64-bit range")
            return number
        if typ.startswith("decimal"):
            number = Decimal(value)
            result = float(number)
            if not number.is_finite() or Decimal(str(result)) != number:
                fail("Decimal cannot round-trip through SQLite")
            return result
        return value

    def save(self, table, columns, rows):
        columns = self.validate_columns(table, columns)
        query = "INSERT INTO " + quote(table) + " (" + ",".join(map(quote, columns)) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
        batch = []
        id_index = columns.index("id")
        for row in rows:
            if len(row) != len(columns):
                fail("Wrong value count in " + table)
            if row[id_index] is None:
                fail("NULL primary key in " + table)
            batch.append(tuple(self.convert(value, self.types[table][col]) for col, value in zip(columns, row)))
            if len(batch) >= 256:
                self.conn.executemany(query, batch)
                self.counts[table] += len(batch)
                batch.clear()
        if batch:
            self.conn.executemany(query, batch)
            self.counts[table] += len(batch)
        self.seen.add(table)

    def parse(self, stream):
        for stmt in sql_statements(stream, self.mysql):
            create = re.fullmatch(r"(?is)CREATE TABLE(?: IF NOT EXISTS)?\s+(" + QUALIFIED + r")\s*\((.*)\)\s*(.*)", stmt)
            if create:
                table = table_name(create[1], self.mysql)
                if table in self.definitions:
                    fail("Duplicate table definition")
                cols = []
                for field in split_fields(create[2]):
                    if re.match(r"(?i)^(?:PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|CHECK|FOREIGN|FULLTEXT|SPATIAL|EXCLUDE)\b", field):
                        continue
                    column = re.match(r"(" + IDENT + r")\s+", field)
                    if not column:
                        fail("Unsupported CREATE TABLE column")
                    cols.append(column_name(column[1], table, self.mysql))
                self.definitions[table] = self.validate_columns(table, cols)
                self.seen.add(table)
                auto = re.search(r"(?i)\bAUTO_INCREMENT\s*=\s*(\d+)", create[3])
                if auto:
                    self.watermarks[table] = max(0, int(auto[1]) - 1)
                continue
            insert = re.fullmatch(r"(?is)INSERT INTO\s+(" + QUALIFIED + r")\s*(?:\(([^()]*)\)\s*)?VALUES\s*(.*)", stmt)
            if insert:
                table = table_name(insert[1], self.mysql)
                cols = columns_list(insert[2], table, self.mysql) if insert[2] is not None else self.definitions.get(table)
                if not cols:
                    fail("INSERT without column list requires CREATE TABLE in backup")
                self.save(table, cols, insert_rows(insert[3], self.mysql))
                continue
            copy = re.fullmatch(r"(?is)COPY\s+(" + QUALIFIED + r")\s*\(([^()]*)\)\s+FROM\s+stdin", stmt)
            if copy and not self.mysql:
                table = table_name(copy[1], False)
                self.save(table, columns_list(copy[2], table, False), copy_rows(stream))
                continue
            sequence = re.fullmatch(r"(?is)SELECT\s+(?:pg_catalog\.)?setval\s*\(\s*'([^']+)'\s*,\s*(\d+)\s*,\s*(true|false)\s*\)", stmt)
            if sequence and not self.mysql:
                name = sequence[1].split(".")[-1]
                if not name.endswith("_id_seq"):
                    fail("Unexpected PostgreSQL sequence")
                table = table_name(name[:-7], False)
                self.watermarks[table] = max(0, int(sequence[2]) - (sequence[3].lower() == "false"))
                continue
            # Recognized dump metadata is ignored, never sent to SQLite or psql.
            if re.match(r"(?is)^(?:SET\b|RESET\b|SELECT\s+pg_catalog\.set_config\s*\(|"
                        r"DROP\s+(?:TABLE|SEQUENCE|INDEX|SCHEMA)\b|"
                        r"CREATE\s+(?:SEQUENCE|(?:UNIQUE\s+)?INDEX|SCHEMA)\b|"
                        r"ALTER\s+(?:TABLE|SEQUENCE|INDEX|SCHEMA)\b|"
                        r"LOCK TABLES\b|UNLOCK TABLES\b|USE\b|COMMENT ON\b|"
                        r"GRANT\b|REVOKE\b|START TRANSACTION\b|COMMIT\b|BEGIN\b)", stmt):
                continue
            fail("Unsupported statement in backup; no data has been published")

        if self.seen not in (TABLES, TABLES | PASSKEY_TABLES):
            fail("Backup must contain all eight business tables, optionally both Passkey tables")
        if not self.counts["app_user"]:
            fail("Backup contains no users; refusing to initialize default credentials")
        if not self.conn.execute("SELECT 1 FROM app_user WHERE role_id=0 LIMIT 1").fetchone():
            fail("Backup contains no administrator")
        if self.conn.execute("SELECT 1 FROM app_user GROUP BY lower(username) HAVING count(*)>1 LIMIT 1").fetchone():
            fail("Duplicate case-insensitive usernames")
        for table, count in sorted(self.counts.items()):
            actual, largest = self.conn.execute("SELECT count(*), coalesce(max(id),0) FROM " + quote(table)).fetchone()
            if actual != count:
                fail("Row count mismatch in " + table)
            if table == "passkey_policy":
                continue  # Singleton ID has no sequence.
            mark = max(largest, self.watermarks.get(table, 0), 0)
            if not self.conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (mark, table)).rowcount:
                self.conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (table, mark))
            print(f"Legacy import: {table}: {count} rows", flush=True)


def capped_copy(reader, path, max_bytes):
    digest, count = hashlib.sha256(), 0
    with path.open("wb") as writer:
        while chunk := reader.read(1024 * 1024):
            count += len(chunk)
            if count > max_bytes:
                fail("Backup exceeds DB_IMPORT_MAX_BYTES")
            digest.update(chunk)
            writer.write(chunk)
    if not count:
        fail("Empty backup")
    return digest.hexdigest()


def stage_backup(source, path, max_bytes):
    with source.open("rb") as raw:
        before = os.fstat(raw.fileno())
        magic = raw.read(2)
        raw.seek(0)
        if magic == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=raw) as reader:
                digest = capped_copy(reader, path, max_bytes)
        else:
            digest = capped_copy(raw, path, max_bytes)
        after = os.fstat(raw.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            fail("Backup changed while being read; publish it with an atomic rename")
    return digest


def unpack_postgres(archive, output, max_bytes):
    # Render to plain text only; never connect to or execute SQL on any server.
    with subprocess.Popen(["pg_restore", "--no-owner", "--no-privileges", "--file=-", str(archive)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            capped_copy(proc.stdout, output, max_bytes)
        except BaseException:
            proc.kill()
            raise
        if proc.wait() != 0:
            fail("pg_restore could not decode this archive; check its format/version or use a plain pg_dump")


def existing_digest(destination):
    if not destination.is_file() or destination.is_symlink():
        return None
    try:
        with closing(sqlite3.connect(destination.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            rows = conn.execute("SELECT digest FROM _flux_legacy_import WHERE id=1").fetchall()
            return rows[0][0] if len(rows) == 1 else None
    except sqlite3.Error:
        return None


def select_backup(directory, name):
    if name:
        if Path(name).name != name or not name.lower().endswith(EXTENSIONS):
            fail("DB_IMPORT_FILE must be a supported basename")
        candidate = directory / name
        if not candidate.is_file() or candidate.is_symlink():
            fail("Selected import backup is missing or is a symlink")
        return candidate
    if not directory.is_dir():
        fail("DB_IMPORT_DIR does not exist")
    files = sorted(p for p in directory.iterdir() if p.is_file() and not p.is_symlink() and p.name.lower().endswith(EXTENSIONS))
    if len(files) > 1:
        fail("Multiple backups found; set DB_IMPORT_FILE explicitly")
    return files[0] if files else None


def import_backup(destination, directory, name, schema, max_bytes):
    if not destination.parent.is_dir():
        fail("SQLite destination directory does not exist")
    if destination.is_symlink():
        fail("SQLite destination cannot be a symlink")
    backup = select_backup(directory, name)
    old_digest = existing_digest(destination)
    if backup is None:
        if old_digest:
            print("Legacy import already completed; no backup remains", flush=True)
            return
        fail("Import enabled but no backup was found")
    if destination.exists() and not old_digest:
        fail("SQLite already exists and was not created by this importer; refusing overwrite")
    with tempfile.TemporaryDirectory(prefix=".flux-import-", dir=destination.parent) as temp:
        work = Path(temp)
        staged = work / "source"
        digest = stage_backup(backup, staged, max_bytes)
        if old_digest:
            if digest != old_digest:
                fail("A different backup was already imported; refusing overwrite")
            print("Legacy import already completed; skipping identical backup", flush=True)
            return
        if any(os.path.lexists(str(destination) + s) for s in ("", "-wal", "-shm", "-journal")):
            fail("SQLite destination or sidecar exists; refusing overwrite")
        with staged.open("rb") as reader:
            prefix = reader.read(65536)
        if prefix.startswith(b"PGDMP"):
            plain = work / "postgres.sql"
            unpack_postgres(staged, plain, max_bytes)
            engine = "postgresql-custom"
            mysql = False
        elif b"MySQL dump" in prefix or b"MariaDB dump" in prefix or re.search(rb"(?i)CREATE TABLE\s+\x60", prefix):
            plain, engine, mysql = staged, "mysql", True
        elif b"PostgreSQL database dump" in prefix or re.search(rb"(?im)^(?:COPY|CREATE TABLE|INSERT INTO)\s+public\.", prefix):
            plain, engine, mysql = staged, "postgresql-plain", False
        else:
            fail("Unknown dump format (expected mysqldump, pg_dump SQL or PGDMP archive)")
        target = work / "flux.db"
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(schema.read_text(encoding="utf-8"))
            conn.execute("BEGIN IMMEDIATE")
            with plain.open("r", encoding="utf-8-sig", newline="") as stream:
                Importer(conn, mysql).parse(stream)
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                fail("Passkey references a missing user")
            conn.execute("CREATE TABLE _flux_legacy_import (id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL, source_type TEXT NOT NULL)")
            conn.execute("INSERT INTO _flux_legacy_import VALUES (1,?,?)", (digest, engine))
            conn.commit()
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                fail("SQLite integrity check failed")
        os.chmod(target, 0o600)
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
        # Same-filesystem atomic publication, never replace an existing file.
        os.link(target, destination)
        dir_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        print(f"Legacy import complete ({engine}); original backup preserved", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--file", default="")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=1073741824)
    args = parser.parse_args()
    try:
        if args.max_bytes <= 0:
            fail("DB_IMPORT_MAX_BYTES must be positive")
        import_backup(args.destination.absolute(), args.directory, args.file, args.schema, args.max_bytes)
    except Exception as exc:
        # Never log dump literals, credentials, node secrets or full driver errors.
        print("Legacy import failed: " + (str(exc) if isinstance(exc, ImportFailure) else type(exc).__name__), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
