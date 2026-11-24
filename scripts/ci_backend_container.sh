#!/usr/bin/env bash
# CI only: starts one disposable backend against the supplied fresh PG database.
set -euo pipefail
image="$1"
metrics="$2"
name="flux-backend-smoke"
mkdir -p "$(dirname "$metrics")"
cleanup() {
  local result=$?
  trap - EXIT
  docker logs "$name" > "$metrics.log" 2>&1 || true
  if [[ "$result" != 0 ]]; then
    cat "$metrics.log" >&2
  fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  exit "$result"
}
check_logs() {
  if grep -E 'MissingReflectionRegistrationError|MissingResourceRegistrationError|Unexpected error occurred in scheduled task' "$1"; then
    echo "Backend contains Native metadata or scheduled task errors" >&2
    return 1
  fi
}
trap cleanup EXIT
start() {
  local before after
  before=$(date +%s%3N)
  docker run -d --name "$name" --network host --memory=512m --memory-swap=512m --cpus=2 \
    -e DB_HOST=127.0.0.1 -e DB_PORT="$PGPORT" -e DB_NAME="$PGDATABASE" \
    -e DB_USER="$PGUSER" -e DB_PASSWORD="$PGPASSWORD" \
    -e JWT_SECRET=ci-integration-only-32-character-secret -e LOG_DIR=/tmp/flux-logs \
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
[[ "$(psql -XAtq -c "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()")" == 0 ]]
ready=$(start)
sleep 15
idle=$(memory)
idle_rss=$(rss)
python scripts/smoke_backend.py
sleep 10
warm=$(memory)
peak=$(docker exec "$name" cat /sys/fs/cgroup/memory.peak | tr -d '\r')
docker stop -t 35 "$name"
[[ "$(docker inspect -f '{{.State.OOMKilled}}' "$name")" == false ]]
docker logs "$name" > "$metrics.first.log" 2>&1
check_logs "$metrics.first.log"
docker rm "$name"
restart=$(start)
python scripts/smoke_backend.py --restart
printf '{"ready_ms":%s,"restart_ready_ms":%s,"idle_cgroup_bytes":%s,"idle_rss_bytes":%s,"warm_cgroup_bytes":%s,"peak_cgroup_bytes":%s}\n' \
 "$ready" "$restart" "$idle" "$idle_rss" "$warm" "$peak" > "$metrics"
cat "$metrics"
docker stop -t 35 "$name"
[[ "$(docker inspect -f '{{.State.OOMKilled}}' "$name")" == false ]]
docker logs "$name" > "$metrics.log" 2>&1
check_logs "$metrics.log"
