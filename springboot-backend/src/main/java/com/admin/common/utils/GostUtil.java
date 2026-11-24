package com.admin.common.utils;

import com.admin.common.dto.GostConfigDto;
import com.admin.common.dto.GostDto;
import com.admin.entity.Tunnel;
import org.apache.commons.lang3.StringUtils;

import java.util.Objects;
import java.util.Map;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.ArrayList;

public class GostUtil {


    public static GostDto AddLimiters(Long node_id, Long name, String speed) {
        Map<String, Object> data = createLimiterData(name, speed);
        return WebSocketServer.send_msg(node_id, data, "AddLimiters");
    }

    public static GostDto UpdateLimiters(Long node_id, Long name, String speed) {
        Map<String, Object> data = createLimiterData(name, speed);
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("limiter", name + "");
        req.put("data", data);
        return WebSocketServer.send_msg(node_id, req, "UpdateLimiters");
    }

    public static GostDto DeleteLimiters(Long node_id, Long name) {
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("limiter", name + "");
        return WebSocketServer.send_msg(node_id, req, "DeleteLimiters");
    }

    public static GostDto AddService(Long node_id, String name, Integer in_port, Integer limiter, String remoteAddr, Integer fow_type, Tunnel tunnel, String strategy, String interfaceName) {
        List<Object> services = new ArrayList<>();
        String[] protocols = {"tcp", "udp"};
        for (String protocol : protocols) {
            Map<String, Object> service = createServiceConfig(name, in_port, limiter, remoteAddr, protocol, fow_type, tunnel, strategy, interfaceName);
            services.add(service);
        }
        return WebSocketServer.send_msg(node_id, services, "AddService");
    }

    public static GostDto UpdateService(Long node_id, String name, Integer in_port, Integer limiter, String remoteAddr, Integer fow_type, Tunnel tunnel, String strategy, String interfaceName) {
        List<Object> services = new ArrayList<>();
        String[] protocols = {"tcp", "udp"};
        for (String protocol : protocols) {
            Map<String, Object> service = createServiceConfig(name, in_port, limiter, remoteAddr, protocol, fow_type, tunnel, strategy, interfaceName);
            services.add(service);
        }
        return WebSocketServer.send_msg(node_id, services, "UpdateService");
    }

    public static GostDto DeleteService(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Object> services = new ArrayList<>();
        services.add(name + "_tcp");
        services.add(name + "_udp");
        data.put("services", services);
        return WebSocketServer.send_msg(node_id, data, "DeleteService");
    }

    public static GostDto AddRemoteService(Long node_id, String name, Integer out_port, String remoteAddr,  String protocol, String strategy, String interfaceName) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", name + "_tls");
        data.put("addr", ":" + out_port);

        if (StringUtils.isNotBlank(interfaceName)) {
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("interface", interfaceName);
            data.put("metadata", metadata);
        }


        Map<String, Object> handler = new LinkedHashMap<>();
        handler.put("type", "relay");
        data.put("handler", handler);
        Map<String, Object> listener = new LinkedHashMap<>();
        listener.put("type", protocol);
        data.put("listener", listener);
        Map<String, Object> forwarder = new LinkedHashMap<>();
        List<Object> nodes = new ArrayList<>();

        String[] split = remoteAddr.split(",");
        int num = 1;
        for (String addr : split) {
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("name", "node_" + num );
            node.put("addr", addr);
            nodes.add(node);
            num ++;
        }
        if (strategy == null || strategy.equals("")){
            strategy = "fifo";
        }
        forwarder.put("nodes", nodes);
        Map<String, Object> selector = new LinkedHashMap<>();
        selector.put("strategy", strategy);
        selector.put("maxFails", 1);
        selector.put("failTimeout", "600s");
        forwarder.put("selector", selector);

        data.put("forwarder", forwarder);
        List<Object> services = new ArrayList<>();
        services.add(data);
        return WebSocketServer.send_msg(node_id, services, "AddService");
    }

    public static GostDto UpdateRemoteService(Long node_id, String name, Integer out_port, String remoteAddr,String protocol, String strategy, String interfaceName) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", name + "_tls");
        data.put("addr", ":" + out_port);

        if (StringUtils.isNotBlank(interfaceName)) {
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("interface", interfaceName);
            data.put("metadata", metadata);
        }


        Map<String, Object> handler = new LinkedHashMap<>();
        handler.put("type", "relay");
        data.put("handler", handler);
        Map<String, Object> listener = new LinkedHashMap<>();
        listener.put("type", protocol);
        data.put("listener", listener);
        Map<String, Object> forwarder = new LinkedHashMap<>();
        List<Object> nodes = new ArrayList<>();

        String[] split = remoteAddr.split(",");
        int num = 1;
        for (String addr : split) {
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("name", "node_" + num );
            node.put("addr", addr);
            nodes.add(node);
            num ++;
        }
        if (strategy == null || strategy.equals("")){
            strategy = "fifo";
        }
        forwarder.put("nodes", nodes);
        Map<String, Object> selector = new LinkedHashMap<>();
        selector.put("strategy", strategy);
        selector.put("maxFails", 1);
        selector.put("failTimeout", "600s");
        forwarder.put("selector", selector);

        data.put("forwarder", forwarder);
        List<Object> services = new ArrayList<>();
        services.add(data);
        return WebSocketServer.send_msg(node_id, services, "UpdateService");
    }

    public static GostDto DeleteRemoteService(Long node_id, String name) {
        List<Object> data = new ArrayList<>();
        data.add(name + "_tls");
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("services", data);
        return WebSocketServer.send_msg(node_id, req, "DeleteService");
    }

    public static GostDto PauseService(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Object> services = new ArrayList<>();
        services.add(name + "_tcp");
        services.add(name + "_udp");
        data.put("services", services);
        return WebSocketServer.send_msg(node_id, data, "PauseService");
    }

    public static GostDto ResumeService(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Object> services = new ArrayList<>();
        services.add(name + "_tcp");
        services.add(name + "_udp");
        data.put("services", services);
        return WebSocketServer.send_msg(node_id, data, "ResumeService");
    }

    public static GostDto PauseRemoteService(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Object> services = new ArrayList<>();
        services.add(name + "_tls");
        data.put("services", services);
        return WebSocketServer.send_msg(node_id, data, "PauseService");
    }

    public static GostDto ResumeRemoteService(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Object> services = new ArrayList<>();
        services.add(name + "_tls");
        data.put("services", services);
        return WebSocketServer.send_msg(node_id, data, "ResumeService");
    }

    public static GostDto AddChains(Long node_id, String name, String remoteAddr, String protocol, String interfaceName) {
        Map<String, Object> dialer = new LinkedHashMap<>();
        dialer.put("type", protocol);
        if (Objects.equals(protocol, "quic")){
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("keepAlive", true);
            metadata.put("ttl", "10s");
            dialer.put("metadata", metadata);
        }




        Map<String, Object> connector = new LinkedHashMap<>();
        connector.put("type", "relay");

        Map<String, Object> node = new LinkedHashMap<>();
        node.put("name", "node-" + name);
        node.put("addr", remoteAddr);
        node.put("connector", connector);
        node.put("dialer", dialer);

        if (StringUtils.isNotBlank(interfaceName)) {
            node.put("interface", interfaceName);
        }


        List<Object> nodes = new ArrayList<>();
        nodes.add(node);

        Map<String, Object> hop = new LinkedHashMap<>();
        hop.put("name", "hop-" + name);
        hop.put("nodes", nodes);

        List<Object> hops = new ArrayList<>();
        hops.add(hop);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", name + "_chains");
        data.put("hops", hops);

        return WebSocketServer.send_msg(node_id, data, "AddChains");
    }

    public static GostDto UpdateChains(Long node_id, String name, String remoteAddr, String protocol, String interfaceName) {
        Map<String, Object> dialer = new LinkedHashMap<>();
        dialer.put("type", protocol);

        if (Objects.equals(protocol, "quic")){
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("keepAlive", true);
            metadata.put("ttl", "10s");
            dialer.put("metadata", metadata);
        }


        Map<String, Object> connector = new LinkedHashMap<>();
        connector.put("type", "relay");

        Map<String, Object> node = new LinkedHashMap<>();
        node.put("name", "node-" + name);
        node.put("addr", remoteAddr);
        node.put("connector", connector);
        node.put("dialer", dialer);

        if (StringUtils.isNotBlank(interfaceName)) {
            node.put("interface", interfaceName);
        }

        List<Object> nodes = new ArrayList<>();
        nodes.add(node);

        Map<String, Object> hop = new LinkedHashMap<>();
        hop.put("name", "hop-" + name);
        hop.put("nodes", nodes);

        List<Object> hops = new ArrayList<>();
        hops.add(hop);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", name + "_chains");
        data.put("hops", hops);
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("chain", name + "_chains");
        req.put("data", data);
       return WebSocketServer.send_msg(node_id, req, "UpdateChains");
    }

    public static GostDto DeleteChains(Long node_id, String name) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("chain", name + "_chains");
        return WebSocketServer.send_msg(node_id, data, "DeleteChains");
    }

    private static Map<String, Object> createLimiterData(Long name, String speed) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", name.toString());
        List<Object> limits = new ArrayList<>();
        limits.add("$ " + speed + "MB " + speed + "MB");
        data.put("limits", limits);
        return data;
    }

    private static Map<String, Object> createServiceConfig(String name, Integer in_port, Integer limiter, String remoteAddr, String protocol, Integer fow_type, Tunnel tunnel, String strategy, String interfaceName) {
        Map<String, Object> service = new LinkedHashMap<>();
        service.put("name", name + "_" + protocol);
        if (Objects.equals(protocol, "tcp")){
            service.put("addr", tunnel.getTcpListenAddr() + ":" + in_port);
        }else {
            service.put("addr", tunnel.getUdpListenAddr() + ":" + in_port);
        }

        if (StringUtils.isNotBlank(interfaceName)) {
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("interface", interfaceName);
            service.put("metadata", metadata);
        }


        // 添加限流器配置
        if (limiter != null) {
            service.put("limiter", limiter.toString());
        }

        // 配置处理器
        Map<String, Object> handler = createHandler(protocol, name, fow_type);
        service.put("handler", handler);

        // 配置监听器
        Map<String, Object> listener = createListener(protocol);
        service.put("listener", listener);

        // 端口转发需要配置转发器
        if (isPortForwarding(fow_type)) {
            Map<String, Object> forwarder = createForwarder(remoteAddr, strategy);
            service.put("forwarder", forwarder);
        }
        return service;
    }

    private static Map<String, Object> createHandler(String protocol, String name, Integer fow_type) {
        Map<String, Object> handler = new LinkedHashMap<>();
        handler.put("type", protocol);

        // 隧道转发需要添加链配置
        if (isTunnelForwarding(fow_type)) {
            handler.put("chain", name + "_chains");
        }

        return handler;
    }

    private static Map<String, Object> createListener(String protocol) {
        Map<String, Object> listener = new LinkedHashMap<>();
        listener.put("type", protocol);
        if (Objects.equals(protocol, "udp")){
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("keepAlive", true);
            listener.put("metadata", metadata);
        }
        return listener;
    }

    private static Map<String, Object> createForwarder(String remoteAddr, String strategy) {
        Map<String, Object> forwarder = new LinkedHashMap<>();
        List<Object> nodes = new ArrayList<>();

        String[] split = remoteAddr.split(",");
        int num = 1;
        for (String addr : split) {
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("name", "node_" + num );
            node.put("addr", addr);
            nodes.add(node);
            num ++;
        }

        if (strategy == null || strategy.equals("")){
            strategy = "fifo";
        }

        forwarder.put("nodes", nodes);

        Map<String, Object> selector = new LinkedHashMap<>();
        selector.put("strategy", strategy);
        selector.put("maxFails", 1);
        selector.put("failTimeout", "600s");
        forwarder.put("selector", selector);
        return forwarder;
    }

    private static boolean isPortForwarding(Integer fow_type) {
        return fow_type != null && fow_type == 1;
    }

    private static boolean isTunnelForwarding(Integer fow_type) {
        return fow_type != null && fow_type != 1;
    }

}
