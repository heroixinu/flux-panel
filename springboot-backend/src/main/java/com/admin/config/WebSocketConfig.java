package com.admin.config;

import com.admin.common.utils.WebSocketServer;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * Wire the concrete, fully initialized handler into the registry rather than
 * creating it through an interface-typed factory method. This also preserves
 * constructor dependencies in generated Spring AOT bean definitions.
 */
@Configuration(proxyBeanMethods = false)
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final WebSocketServer handler;
    private final WebSocketInterceptor interceptor;

    public WebSocketConfig(WebSocketServer handler, WebSocketInterceptor interceptor) {
        this.handler = handler;
        this.interceptor = interceptor;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, "/system-info")
                .setAllowedOrigins("*")
                .addInterceptors(interceptor);
    }
}
