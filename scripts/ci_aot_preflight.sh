#!/usr/bin/env bash
# Run the SAME AOT-processed artifact against both database engines.
set -euo pipefail
jar="$(realpath "$1")"
engine="${2:-postgresql}"
root="$(cd "$(dirname "$0")/.." && pwd)"
log="$PWD/aot-preflight-$engine.log"
test -f "$jar"
export FLUX_TEST_DB="$engine"
scratch=
case "$engine" in
  sqlite)
    scratch=$(mktemp -d)
    unset DB_TYPE DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD
    export DB_PATH="$scratch/flux.db" FLUX_TEST_DB_PATH="$scratch/flux.db"
    ;;
  postgresql)
    unset DB_TYPE
    createdb --maintenance-db=postgres flux_aot
    export PGDATABASE=flux_aot DB_NAME=flux_aot
    ;;
  *) echo "Unsupported engine: $engine" >&2; exit 1 ;;
esac
export FLUX_TEST_URL=http://127.0.0.1:6366
export PASSKEY_ENABLED=true PASSKEY_ORIGIN=http://localhost:6366
passkey_state=$(mktemp)
export FLUX_TASKS_STATISTICS_CRON='*/5 * * * * *'
export FLUX_TASKS_RESET_CRON='*/5 * * * * *'
java -Xms32m -Xmx192m -XX:+UseSerialGC \
  -Dspring.aot.enabled=true -Duser.timezone=Asia/Shanghai -Dfile.encoding=UTF-8 \
  -jar "$jar" --server.port=6366 > "$log" 2>&1 &
pid=$!
cleanup() {
  local result=$?
  trap - EXIT
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  if [[ "$result" != 0 ]]; then cat "$log" >&2; fi
  rm -f "$passkey_state"
  if [[ -n "$scratch" ]]; then rm -rf "$scratch"; fi
  exit "$result"
}
trap cleanup EXIT
for i in $(seq 1 300); do
  if curl -fs --max-time 1 "$FLUX_TEST_URL/flow/test" | grep -qx test; then
    grep -q 'Starting AOT-processed' "$log"
    python "$root/scripts/smoke_backend.py"
    python "$root/scripts/smoke_passkey.py" --state "$passkey_state"
    if grep -E 'MissingReflectionRegistrationError|MissingResourceRegistrationError|Unexpected error occurred in scheduled task|Type definition error:|SQLITE_BUSY|SQLITE_LOCKED|database is locked' "$log"; then
      exit 1
    fi
    echo "Spring AOT JVM regression passed ($engine)"
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || exit 1
  sleep 0.2
done
echo 'AOT JVM readiness check timed out' >&2
exit 1
