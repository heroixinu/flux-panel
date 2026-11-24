package com.admin.controller;

import com.admin.common.lang.R;
import org.springframework.web.bind.annotation.*;

/** Compatibility endpoint for clients released before captcha retirement. */
@RestController
@CrossOrigin
@RequestMapping("/api/v1/captcha")
public class CaptchaController {
    @PostMapping("/check")
    public R check() {
        return R.ok(0);
    }
}
