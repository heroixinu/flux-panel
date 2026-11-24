#!/bin/sh
set -eu

case "${DB_IMPORT_ENABLED:-false}" in
  false|0|"") ;;
  true|1)
    # Import before Spring Boot opens a connection or seeds a default admin.
    if [ "${DB_TYPE:-sqlite}" != sqlite ] ||
       [ -n "${DB_HOST:-}${DB_PORT:-}${DB_NAME:-}${DB_USER:-}${DB_PASSWORD:-}${SPRING_DATASOURCE_URL:-}${SPRING_APPLICATION_JSON:-}" ]; then
      echo "Legacy import requires SQLite and no legacy connection settings or datasource override" >&2
      exit 1
    fi
    for arg in "$@"; do
      case "$arg" in
        *spring.datasource*|*spring.config*|*DB_PATH*|*DB_TYPE*|*spring.application.json*)
          echo "Legacy import does not allow database/config command-line overrides" >&2
          exit 1 ;;
      esac
    done
    # JVM launch options can also override Spring datasource configuration.
    for opts in "${JAVA_OPTS:-}" "${JAVA_TOOL_OPTIONS:-}" "${JDK_JAVA_OPTIONS:-}" "${_JAVA_OPTIONS:-}"; do
      case "$opts" in
        *spring.datasource*|*spring.config*|*DB_PATH*|*DB_TYPE*|*spring.application.json*)
          echo "Legacy import does not allow database/config JVM overrides" >&2
          exit 1 ;;
      esac
    done
    export DB_TYPE=sqlite
    case "${DB_PATH:-/app/data/flux.db}" in
      *\?*|*\#*|*:memory:|file:*) echo "Invalid SQLite import destination" >&2; exit 1 ;;
    esac
    python3 /app/import-legacy.py \
      --destination "${DB_PATH:-/app/data/flux.db}" \
      --directory "${DB_IMPORT_DIR:-/app/import}" \
      --file "${DB_IMPORT_FILE:-}" \
      --schema /app/sqlite-schema.sql \
      --max-bytes "${DB_IMPORT_MAX_BYTES:-1073741824}"
    ;;
  *) echo "DB_IMPORT_ENABLED must be true or false" >&2; exit 1 ;;
esac

if [ "$1" = jvm ]; then
  shift
  # JAVA_OPTS intentionally retains the existing word-splitting contract.
  exec java $JAVA_OPTS -jar /app/app.jar "$@"
fi
exec "$@"
