FROM maven:3.9.6-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
COPY ci/mvn_retry.sh ./ci/mvn_retry.sh
COPY src ./src
RUN --mount=type=cache,target=/root/.m2/repository \
    bash ci/mvn_retry.sh /tmp/maven-build.log clean package -DskipTests

FROM eclipse-temurin:21-jre AS runtime-base
WORKDIR /app
ENV JAVA_OPTS="-Xms32m -Xmx192m -XX:+UseSerialGC -Dfile.encoding=UTF-8 -Duser.timezone=Asia/Shanghai"
ENV LANG=C.UTF-8 DB_PATH=/app/data/flux.db

# curl is required by the Compose health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl sqlite3 python3 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/import
COPY docker/import_legacy.py /app/import-legacy.py
COPY --chmod=0755 docker/start-backend.sh /app/start-backend.sh
COPY src/main/resources/db/init/sqlite-schema.sql /app/sqlite-schema.sql
EXPOSE 6365
ENTRYPOINT ["/app/start-backend.sh", "jvm"]

# CI consumes the JAR built on the runner with the shared Maven cache.
# BuildKit skips the source build stage for this target.
FROM runtime-base AS prebuilt
COPY jvm/app.jar /app/app.jar

# Default target preserves standalone Docker builds from source.
FROM runtime-base AS runtime
COPY --from=build /app/target/admin-0.0.1-SNAPSHOT.jar /app/app.jar
