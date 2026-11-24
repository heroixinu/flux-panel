package com.admin;

import com.admin.config.DatabaseDefaults;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class DatabaseDefaultsTests {
    private MockEnvironment configure(MockEnvironment env) {
        new DatabaseDefaults().postProcessEnvironment(env, new SpringApplication(AdminApplication.class));
        return env;
    }

    @Test
    void noDatabaseSettingsMeansPersistentSqlite() {
        var env = configure(new MockEnvironment());
        assertEquals("sqlite", env.getProperty("flux.database.type"));
        assertEquals("jdbc:sqlite:./flux.db", env.getProperty("spring.datasource.url"));
        assertEquals("classpath:/db/init/sqlite-schema.sql", env.getProperty("spring.sql.init.schema-locations"));
        assertEquals(1, env.getProperty("spring.datasource.hikari.maximum-pool-size", Integer.class));
    }

    @Test
    void oldPostgresSettingsAreNotSilentlySwitchedToSqlite() {
        var env = configure(new MockEnvironment()
                .withProperty("DB_HOST", "db").withProperty("DB_NAME", "flux")
                .withProperty("DB_USER", "flux").withProperty("DB_PASSWORD", "test"));
        assertEquals("postgresql", env.getProperty("flux.database.type"));
        assertEquals("jdbc:postgresql://db:5432/flux", env.getProperty("spring.datasource.url"));
        assertEquals("classpath:/db/init/schema.sql", env.getProperty("spring.sql.init.schema-locations"));
    }

    @Test
    void explicitTypeOverridesLegacyHostAndExplicitUrlIsHonored() {
        var env = configure(new MockEnvironment().withProperty("DB_HOST", "db")
                .withProperty("DB_TYPE", "SQLite").withProperty("DB_PATH", "/tmp/flux.db"));
        assertEquals("jdbc:sqlite:/tmp/flux.db", env.getProperty("spring.datasource.url"));
        var explicit = configure(new MockEnvironment()
                .withProperty("spring.datasource.url", "jdbc:postgresql://external/flux"));
        assertEquals("postgresql", explicit.getProperty("flux.database.type"));
        assertEquals("jdbc:postgresql://external/flux", explicit.getProperty("spring.datasource.url"));
    }

    @Test
    void conflictingEngineOrInvalidPathFailsFast() {
        assertThrows(IllegalArgumentException.class, () -> configure(new MockEnvironment()
                .withProperty("DB_TYPE", "mysql")));
        assertThrows(IllegalArgumentException.class, () -> configure(new MockEnvironment()
                .withProperty("DB_TYPE", "sqlite").withProperty("spring.datasource.url", "jdbc:postgresql://db/flux")));
        assertThrows(IllegalArgumentException.class, () -> configure(new MockEnvironment()
                .withProperty("DB_PATH", ":memory:")));
    }
}
