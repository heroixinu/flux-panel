#!/usr/bin/env bash
# CI only: test the actual image, persistent restart and SQLite online backup/restore.
set -euo pipefail
image="$1"
metrics="$2"
engine="${3:-postgresql}"
name="flux-backend-smoke-$engine"
mkdir -p "$(dirname "$metrics")"
scratch=$(mktemp -d)
data_dir="$scratch/data"
backup_dir="$scratch/backup"
mkdir -p "$data_dir" "$backup_dir"
export FLUX_TEST_DB="$engine"
export PASSKEY_ORIGIN=http://localhost:6365
passkey_state="$scratch/passkeys.json"
db_args=()
case "$engine" in
  sqlite)
    # Intentionally omit DB_TYPE and DB_HOST to exercise the default image.
    export FLUX_TEST_DB_PATH="$data_dir/flux.db"
    db_args=(--user "$(id -u):$(id -g)" --mount "type=bind,source=$data_dir,target=/app/data")
    ;;
  postgresql)
    db_args=(-e DB_HOST=127.0.0.1 -e DB_PORT="$PGPORT" -e DB_NAME="$PGDATABASE" -e DB_USER="$PGUSER" -e DB_PASSWORD="$PGPASSWORD")
    [[ "$(psql -XAtq -c "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()")" == 0 ]]
    ;;
  *) echo "Unsupported engine: $engine" >&2; rm -rf "$scratch"; exit 1 ;;
esac
cleanup() {
  local result=$?
  trap - EXIT
  docker logs "$name" > "$metrics.log" 2>&1 || true
  if [[ "$result" != 0 ]]; then cat "$metrics.log" >&2; fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$scratch"
  exit "$result"
}
check_logs() {
  if grep -E 'MissingReflectionRegistrationError|MissingResourceRegistrationError|Unexpected error occurred in scheduled task|Type definition error:|InvalidDefinitionException|No serializer found for class|SQLITE_BUSY|SQLITE_LOCKED|database is locked' "$1"; then
    echo "Backend contains Native metadata, serialization, SQLite locking or scheduled task errors" >&2
    return 1
  fi
}
trap cleanup EXIT
start() {
  local before after
  before=$(date +%s%3N)
  local recovery="${1:-false}"
  docker run -d --name "$name" --network host --memory=512m --memory-swap=512m --cpus=2 \
    "${db_args[@]}" \
    -e JWT_SECRET=ci-integration-only-32-character-secret -e LOG_DIR=/tmp/flux-logs \
    -e PASSKEY_ENABLED=true -e PASSKEY_ORIGIN="$PASSKEY_ORIGIN" -e PASSKEY_RECOVERY_PASSWORD_LOGIN="$recovery" \
    -e 'FLUX_TASKS_STATISTICS_CRON=*/5 * * * * *' -e 'FLUX_TASKS_RESET_CRON=*/5 * * * * *' \
    "$image" >/dev/null
  for i in $(seq 1 600); do
    if curl -fsS --max-time 1 http://127.0.0.1:6365/flow/test | grep -qx test; then
      after=$(date +%s%3N)
      echo "$((after-before))"
      return
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]]; then
      docker logs "$name" >&2
      return 1
    fi
    sleep 0.1
  done
  echo 'Application failed readiness check' >&2
  docker logs "$name" >&2
  return 1
}
memory() {
  docker exec "$name" cat /sys/fs/cgroup/memory.current | tr -d '\r'
}
rss() {
  docker exec "$name" sh -c "awk '/^VmRSS:/{print \$2*1024}' /proc/1/status"
}
stop_and_check() {
  local suffix="$1"
  docker stop -t 35 "$name"
  [[ "$(docker inspect -f '{{.State.OOMKilled}}' "$name")" == false ]]
  docker logs "$name" > "$metrics.$suffix.log" 2>&1
  check_logs "$metrics.$suffix.log"
}
ready=$(start)
sleep 15
idle=$(memory)
idle_rss=$(rss)
pg_idle=0
if [[ "$engine" == postgresql && -n "${FLUX_PG_CONTAINER:-}" ]]; then
  pg_idle=$(docker exec "$FLUX_PG_CONTAINER" cat /sys/fs/cgroup/memory.current | tr -d '\r')
fi
python scripts/smoke_backend.py
python scripts/smoke_passkey.py --state "$passkey_state"
sleep 10
warm=$(memory)
peak=$(docker exec "$name" cat /sys/fs/cgroup/memory.peak | tr -d '\r')
if [[ "$engine" == sqlite ]]; then
  docker exec "$name" sqlite3 -bail -cmd '.timeout 10000' /app/data/flux.db ".backup '/tmp/flux-ci-backup.db'"
  [[ "$(docker exec "$name" sqlite3 -bail /tmp/flux-ci-backup.db 'PRAGMA integrity_check;')" == ok ]]
  docker cp "$name:/tmp/flux-ci-backup.db" "$backup_dir/flux.db"
  test -s "$backup_dir/flux.db"
fi
stop_and_check first
docker rm "$name"
restart=$(start)
python scripts/smoke_passkey.py --state "$passkey_state" --restart
python scripts/smoke_backend.py --restart
stop_and_check restart
restore=0
if [[ "$engine" == sqlite ]]; then
  docker rm "$name"
  # Restore the online backup to a fresh directory, not over live WAL/SHM.
  mv "$data_dir" "$scratch/original"
  mkdir "$data_dir"
  cp "$backup_dir/flux.db" "$data_dir/flux.db"
  chmod 600 "$data_dir/flux.db"
  restore=$(start)
  python scripts/smoke_passkey.py --state "$passkey_state" --restart
  python scripts/smoke_backend.py --restart
  stop_and_check restore
  # Restore again to test emergency recovery with the persisted passkey-only policy.
  docker rm "$name"
  rm -rf "$data_dir"
  mkdir "$data_dir"
  cp "$backup_dir/flux.db" "$data_dir/flux.db"
  chmod 600 "$data_dir/flux.db"
  start true >/dev/null
  python scripts/smoke_passkey.py --recovery
  stop_and_check recovery
  docker rm "$name"
  start >/dev/null
  python scripts/smoke_backend.py --restart
  stop_and_check recovered
fi
printf '{"engine":"%s","ready_ms":%s,"restart_ready_ms":%s,"restore_ready_ms":%s,"idle_cgroup_bytes":%s,"idle_rss_bytes":%s,"warm_cgroup_bytes":%s,"peak_cgroup_bytes":%s,"postgres_idle_cgroup_bytes":%s,"combined_idle_cgroup_bytes":%s}\n' \
 "$engine" "$ready" "$restart" "$restore" "$idle" "$idle_rss" "$warm" "$peak" "$pg_idle" "$((idle+pg_idle))" > "$metrics"
cat "$metrics"
