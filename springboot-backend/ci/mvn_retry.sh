#!/usr/bin/env bash
# JVM and Native builds: retry transient Maven Central failures.
# Do not retry application, AOT or native compiler errors.
set -euo pipefail
log="$1"
shift
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
: > "$log"

# Use the default Maven configuration first so the shared Central cache is reusable.
# On a transient failure, use a real mirror (not a repository profile) to redirect
# every Central request, including repositories declared by transitive POMs.
# Both alternate Central endpoints use the same mirror ID for cache provenance.
endpoints=(
  'https://repo.maven.apache.org/maven2'
  'https://maven-central.storage-download.googleapis.com/maven2'
  'https://repo1.maven.org/maven2'
  'https://repo.maven.apache.org/maven2'
)
transient='HTTP (Status: )?(429|502|503|504)|status code: (429|502|503|504)|status (429|502|503|504)|Read timed out|Connection reset|Connection timed out|Temporary failure in name resolution|Connect timed out|Premature end of Content-Length'
for i in 0 1 2 3; do
  endpoint="${endpoints[$i]}"
  echo "Maven attempt $((i + 1))/4: $endpoint" | tee -a "$log"
  extra=()
  if (( i > 0 )); then extra+=(-U); fi
  if (( i == 1 || i == 2 )); then
    cat > "$scratch/settings.xml" <<EOF
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <mirrors>
    <mirror>
      <id>central-ci-fallback</id>
      <name>Central fallback</name>
      <url>$endpoint</url>
      <mirrorOf>central</mirrorOf>
    </mirror>
  </mirrors>
</settings>
EOF
    extra+=(-s "$scratch/settings.xml")
  fi
  if mvn -B -ntp \
    -Daether.connector.connectTimeout=10000 \
    -Daether.connector.requestTimeout=45000 \
    -Daether.connector.http.retryHandler.count=1 \
    -Daether.connector.http.retryHandler.intervalMax=15000 \
    "${extra[@]}" "$@" 2>&1 | tee "$scratch/attempt.log" | tee -a "$log"; then
    exit 0
  fi
  if (( i == 3 )) || ! grep -Eiq "$transient" "$scratch/attempt.log"; then
    exit 1
  fi
  sleep "$(( (i + 1) * 10 ))"
done
