package com.example.hanresstest.component;

import org.springframework.ai.mcp.annotation.McpPrompt;
import org.springframework.stereotype.Component;

@Component
public class FinancePrompts {

    @McpPrompt(
            name = "monthly_financial_analysis",
            description = "生成月度财务分析提示"
    )
    public String monthlyAnalysis(
            String company,
            String month
    ) {

        return """
                请分析%s在%s的财务经营情况。

                重点分析：
                1. 收入
                2. 成本
                3. 毛利率
                4. 应收账款
                5. 现金流
                6. 与上月对比
                """.formatted(company, month);
    }
}
