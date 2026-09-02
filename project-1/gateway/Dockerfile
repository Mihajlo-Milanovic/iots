# build kontekst je koren project-1 direktorijuma (zbog proto/)
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY gateway/pom.xml .
RUN mvn -B -q dependency:go-offline || true
COPY proto/ /proto/
COPY gateway/src/ /build/src/
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /build/target/gateway-1.0.0.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
