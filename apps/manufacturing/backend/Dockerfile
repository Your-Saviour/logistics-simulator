FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /build
COPY apps/manufacturing/backend/pom.xml ./pom.xml
RUN mvn -B -q dependency:go-offline
ENV MAVEN_OPTS=-Xmx256m
COPY apps/manufacturing/backend/src ./src
RUN mvn -B -q package -DskipTests
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S manufacturing && adduser -S -G manufacturing manufacturing
COPY --from=build /build/target/manufacturing-1.0.0.jar /app/manufacturing.jar
USER manufacturing
EXPOSE 8000
ENTRYPOINT ["java","-jar","/app/manufacturing.jar"]
