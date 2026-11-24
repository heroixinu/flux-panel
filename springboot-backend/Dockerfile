FROM maven:3.9.6-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
COPY ci/mvn_retry.sh ./ci/mvn_retry.sh
COPY src ./src
RUN --mount=type=cache,target=/root/.m2/repository \
    bash ci/mvn_retry.sh /tmp/maven-build.log clean package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
ENV JAVA_OPTS="-Xms32m -Xmx192m -XX:+UseSerialGC -Dfile.encoding=UTF-8 -Duser.timezone=Asia/Shanghai"
ENV LANG=C.UTF-8

# curl is required by the Compose health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/target/*.jar /app/app.jar
EXPOSE 6365
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
