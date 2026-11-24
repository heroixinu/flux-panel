#!/usr/bin/env bash
# CI only. Run the AOT-processed jar against a separate disposable database.
set -euo pipefail
jar="$(realpath "$1")"
root="$(cd "$(dirname "$0")/.." && pwd)"
log="$PWD/aot-preflight.log"
test -f "$jar"
createdb --maintenance-db=postgres flux_aot
export PGDATABASE=flux_aot DB_NAME=flux_aot
export FLUX_TEST_URL=http://127.0.0.1:6366
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
  if [[ "$result" != 0 ]]; then
    cat "$log" >&2
  fi
  exit "$result"
}
trap cleanup EXIT
for i in $(seq 1 300); do
  if curl -fs --max-time 1 "$FLUX_TEST_URL/flow/test" | grep -qx test; then
    grep -q 'Starting AOT-processed' "$log"
    python "$root/scripts/smoke_backend.py"
    echo 'Spring AOT JVM regression passed'
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || exit 1
  sleep 0.2
done
echo 'AOT JVM readiness check timed out' >&2
exit 1
