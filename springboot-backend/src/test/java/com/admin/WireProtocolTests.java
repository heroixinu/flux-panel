package com.admin;

import com.admin.common.dto.FlowDto;
import com.admin.common.dto.GostConfigDto;
import com.admin.common.utils.AESCrypto;
import com.admin.common.utils.JsonSupport;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class WireProtocolTests {
    @Test
    void jacksonPreservesGostProtocolAndIgnoresAdditionalFields() {
        FlowDto flow = JsonSupport.read("{\"n\":\"1_2_3_tcp\",\"u\":3,\"d\":5,\"extra\":true}", FlowDto.class);
        assertEquals("1_2_3_tcp", flow.getN());
        assertEquals(3L, flow.getU());
        assertEquals(5L, flow.getD());
        GostConfigDto config = JsonSupport.read("{\"services\":[{\"name\":\"svc\",\"extra\":1}],\"chains\":[],\"limiters\":[]}", GostConfigDto.class);
        assertEquals("svc", config.getServices().getFirst().getName());
        Map<String,Object> data = new LinkedHashMap<>();
        data.put("type", "AddService");
        data.put("data", List.of(Map.of("name", "service_tcp"), Map.of("name", "service_udp")));
        data.put("unused", null);
        var tree = JsonSupport.tree(JsonSupport.write(data));
        assertEquals("AddService", tree.path("type").asText());
        assertEquals("service_udp", tree.path("data").get(1).path("name").asText());
        assertFalse(tree.has("unused"));
    }

    @Test
    void aesGcmRoundTripAndTamperRejection() {
        AESCrypto crypto = new AESCrypto("test-node-secret");
        String value = "{\"memory_usage\":12.5}";
        String encrypted = crypto.encrypt(value);
        assertEquals(value, crypto.decryptString(encrypted));
        assertThrows(RuntimeException.class, () -> new AESCrypto("wrong-secret").decryptString(encrypted));
    }
}
