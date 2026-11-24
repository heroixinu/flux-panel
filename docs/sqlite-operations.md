# SQLite + GraalVM Native deployment (preview)

## Defaults and compatibility

- New installation: SQLite, one backend replica, local persistent directory `./data`, two containers (backend and frontend). The backend image's default database file is `/app/data/flux.db`; a local JVM launch defaults to `./flux.db`.
- For an existing PostgreSQL installation, `DB_HOST` without `DB_TYPE` still selects PostgreSQL. Explicit `DB_TYPE=postgresql` is recommended; keep DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD. A standard Spring datasource URL is also supported.
- The installer identifies the existing engine before upgrades, backs it up, and refuses implicit database conversion. External PostgreSQL deployments should upgrade their existing Compose manually without changing database settings.
- Do not start multiple backend instances against the same SQLite database or put it on NFS/SMB/network volumes. Use PostgreSQL for multi-instance and heavy write workloads.
- Default SQLite pool: one persistent connection, WAL, synchronous FULL, busy timeout 10 seconds, 2 MiB page cache and foreign-key enforcement. Keep the database, WAL and SHM together. Do not override the connection pool to multiple writers without load testing.
- SQLite's built-in LOWER is ASCII case-insensitive, unlike PostgreSQL with Unicode collations. Existing non-ASCII usernames remain usable with their exact spelling; ASCII case-insensitive login remains supported. No collation extension is loaded.
- Login credentials, JWT secret, node secrets and all business records are preserved by migration; never initialize a new empty SQLite file over an existing installation.

## New installation

Only deploy after both CI workflows have passed for the same commit and images are available. The native image tag on this branch is `sqlite-native`, the JVM alternative is `sqlite-jvm`, and the frontend tag is `sqlite-default`.

In an empty directory, download `panel_install.sh` from `codex/sqlite-default`, then:

```bash
chmod +x panel_install.sh
FLUX_SOURCE_REF=codex/sqlite-default FLUX_IMAGE_TAG=sqlite-default ./panel_install.sh
```

Choose install. To choose PostgreSQL for a fresh install, prepend `FLUX_DB_TYPE=postgresql`. To choose the JVM backend instead of Native, prepend `FLUX_BACKEND_IMAGE_TAG=sqlite-jvm`.

For manual Compose/1Panel installation, use `docker-compose-v4.yml` or `docker-compose-v6.yml`, set `JWT_SECRET` to a strong random secret, `BACKEND_PORT=6365`, `FRONTEND_PORT=6366`, `IMAGE_TAG=sqlite-default`, `BACKEND_IMAGE_TAG=sqlite-native` in .env. No DB credentials are needed. Create `data` with mode 0700. Keep the entire data directory on local persistent storage. Change default admin credentials after first login.

The PostgreSQL Compose variants are `docker-compose-postgresql-v4.yml` and `docker-compose-postgresql-v6.yml`; retain both gost-schema.sql and gost.sql and the existing postgres_data volume if using the bundled server.

## Online backup and offline restore

Menu option 4 produces a consistent SQLite Backup API snapshot using the sqlite3 CLI bundled in both backend images. It verifies PRAGMA integrity_check and writes the private file into a new sqlite_backup_* directory. The PostgreSQL option still runs pg_dump -Fc.

Manual backup from the Compose deployment directory (backend running):

```bash
umask 077
mkdir -m 700 backups
docker compose exec -T backend sqlite3 -bail -cmd '.timeout 10000' /app/data/flux.db ".backup '/tmp/flux-backup.db'"
docker compose exec -T backend sqlite3 -bail /tmp/flux-backup.db 'PRAGMA integrity_check;'
docker cp springboot-backend:/tmp/flux-backup.db backups/flux.db
chmod 600 backups/flux.db
docker compose exec -T backend rm -f /tmp/flux-backup.db
```

Use a unique backup path for each run and require integrity_check to print exactly ok. Do not copy only the live flux.db file: committed transactions can still be in its WAL. Back up the .env separately (JWT_SECRET is sensitive).

Restore requires stopping the backend and ensuring the backup is from the same compatible schema. Verify the backup with sqlite3 first; then move the entire old data directory aside (including sidecars), create a new private data directory, copy the verified backup as data/flux.db, and start the backend. Do not delete the old directory until login, nodes, tunnels, forwarding and traffic counters have been checked. If using 1Panel, the bind-mounted data directory can be managed by the panel, but stop the backend before a filesystem backup/restore or use the online backup instead.

## PostgreSQL -> SQLite migration

This is a deliberate offline cutover. Do not switch DB_TYPE first.

1. Take a PostgreSQL custom-format dump and keep the original Compose, .env and volume.
2. Stop the old backend (not the PostgreSQL server), and keep it stopped so writes cannot be lost after the migration snapshot.
3. Use a machine with Python 3.10+ and access to the PostgreSQL database. From a checkout of this branch, run:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r scripts/requirements-migration.txt
export PGHOST=127.0.0.1 PGPORT=5432 PGDATABASE=flux PGUSER=flux
# Use a protected .pgpass file or set PGPASSWORD without exposing it in shell history.
install -d -m 700 data
python scripts/migrate_postgresql_to_sqlite.py --output data/flux.db
```

If the database has no host port, run the tool in a protected environment with access to the Docker network or temporarily use a localhost-only mapping. The source account needs SELECT on the eight tables and identity sequences. Do not expose PostgreSQL publicly.

The tool requires the exact eight business tables and matching columns in current_schema(), copies and verifies every row in a read-only repeatable-read snapshot, preserves explicit IDs and identity high-water marks, checks SQLite integrity and atomically publishes a new file. It refuses an existing destination or sidecars. It never changes PostgreSQL and never seeds a new admin into the migration file. For standalone release assets, keep sqlite-schema.sql beside the script or pass --schema.

4. Replace the stopped deployment's Compose with the SQLite variant, keep the original JWT_SECRET and ports, select the verified native or JVM image, and ensure data/flux.db is the migrated file.
5. Start the backend and frontend. Verify existing admin and ordinary user logins, node WebSocket reconnects, forwarding rules, tunnel permissions and traffic statistics. Keep the original PG service/volume and backup until acceptance; then stop the PG container without removing its volume.
6. Rollback: stop the SQLite backend, restore the original Compose/.env and start the old backend against the unchanged PostgreSQL database. Any writes made after SQLite cutover are not automatically replayed to PG; reconcile them before rollback.

## Verification / performance

CI covers both runtime types with both DB engines, including AOT JVM checks, generated IDs, paginated queries, startup and idempotent initialization, node WebSocket, flow concurrency, scheduled statistics, nested dashboard DTOs, restart persistence, backup/restore, migration and failure/no-overwrite tests. The real containers collect startup time, process RSS, backend cgroup idle/warm/peak memory, and PostgreSQL container idle memory for combined idle comparisons. CI is AMD64 only. These are controlled measurements, not a production capacity benchmark; no memory saving figure is asserted until reports exist.
