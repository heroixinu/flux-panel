package com.admin.config;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.boot.context.config.ConfigDataEnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

/**
 * Selects defaults at environment preparation time, not at AOT build time.
 * Existing deployments with DB_HOST keep using PostgreSQL; new installations
 * without database settings use SQLite. Explicit Spring properties take priority.
 */
public final class DatabaseDefaults implements EnvironmentPostProcessor, Ordered {
    @Override
    public int getOrder() {
        return ConfigDataEnvironmentPostProcessor.ORDER + 1;
    }

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment env, SpringApplication application) {
        String explicitUrl = env.getProperty("spring.datasource.url");
        String type = env.getProperty("DB_TYPE", "").trim().toLowerCase(Locale.ROOT);
        if (type.isEmpty()) {
            if (explicitUrl != null && !explicitUrl.isBlank()) {
                if (explicitUrl.startsWith("jdbc:sqlite:")) type = "sqlite";
                else if (explicitUrl.startsWith("jdbc:postgresql:")) type = "postgresql";
                else throw new IllegalArgumentException("Unsupported datasource JDBC URL");
            } else {
                type = env.getProperty("DB_HOST", "").isBlank() ? "sqlite" : "postgresql";
            }
        }
        if (!type.equals("sqlite") && !type.equals("postgresql")) {
            throw new IllegalArgumentException("DB_TYPE must be sqlite or postgresql");
        }
        if (explicitUrl != null && !explicitUrl.startsWith("jdbc:" + type + ":")) {
            throw new IllegalArgumentException("DB_TYPE and spring.datasource.url disagree");
        }

        Map<String, Object> defaults = new LinkedHashMap<>();
        defaults.put("flux.database.type", type);
        defaults.put("spring.datasource.hikari.minimum-idle", 1);
        if (type.equals("sqlite")) {
            String path = env.getProperty("DB_PATH", "./flux.db");
            if (path.isBlank() || path.contains("?") || path.contains("#") || path.equals(":memory:")) {
                throw new IllegalArgumentException("DB_PATH must name a persistent SQLite file (no URL query or fragment)");
            }
            defaults.put("spring.datasource.driver-class-name", "org.sqlite.JDBC");
            defaults.put("spring.datasource.url", "jdbc:sqlite:" + path);
            // One connection serializes writes (including scheduled tasks) in this
            // single-instance application and avoids SQLITE_BUSY_SNAPSHOT upgrades.
            defaults.put("spring.datasource.hikari.maximum-pool-size", 1);
            defaults.put("spring.datasource.hikari.max-lifetime", 0);
            defaults.put("spring.datasource.hikari.idle-timeout", 0);
            defaults.put("spring.datasource.hikari.data-source-properties.busy_timeout", 10000);
            defaults.put("spring.datasource.hikari.data-source-properties.journal_mode", "WAL");
            defaults.put("spring.datasource.hikari.data-source-properties.synchronous", "NORMAL");
            defaults.put("spring.datasource.hikari.data-source-properties.foreign_keys", "on");
            defaults.put("spring.datasource.hikari.data-source-properties.cache_size", -2048);
            defaults.put("spring.sql.init.schema-locations", "classpath:/db/init/sqlite-schema.sql");
        } else {
            defaults.put("spring.datasource.driver-class-name", "org.postgresql.Driver");
            defaults.put("spring.datasource.url", "jdbc:postgresql://${DB_HOST}:${DB_PORT:5432}/${DB_NAME}");
            defaults.put("spring.datasource.username", "${DB_USER}");
            defaults.put("spring.datasource.password", "${DB_PASSWORD}");
            defaults.put("spring.datasource.hikari.maximum-pool-size", 5);
            defaults.put("spring.datasource.hikari.max-lifetime", 500000);
            defaults.put("spring.datasource.hikari.idle-timeout", 120000);
            defaults.put("spring.sql.init.schema-locations", "classpath:/db/init/schema.sql");
        }
        env.getPropertySources().addLast(new MapPropertySource("fluxDatabaseDefaults", defaults));
    }
}
