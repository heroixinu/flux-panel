#!/usr/bin/env python3
"""Test the legacy importer with synthetic fixtures and real database-produced dumps.

No production backup or credentials are included in this repository.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "springboot-backend/src/main/resources/db/init/sqlite-schema.sql"
SEED = ROOT / "springboot-backend/src/main/resources/db/init/data.sql"
IMPORTER = ROOT / "springboot-backend/docker/import_legacy.py"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def create_fixture():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text())
    conn.executescript(SEED.read_text())
    conn.execute("UPDATE vite_config SET value=? WHERE name='app_name'", ("中文 O'Reilly; \\\\ slash\nline\tend",))
    conn.execute("INSERT INTO node(id,name,secret,ip,server_ip,port_sta,port_end,created_time,status) VALUES(11,?,?,?,?,1000,2000,1,1)",
                 ("node; quote ' and \\", "fixture-secret", None, "127.0.0.1"))
    conn.execute("INSERT INTO tunnel(id,name,traffic_ratio,in_node_id,in_ip,out_node_id,out_ip,type,flow,created_time,updated_time,status) VALUES(12,'tunnel',1.3,11,'::1',11,'::1',1,1,1,1,1)")
    conn.execute("INSERT INTO forward(id,user_id,user_name,name,tunnel_id,in_port,remote_addr,created_time,updated_time,status) VALUES(13,1,'admin_user','forward',12,1234,'example:80',1,1,1)")
    conn.execute("INSERT INTO statistics_flow(id,user_id,flow,total_flow,time,created_time) VALUES(16,1,9007199254740993,9007199254740993,'12:00',1)")
    conn.execute("UPDATE sqlite_sequence SET seq=999 WHERE name='vite_config'")
    conn.commit()
    return conn


def mysql_literal(value):
    if value is None:
        return "NULL"
    if not isinstance(value, str):
        return str(value)
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t").replace("\0", "\\0") + "'"


def pg_value(value):
    if value is None:
        return r"\N"
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def fixture_dumps(directory, passkeys=False):
    """Match the two source layouts, plus PG plain SQL and INSERT variants."""
    directory.mkdir(parents=True, exist_ok=True)
    with closing(create_fixture()) as conn:
        tables = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name").fetchall()
        mysql = ["-- MySQL dump 10.13 Distrib 8.0.46\n/*!40101 SET NAMES utf8mb4 */;\n"]
        pg = ["-- PostgreSQL database dump\nSET standard_conforming_strings = on;\n"]
        pg_insert = ["-- PostgreSQL database dump\nSET standard_conforming_strings = on;\n"]
        for table, ddl in tables:
            if not passkeys and table.startswith("passkey_"):
                continue
            name = "user" if table == "app_user" else table
            cols = [row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")]
            types = [row[2] for row in conn.execute("PRAGMA table_info(" + table + ")")]
            source_cols = ["user" if table == "app_user" and col == "username" else col for col in cols]
            bt = chr(96)
            mysql.append("CREATE TABLE " + bt + name + bt + " (\n" +
                         ",\n".join("  " + bt + col + bt + " " + ("int" if typ == "INTEGER" else typ) for col, typ in zip(source_cols, types)) +
                         ",\n PRIMARY KEY (" + bt + "id" + bt + ")) ENGINE=InnoDB" +
                         (" AUTO_INCREMENT=1000" if table == "vite_config" else "") + ";\n")
            rows = conn.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
            if rows:
                mysql.append("INSERT INTO " + bt + name + bt + " VALUES " +
                             ",".join("(" + ",".join(map(mysql_literal, row)) + ")" for row in rows) + ";\n")
            pg.append("COPY public." + table + " (" + ", ".join('"' + col + '"' for col in cols) + ") FROM stdin;\n")
            pg.extend("\t".join(map(pg_value, row)) + "\n" for row in rows)
            pg.append("\\.\n")
            pg_insert.append("CREATE TABLE public." + table + " (" + ",".join('"' + c + '" ' + t for c,t in zip(cols,types)) + ");\n")
            for row in rows:
                pg_insert.append("INSERT INTO public." + table + " VALUES (" + ",".join(
                    "NULL" if v is None else "'" + v.replace("'", "''") + "'" if isinstance(v,str) else str(v) for v in row) + ");\n")
            if table == "vite_config":
                pg.append("SELECT pg_catalog.setval('public.vite_config_id_seq', 999, true);\n")
                pg_insert.append("SELECT pg_catalog.setval('public.vite_config_id_seq', 1000, false);\n")
        with gzip.open(directory / "mysql.sql.gz", "wt", encoding="utf-8") as handle:
            handle.write("".join(mysql))
        (directory / "pg.sql").write_text("".join(pg), encoding="utf-8")
        (directory / "pg-insert.sql").write_text("".join(pg_insert), encoding="utf-8")
    return directory


def invoke(directory, dest, name="", *, success=True, max_bytes=1073741824):
    cmd = [sys.executable, str(IMPORTER), "--directory", str(directory), "--destination", str(dest),
           "--schema", str(SCHEMA), "--file", name, "--max-bytes", str(max_bytes)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if (result.returncode == 0) != success:
        raise AssertionError(result.stdout)
    return result.stdout


def verify_fixture(path):
    with closing(sqlite3.connect(path)) as conn, closing(create_fixture()) as expected:
        for table, in expected.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
            assert conn.execute("SELECT * FROM " + table + " ORDER BY id").fetchall() == expected.execute("SELECT * FROM " + table + " ORDER BY id").fetchall(), table
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name='vite_config'").fetchone() == (999,)
        assert len(conn.execute("SELECT digest FROM _flux_legacy_import").fetchone()[0]) == 64


def unit():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        directory = fixture_dumps(root / "import")
        for name in ("mysql.sql.gz", "pg.sql", "pg-insert.sql"):
            dest = root / (name + ".db")
            assert "Legacy import complete" in invoke(directory, dest, name)
            verify_fixture(dest)
            with closing(sqlite3.connect(dest)) as conn:
                conn.execute("UPDATE vite_config SET value='keep' WHERE name='app_name'")
                conn.commit()
            before = dest.read_bytes()
            assert "skipping identical backup" in invoke(directory, dest, name)
            assert dest.read_bytes() == before
            different = "pg.sql" if name != "pg.sql" else "mysql.sql.gz"
            invoke(directory, dest, different, success=False)
            assert dest.read_bytes() == before
        # Old dumps omit both new tables; new dumps preserve both credentials
        # and policy. A partial security schema must fail closed.
        newer = fixture_dumps(root / "newer", passkeys=True)
        pg = newer / "pg.sql"
        content = pg.read_text()
        content = content.replace('COPY public.passkey_policy ("id", "password_enabled") FROM stdin;\n\\.\n',
                                  'COPY public.passkey_policy ("id", "password_enabled") FROM stdin;\n1\t0\n\\.\n')
        content = content.replace('COPY public.passkey_credential ("id", "user_id", "rp_id", "credential_id", "user_handle", "public_key_cose", "signature_count", "label", "created_at", "last_used_at", "backup_eligible", "backed_up") FROM stdin;\n\\.\n',
                                  'COPY public.passkey_credential ("id", "user_id", "rp_id", "credential_id", "user_handle", "public_key_cose", "signature_count", "label", "created_at", "last_used_at", "backup_eligible", "backed_up") FROM stdin;\n1\t1\tlocalhost\tY3JlZA\tdXNlcg\tY29zZQ\t1\tci\t1\t2\t0\t0\n\\.\n')
        pg.write_text(content)
        secured = root / "secured.db"
        invoke(newer, secured, "pg.sql")
        with closing(sqlite3.connect(secured)) as conn:
            assert conn.execute("SELECT password_enabled FROM passkey_policy").fetchone() == (0,)
            assert conn.execute("SELECT user_id,credential_id,last_used_at FROM passkey_credential").fetchone() == (1, "Y3JlZA", 2)
        (newer / "partial.sql").write_text((directory / "pg.sql").read_text() +
                                            'COPY public.passkey_policy ("id", "password_enabled") FROM stdin;\n1\t0\n\\.\n')
        invoke(newer, root / "partial.db", "partial.sql", success=False)
        (newer / "orphan.sql").write_text(content.replace("1\t1\tlocalhost", "1\t99999\tlocalhost"))
        invoke(newer, root / "orphan.db", "orphan.sql", success=False)
        dest = root / "bad.db"
        invoke(directory, dest, success=False)  # ambiguous file selection
        assert not dest.exists()
        invoke(directory, dest, "mysql.sql.gz", success=False, max_bytes=10)
        assert not dest.exists()
        (directory / "broken.sql").write_text((directory / "pg.sql").read_text() + "COPY public.node (id) FROM stdin;\n")
        invoke(directory, dest, "broken.sql", success=False)
        assert not dest.exists()
        (directory / "null-id.sql").write_text((directory / "pg.sql").read_text().replace("11\tnode;", r"\N" + "\tnode;", 1))
        invoke(directory, dest, "null-id.sql", success=False)
        assert not dest.exists()
        (directory / "injection.sql").write_text((directory / "pg.sql").read_text() + "DELETE FROM app_user;")
        invoke(directory, dest, "injection.sql", success=False)
        assert not dest.exists()
        with closing(sqlite3.connect(dest)) as conn:
            conn.executescript(SCHEMA.read_text())
        before = dest.read_bytes()
        invoke(directory, dest, "mysql.sql.gz", success=False)
        assert dest.read_bytes() == before
        assert not list(root.glob(".flux-import-*"))
    print("Legacy import parser, escaping, 64-bit data, sequence, idempotence, corruption and overwrite tests passed")


def actual_dumps(mysql_file, pg_file, pg_sql):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for path, engine in ((mysql_file, "mysql"), (pg_file, "postgresql-custom"), (pg_sql, "postgresql-plain")):
            directory = root / engine
            directory.mkdir()
            name = Path(path).name
            shutil.copyfile(path, directory / name)
            dest = root / (engine + ".db")
            invoke(directory, dest, name)
            with closing(sqlite3.connect(dest)) as conn:
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert conn.execute("SELECT id FROM node").fetchone() == (11,)
                assert conn.execute("SELECT id FROM forward").fetchone() == (13,)
                assert conn.execute("SELECT id FROM user_tunnel").fetchone() == (15,)
                assert conn.execute("SELECT source_type FROM _flux_legacy_import").fetchone() == (engine,)
                if engine != "mysql":
                    assert conn.execute("SELECT flow FROM statistics_flow WHERE id=16").fetchone() == (9007199254740993,)
                    assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name='vite_config'").fetchone()[0] >= 999
            invoke(directory, dest, name)
    print("Real mysqldump and pg_dump custom/plain archives passed")


def container_tests(image):
    """Exercise the image entrypoint, then authenticate against imported data."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        directory = fixture_dumps(root / "import")
        # Produce a real custom archive from a separate, disposable PG DB.
        # PG service is already available in the Native verification workflow.
        env = dict(os.environ, PGDATABASE="flux_legacy_import")
        run("createdb", "--maintenance-db=postgres", "flux_legacy_import")
        try:
            run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "gost-schema.sql"), env=env)
            run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "gost.sql"), env=env)
            # Ensure a known non-default config is imported, not a newly seeded DB.
            run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-c", "UPDATE vite_config SET value='imported-pg' WHERE name='app_name'", env=env)
            archive = root / "pg.dump"
            run("pg_dump", "-Fc", "--file", str(archive), env=env)
            with archive.open("rb") as src, gzip.open(directory / "pg-custom.sql.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
        finally:
            run("dropdb", "--maintenance-db=postgres", "flux_legacy_import")
        for index, file in enumerate(("mysql.sql.gz", "pg-custom.sql.gz")):
            data = root / ("data-" + str(index))
            data.mkdir()
            name = "flux-legacy-import-" + str(index)
            args = ["docker", "run", "-d", "--name", name, "--network", "host",
                    "--memory=512m", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--mount", f"type=bind,source={data},target=/app/data",
                    "--mount", f"type=bind,source={directory},target=/app/import,readonly",
                    "-e", "DB_TYPE=sqlite", "-e", "DB_IMPORT_ENABLED=true", "-e", "DB_IMPORT_FILE=" + file,
                    "-e", "JWT_SECRET=ci-integration-only-32-character-secret", "-e", "LOG_DIR=/tmp/flux-logs", image]
            def ready():
                for _ in range(300):
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:6365/flow/test", timeout=1) as response:
                            if response.read() == b"test":
                                return
                    except OSError:
                        pass
                    if subprocess.check_output(["docker", "inspect", "-f", "{{.State.Running}}", name], text=True).strip() != "true":
                        break
                    time.sleep(0.2)
                raise AssertionError("Imported backend did not start")
            def authenticate():
                body = json.dumps({"username": "admin_user", "password": "admin_user"}).encode()
                request = urllib.request.Request("http://127.0.0.1:6365/api/v1/user/login", data=body,
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    assert json.load(response)["code"] == 0
                with closing(sqlite3.connect(data / "flux.db")) as conn:
                    expected = ("中文 O'Reilly; \\\\ slash\nline\tend" if index == 0 else "imported-pg")
                    assert conn.execute("SELECT value FROM vite_config WHERE name='app_name'").fetchone()[0] == expected
                    assert conn.execute("SELECT count(*) FROM _flux_legacy_import").fetchone() == (1,)
            try:
                run(*args, stdout=subprocess.DEVNULL)
                ready()
                authenticate()
                run("docker", "stop", "-t", "35", name, stdout=subprocess.DEVNULL)
                run("docker", "start", name, stdout=subprocess.DEVNULL)
                ready()
                authenticate()
                logs = subprocess.check_output(["docker", "logs", name], stderr=subprocess.STDOUT, text=True)
                assert logs.count("Legacy import complete (") == 1
                assert "skipping identical backup" in logs
                print("Container startup and restart imported " + file + " successfully")
            except BaseException:
                subprocess.run(["docker", "logs", name], check=False)
                raise
            finally:
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        unit()
    elif sys.argv[1] == "--actual":
        actual_dumps(*sys.argv[2:])
    elif sys.argv[1] == "--container":
        container_tests(sys.argv[2])
    else:
        raise SystemExit("Unknown test mode")
