package com.admin.config;

import com.admin.common.dto.*;
import com.admin.common.lang.R;
import com.admin.common.utils.WebSocketServer;
import com.admin.controller.FlowController;
import com.admin.entity.*;
import com.admin.service.impl.ForwardServiceImpl;
import com.admin.service.impl.TunnelServiceImpl;
import org.springframework.aot.hint.ExecutableMode;
import org.springframework.aot.hint.MemberCategory;
import org.mybatis.spring.SqlSessionTemplate;
import java.util.List;
import org.springframework.aot.hint.RuntimeHints;
import org.springframework.aot.hint.RuntimeHintsRegistrar;

/**
 * MyBatis-Plus supplies mapper AOT integration. These hints cover application-owned
 * DTOs, reflective bean copies and SQL/XML files that are accessed outside MVC.
 */
public final class FluxRuntimeHints implements RuntimeHintsRegistrar {
    @Override
    public void registerHints(RuntimeHints hints, ClassLoader loader) {
        hints.resources().registerPattern("db/init/*.sql");
        hints.resources().registerPattern("META-INF/spring.factories");
        hints.reflection().registerType(org.springframework.aot.hint.TypeReference.of("org.sqlite.JDBC"),
                MemberCategory.INVOKE_PUBLIC_CONSTRUCTORS);
        hints.reflection().registerType(org.springframework.aot.hint.TypeReference.of("org.postgresql.Driver"),
                MemberCategory.INVOKE_PUBLIC_CONSTRUCTORS);
        hints.resources().registerPattern("mapper/*Mapper.xml");
        hints.resources().registerPattern("logback-spring.xml");

        // MyBatis-Plus AbstractRepository resolves the session factory through
        // MyBatis MetaObject before saveBatch/updateBatchById. A queried-only
        // getter is not sufficient for invocation in GraalVM Native Image.
        hints.reflection().registerType(SqlSessionTemplate.class,
                hint -> hint.withMethod("getSqlSessionFactory", List.of(), ExecutableMode.INVOKE));

        Class<?>[] models = {
                BaseEntity.class, Forward.class, Node.class, SpeedLimit.class,
                StatisticsFlow.class, Tunnel.class, User.class, UserTunnel.class, ViteConfig.class,
                R.class, ChangePasswordDto.class, ConfigItem.class, FlowDto.class,
                ForwardDto.class, ForwardUpdateDto.class, ForwardWithTunnelDto.class,
                GostConfigDto.class, GostDto.class, LoginDto.class, NodeDto.class,
                NodeUpdateDto.class, ResetFlowDto.class, SpeedLimitDto.class,
                SpeedLimitUpdateDto.class, SystemInfoDto.class, TunnelDto.class,
                TunnelListDto.class, TunnelUpdateDto.class, UserDto.class,
                UserPackageDto.class, UserTunnelDto.class, UserTunnelQueryDto.class,
                UserTunnelUpdateDto.class, UserTunnelWithDetailDto.class, UserUpdateDto.class,
                FlowController.EncryptedMessage.class, WebSocketServer.EncryptedMessage.class,
                ForwardServiceImpl.DiagnosisResult.class, TunnelServiceImpl.DiagnosisResult.class,
                com.baomidou.mybatisplus.extension.plugins.pagination.Page.class
        };
        for (Class<?> model : models) {
            registerModel(hints, model);
        }
    }

    /**
     * R.data is declared as Object, so MVC AOT cannot infer the response
     * graph. Register nested DTOs too: UserPackageDto contains user info,
     * tunnel permission and forwarding result types returned via Mapper XML.
     * This runs during AOT processing, not in the native application.
     */
    private static void registerModel(RuntimeHints hints, Class<?> model) {
        hints.reflection().registerType(model,
                MemberCategory.INVOKE_DECLARED_CONSTRUCTORS,
                MemberCategory.INVOKE_PUBLIC_METHODS,
                MemberCategory.INVOKE_DECLARED_METHODS,
                MemberCategory.DECLARED_FIELDS,
                MemberCategory.PUBLIC_FIELDS);
        for (Class<?> nested : model.getDeclaredClasses()) {
            if (!nested.isSynthetic()) {
                registerModel(hints, nested);
            }
        }
    }
}
