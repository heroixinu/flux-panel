package com.admin.config;

import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.BlockAttackInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
// Explicit bean reference survives Spring's generated AOT bean definitions.
@MapperScan(basePackages = "com.admin.mapper", sqlSessionTemplateRef = "sqlSessionTemplate")
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(com.baomidou.mybatisplus.annotation.DbType.POSTGRE_SQL)); // 分页插件
        interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor()); // 防止全表更新插件
        return interceptor;
    }

}
