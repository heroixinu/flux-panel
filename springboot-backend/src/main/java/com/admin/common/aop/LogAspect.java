package com.admin.common.aop;

import com.admin.common.utils.HttpContextUtils;
import com.admin.common.utils.IpUtils;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.AfterReturning;
import org.aspectj.lang.annotation.AfterThrowing;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/** Log operation metadata only: never serialize passwords, JWTs or node secrets. */
@Component
@Aspect
@Slf4j
public class LogAspect {
    @AfterReturning("@annotation(com.admin.common.aop.LogAnnotation)")
    public void log(JoinPoint joinPoint) {
        record(joinPoint, "success");
    }

    @AfterThrowing(value = "@annotation(com.admin.common.aop.LogAnnotation)", throwing = "ex")
    public void recordLog(JoinPoint joinPoint, Throwable ex) {
        record(joinPoint, ex.getClass().getSimpleName());
    }

    private void record(JoinPoint joinPoint, String outcome) {
        try {
            HttpServletRequest request = HttpContextUtils.getHttpServletRequest();
            if (request != null) {
                log.info("request method={} ip={} operation={} outcome={}",
                        request.getMethod(), IpUtils.getIpAddr(request),
                        joinPoint.getSignature().toShortString(), outcome);
            }
        } catch (Exception e) {
            log.debug("Request metadata unavailable", e);
        }
    }
}
