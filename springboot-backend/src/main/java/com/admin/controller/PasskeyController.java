package com.admin.controller;

import com.admin.common.lang.R;
import com.admin.service.PasskeyService;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.bind.annotation.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@RestController
@RequestMapping("/api/v1/passkey")
public class PasskeyController {
    private static final Logger log = LoggerFactory.getLogger(PasskeyController.class);
    private final PasskeyService passkeys;
    public PasskeyController(PasskeyService passkeys) { this.passkeys = passkeys; }

    @FunctionalInterface
    private interface Operation { R run() throws Exception; }
    private R invoke(Operation op) {
        try { return op.run(); }
        catch (PasskeyService.Denied e) { return R.err(e.getMessage()); }
        catch (Exception e) {
            // Never log challenge responses, tokens, passwords, or raw client data.
            log.warn("Passkey operation rejected: {}", e.getClass().getSimpleName());
            return R.err("Passkey 操作失败，请重新验证");
        }
    }

    @PostMapping("/modes")
    public R modes() { return invoke(passkeys::modes); }

    @PostMapping("/login/options")
    public R loginOptions() { return invoke(() -> passkeys.assertionOptions(null, false)); }
    @PostMapping("/login/finish")
    public R loginFinish(@RequestBody JsonNode body) { return invoke(() -> passkeys.assertionFinish(null, false, body)); }

    @PostMapping("/list")
    public R list(@RequestHeader("Authorization") String token) { return invoke(() -> passkeys.list(token)); }

    @PostMapping("/register/options")
    public R registerOptions(@RequestHeader("Authorization") String token, @RequestBody JsonNode body) {
        return invoke(() -> passkeys.registerOptions(token, body));
    }
    @PostMapping("/register/finish")
    public R registerFinish(@RequestHeader("Authorization") String token, @RequestBody JsonNode body) {
        return invoke(() -> passkeys.registerFinish(token, body));
    }
    @PostMapping("/reauth/options")
    public R reauthOptions(@RequestHeader("Authorization") String token) {
        return invoke(() -> passkeys.assertionOptions(token, true));
    }
    @PostMapping("/reauth/finish")
    public R reauthFinish(@RequestHeader("Authorization") String token, @RequestBody JsonNode body) {
        return invoke(() -> passkeys.assertionFinish(token, true, body));
    }
    @PostMapping("/delete")
    public R delete(@RequestHeader("Authorization") String token, @RequestBody JsonNode body) {
        return invoke(() -> passkeys.delete(token, body));
    }
    @PostMapping("/policy")
    public R policy(@RequestHeader("Authorization") String token, @RequestBody JsonNode body) {
        return invoke(() -> passkeys.policy(token, body));
    }
}
