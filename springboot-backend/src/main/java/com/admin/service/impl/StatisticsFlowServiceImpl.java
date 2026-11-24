package com.admin.service.impl;

import com.admin.entity.StatisticsFlow;
import com.admin.mapper.StatisticsFlowMapper;
import com.admin.service.StatisticsFlowService;
import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import org.springframework.stereotype.Service;

/**
 * <p>
 *  服务实现类
 * </p>
 *
 * @author QAQ
 * @since 2025-08-14
 */
@Service
public class StatisticsFlowServiceImpl extends ServiceImpl<StatisticsFlowMapper, StatisticsFlow> implements StatisticsFlowService {
    @Override
    @org.springframework.transaction.annotation.Transactional
    public void saveSamples(java.util.List<StatisticsFlow> samples) {
        // SQLite JDBC cannot return all generated keys for a multi-row batch.
        for (StatisticsFlow sample : samples) {
            if (!save(sample)) {
                throw new IllegalStateException("Could not persist statistics sample");
            }
        }
    }
}

