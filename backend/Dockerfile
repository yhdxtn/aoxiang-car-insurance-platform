FROM docker.m.daocloud.io/library/maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src src
RUN mvn -B -DskipTests package
FROM docker.m.daocloud.io/library/eclipse-temurin:21.0.9_10-jre-jammy
WORKDIR /app
RUN groupadd --system insurance && useradd --system --gid insurance insurance && mkdir -p /app/data/private-files && chown -R insurance:insurance /app
COPY --from=build /build/target/mini-insurance-api-1.0.0.jar app.jar
USER insurance
EXPOSE 18080
ENTRYPOINT ["java","-jar","/app/app.jar"]
