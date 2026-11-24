package com.admin;

import com.admin.common.dto.ForwardWithTunnelDto;
import com.admin.common.dto.LoginDto;
import com.admin.controller.FlowController;
import com.admin.entity.ViteConfig;
import com.admin.entity.StatisticsFlow;
import com.admin.service.StatisticsFlowService;
import java.util.List;
import com.admin.mapper.ForwardMapper;
import com.admin.mapper.ViteConfigMapper;
import com.admin.service.UserService;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.mapper.MapperFactoryBean;
import org.springframework.beans.factory.config.RuntimeBeanReference;
import org.springframework.context.ConfigurableApplicationContext;
import javax.sql.DataSource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
@Transactional
class DatabaseIntegrationTests {
    @Autowired JdbcTemplate jdbc;
    @Autowired org.springframework.core.env.Environment environment;
    @Autowired DataSource dataSource;
    @Autowired UserService users;
    @Autowired ViteConfigMapper configs;
    @Autowired ForwardMapper forwards;
    @Autowired FlowController flows;
    @Autowired StatisticsFlowService statistics;
    @Autowired ConfigurableApplicationContext context;
    @Autowired SqlSessionTemplate sqlSessionTemplate;

    @Test
    void allMapperFactoriesHaveExplicitSessionTemplateReferences() {
        // AOT cannot depend on implicit AUTOWIRE_BY_TYPE for mapper factories.
        for (String name : List.of("forwardMapper", "nodeMapper", "speedLimitMapper",
                "statisticsFlowMapper", "tunnelMapper", "userMapper", "userTunnelMapper",
                "viteConfigMapper")) {
            var definition = context.getBeanFactory().getBeanDefinition(name);
            var reference = assertInstanceOf(RuntimeBeanReference.class,
                    definition.getPropertyValues().get("sqlSessionTemplate"), name);
            assertEquals("sqlSessionTemplate", reference.getBeanName(), name);
            var factory = context.getBean("&" + name, MapperFactoryBean.class);
            assertSame(sqlSessionTemplate, factory.getSqlSession(), name);
        }
    }

    @Test
    void initializesAllTablesAndDoesNotChangeExistingDataOnRestart() {
        // Both engines must initialize all eight business tables before serving requests.
        boolean sqlite = "sqlite".equals(environment.getProperty("flux.database.type"));
        String tables = "('forward','node','speed_limit','statistics_flow','tunnel','app_user','user_tunnel','vite_config')";
        Long count = jdbc.queryForObject(sqlite
                ? "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN " + tables
                : "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN " + tables,
                Long.class);
        if (sqlite) {
            assertEquals("wal", jdbc.queryForObject("PRAGMA journal_mode", String.class));
            assertEquals(10000, jdbc.queryForObject("PRAGMA busy_timeout", Integer.class));
            assertEquals(2, jdbc.queryForObject("PRAGMA synchronous", Integer.class));
            assertEquals(1, jdbc.queryForObject("PRAGMA foreign_keys", Integer.class));
            assertEquals(1, ((com.zaxxer.hikari.HikariDataSource) dataSource).getMaximumPoolSize());
        }
        assertEquals(8L, count);
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM app_user WHERE username='admin_user'", Long.class));
        assertEquals("flux", jdbc.queryForObject("SELECT value FROM vite_config WHERE name='app_name'", String.class));

        jdbc.update("UPDATE vite_config SET value = 'keep-existing-value' WHERE name = 'app_name'");
        jdbc.update("INSERT INTO vite_config (name,value,time) VALUES ('existing_custom_key','custom',1)");
        Long usersBefore = jdbc.queryForObject("SELECT count(*) FROM app_user", Long.class);
        Long configsBefore = jdbc.queryForObject("SELECT count(*) FROM vite_config", Long.class);

        // Re-run the same SQL against an existing database. No seeded data should change.
        ResourceDatabasePopulator populator = new ResourceDatabasePopulator(
            new ClassPathResource(sqlite ? "db/init/sqlite-schema.sql" : "db/init/schema.sql"),
            new ClassPathResource("db/init/data.sql")
        );
        populator.execute(dataSource);
        assertEquals(usersBefore, jdbc.queryForObject("SELECT count(*) FROM app_user", Long.class));
        assertEquals(configsBefore, jdbc.queryForObject("SELECT count(*) FROM vite_config", Long.class));
        assertEquals("keep-existing-value", jdbc.queryForObject(
            "SELECT value FROM vite_config WHERE name = 'app_name'", String.class));
        assertEquals("custom", jdbc.queryForObject(
            "SELECT value FROM vite_config WHERE name = 'existing_custom_key'", String.class));
    }

    @Test
    void loginIdentityPaginationJoinAndFlowUpdates() {
        LoginDto login = new LoginDto();
        // Historical captcha settings must not block login after retirement.
        jdbc.update("INSERT INTO vite_config (name,value,time) VALUES ('captcha_enabled','true',1)");
        assertEquals(0, new com.admin.controller.CaptchaController().check().getData());
        login.setUsername("ADMIN_USER");
        login.setPassword("admin_user");
        assertEquals(0, users.login(login).getCode());
        login.setPassword("wrong");
        assertNotEquals(0, users.login(login).getCode());

        ViteConfig config = new ViteConfig();
        config.setName("integration_test");
        config.setValue("value");
        config.setTime(1L);
        assertEquals(1, configs.insert(config));
        assertNotNull(config.getId());
        assertTrue(config.getId() > 1);
        assertEquals("value", configs.selectById(config.getId()).getValue());
        assertEquals(1, configs.selectPage(new Page<>(1, 1), new QueryWrapper<ViteConfig>().eq("name", "integration_test")).getTotal());

        Integer nodeId = jdbc.queryForObject("INSERT INTO node (name, secret, server_ip, port_sta, port_end, created_time, status) VALUES ('node', 'integration-secret', '127.0.0.1', 1000, 2000, 1, 1) RETURNING id", Integer.class);
        Integer tunnelId = jdbc.queryForObject("INSERT INTO tunnel (name, in_node_id, in_ip, out_node_id, out_ip, type, flow, created_time, updated_time, status) VALUES ('tunnel', ?, '127.0.0.1', ?, '127.0.0.1', 1, 1, 1, 1, 1) RETURNING id", Integer.class, nodeId, nodeId);
        Integer forwardId = jdbc.queryForObject("INSERT INTO forward (user_id, user_name, name, tunnel_id, in_port, remote_addr, created_time, updated_time, status) VALUES (1, 'admin_user', 'forward', ?, 1234, 'example', 1, 1, 1) RETURNING id", Integer.class, tunnelId);
        ForwardWithTunnelDto forward = forwards.selectForwardsWithTunnelByUserId(1).stream().filter(f -> f.getId().equals(forwardId.longValue())).findFirst().orElseThrow();
        assertEquals("tunnel", forward.getTunnelName());
        assertEquals(tunnelId, forward.getTunnelId());
        assertEquals(1234, forward.getInPort());

        Integer permissionId = jdbc.queryForObject("INSERT INTO user_tunnel (user_id, tunnel_id, num, flow, flow_reset_time, exp_time, status) VALUES (1, ?, 10, 99999, 0, 2727251700000, 1) RETURNING id", Integer.class, tunnelId);
        assertEquals("ok", flows.uploadFlowData("{\"n\":\"" + forwardId + "_1_" + permissionId + "_tcp\",\"u\":3,\"d\":5}", "integration-secret"));
        assertEquals(5L, jdbc.queryForObject("SELECT in_flow FROM forward WHERE id = ?", Long.class, forwardId));
        assertEquals(3L, jdbc.queryForObject("SELECT out_flow FROM forward WHERE id = ?", Long.class, forwardId));
        assertEquals(5L, jdbc.queryForObject("SELECT in_flow FROM app_user WHERE id = 1", Long.class));
        assertEquals(5L, jdbc.queryForObject("SELECT in_flow FROM user_tunnel WHERE id = ?", Long.class, permissionId));
        StatisticsFlow record = new StatisticsFlow();
        record.setUserId(1L);
        record.setFlow(5L);
        record.setTotalFlow(5L);
        record.setTime("2026-01-01");
        record.setCreatedTime(1L);
        StatisticsFlow second = new StatisticsFlow();
        second.setUserId(1L);
        second.setFlow(9007199254740993L);
        second.setTotalFlow(9007199254740993L);
        second.setTime("2026-01-01");
        second.setCreatedTime(2L);
        statistics.saveSamples(List.of(record, second));
        assertNotNull(record.getId());
        assertNotNull(second.getId());
        assertNotEquals(record.getId(), second.getId());
        assertEquals(9007199254740993L, statistics.getById(second.getId()).getTotalFlow());
        jdbc.update("UPDATE tunnel SET traffic_ratio=1.3 WHERE id=?", tunnelId);
        assertEquals(0, new java.math.BigDecimal("1.3").compareTo(
                jdbc.queryForObject("SELECT traffic_ratio FROM tunnel WHERE id=?", java.math.BigDecimal.class, tunnelId)));
        assertThrows(IllegalArgumentException.class, () -> flows.uploadFlowData("{\"n\":\"bad_1_0_tcp\",\"u\":3,\"d\":5}", "integration-secret"));
    }
}
