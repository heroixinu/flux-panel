package com.admin;

import com.admin.common.dto.UserPackageDto;
import com.admin.common.lang.R;
import com.admin.config.FluxRuntimeHints;
import com.admin.entity.StatisticsFlow;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.aot.hint.MemberCategory;
import org.springframework.aot.hint.RuntimeHints;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.core.type.classreading.CachingMetadataReaderFactory;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class NativeRuntimeHintsTests {
    @Test
    void everyApplicationDtoAndEntityIncludingNestedTypesHasNativeHints() throws Exception {
        RuntimeHints hints = new RuntimeHints();
        ClassLoader loader = getClass().getClassLoader();
        new FluxRuntimeHints().registerHints(hints, loader);
        var resolver = new PathMatchingResourcePatternResolver(loader);
        var readerFactory = new CachingMetadataReaderFactory(resolver);
        for (String path : List.of("com/admin/common/dto", "com/admin/entity")) {
            var resources = resolver.getResources("classpath*:" + path + "/**/*.class");
            assertTrue(resources.length > 0, "No classes found in " + path);
            for (var resource : resources) {
                String className = readerFactory.getMetadataReader(resource).getClassMetadata().getClassName();
                Class<?> type = Class.forName(className, false, loader);
                if (type.isSynthetic() || type.isAnonymousClass() || type.isLocalClass()) {
                    continue;
                }
                var hint = hints.reflection().getTypeHint(type);
                assertNotNull(hint, "Missing Native hints: " + className);
                assertTrue(hint.getMemberCategories().contains(MemberCategory.INVOKE_PUBLIC_METHODS),
                        "Missing bean getter/setter invocation hints: " + className);
                assertTrue(hint.getMemberCategories().contains(MemberCategory.INVOKE_DECLARED_CONSTRUCTORS),
                        "Missing constructor hints: " + className);
            }
        }
    }

    @Test
    void dashboardResponseContainsAllNestedDtos() throws Exception {
        var user = new UserPackageDto.UserInfoDto();
        user.setId(7L);
        user.setUser("dashboard-user");
        var tunnel = new UserPackageDto.UserTunnelDetailDto();
        tunnel.setId(8);
        tunnel.setTunnelName("test-tunnel");
        var forward = new UserPackageDto.UserForwardDetailDto();
        forward.setId(9L);
        forward.setName("test-forward");
        var stats = new StatisticsFlow();
        stats.setUserId(7L);
        stats.setTotalFlow(16L);
        var dto = new UserPackageDto();
        dto.setUserInfo(user);
        dto.setTunnelPermissions(List.of(tunnel));
        dto.setForwards(List.of(forward));
        dto.setStatisticsFlows(List.of(stats));

        var mapper = new ObjectMapper();
        var json = mapper.readTree(mapper.writeValueAsString(R.ok(dto)));
        assertEquals(0, json.path("code").asInt(-1));
        var data = json.path("data");
        assertEquals("dashboard-user", data.path("userInfo").path("user").asText());
        assertEquals("test-tunnel", data.path("tunnelPermissions").get(0).path("tunnelName").asText());
        assertEquals("test-forward", data.path("forwards").get(0).path("name").asText());
        assertEquals(16L, data.path("statisticsFlows").get(0).path("totalFlow").asLong());
    }
}
