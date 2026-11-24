#!/usr/bin/env bash
# JVM and Native builds: retry transient Maven Central failures.
# Do not retry application, AOT or native compiler errors.
set -euo pipefail
log="$1"
shift
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
: > "$log"

# Keep the same repository ID for local artifact provenance; alternate URLs
# replace the default Central repositories via an active settings profile.
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
  cat > "$scratch/settings.xml" <<EOF
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <profiles>
    <profile>
      <id>central-ci</id>
      <repositories>
        <repository>
          <id>central</id><url>$endpoint</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>false</enabled></snapshots>
        </repository>
      </repositories>
      <pluginRepositories>
        <pluginRepository>
          <id>central</id><url>$endpoint</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>false</enabled></snapshots>
        </pluginRepository>
      </pluginRepositories>
    </profile>
  </profiles>
  <activeProfiles><activeProfile>central-ci</activeProfile></activeProfiles>
</settings>
EOF
  extra=()
  if (( i > 0 )); then extra+=(-U); fi
  if mvn -B -ntp -s "$scratch/settings.xml" \
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
