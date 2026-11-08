FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /bot
# Sur la plateforme, les dépendances passent par un mandataire (variable HTTPS_PROXY).
# Maven ne lit pas cette variable : on la traduit en paramètres Maven.
RUN if [ -n "$HTTPS_PROXY" ]; then \
      host=$(echo "$HTTPS_PROXY" | sed -E 's#^[a-z]+://([^:/]+).*#\1#'); \
      port=$(echo "$HTTPS_PROXY" | sed -E 's#^[a-z]+://[^:/]+:([0-9]+).*#\1#'); \
      mkdir -p /root/.m2 && printf '<settings><proxies>%s%s</proxies></settings>' \
        "<proxy><id>https</id><active>true</active><protocol>https</protocol><host>$host</host><port>$port</port></proxy>" \
        "<proxy><id>http</id><active>true</active><protocol>http</protocol><host>$host</host><port>$port</port></proxy>" \
        > /root/.m2/settings.xml; \
    fi
COPY pom.xml .
RUN mvn -q dependency:go-offline
COPY src ./src
RUN mvn -q -o package

FROM eclipse-temurin:21-jre
WORKDIR /bot
COPY --from=build /bot/target/bot.jar .
CMD ["java", "-jar", "bot.jar"]
