# 官方模拟器对比结果

固定 seed、原始 120 订单、原样官方 harness。所有指标越低越好；max share 仅衡量集中程度，不等于已实现公平性优化。

默认主设置 min_delay 来自现有系统；团队课程主目标分配尚待确认。以下是开发集实验，不是独立 holdout 或真实经营收益。

| 场景 | Seed | 策略 | 平均天数 | P90天数 | 迟交% | 缺陷% | 成本 | 最大份额% |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| standard | 5105 | random | 21.52 | 45.62 | 34.17 | 4.17 | 111780.00 | 22.62 |
| standard | 5105 | greedy_biggest | 49.02 | 80.62 | 84.17 | 4.17 | 108430.00 | 70.16 |
| standard | 5105 | cheapest | 105.13 | 192.87 | 93.33 | 7.50 | 85960.00 | 70.16 |
| standard | 5105 | planner_min_delay | 8.05 | 13.69 | 1.67 | 5.00 | 115640.00 | 25.56 |
| standard | 5105 | planner_min_defects | 162.51 | 282.15 | 95.00 | 1.67 | 129920.00 | 70.16 |
| standard | 5105 | planner_hybrid | 8.79 | 16.23 | 2.50 | 3.33 | 113480.00 | 33.58 |
| standard | 5105 | planner_min_cost | 105.13 | 192.87 | 93.33 | 7.50 | 85960.00 | 70.16 |
| shock | 5105 | random | 23.36 | 48.35 | 39.17 | 4.17 | 111780.00 | 22.62 |
| shock | 5105 | greedy_biggest | 51.04 | 81.25 | 86.67 | 4.17 | 108430.00 | 70.16 |
| shock | 5105 | cheapest | 103.88 | 190.04 | 91.67 | 5.00 | 85960.00 | 70.16 |
| shock | 5105 | planner_min_delay | 8.38 | 15.38 | 1.67 | 5.00 | 115805.00 | 26.15 |
| shock | 5105 | planner_min_defects | 165.00 | 285.12 | 95.00 | 1.67 | 129920.00 | 70.16 |
| shock | 5105 | planner_hybrid | 9.30 | 18.59 | 3.33 | 3.33 | 114110.00 | 33.26 |
| shock | 5105 | planner_min_cost | 103.88 | 190.04 | 91.67 | 5.00 | 85960.00 | 70.16 |

## 基线胜出的指标

每个设置对三种基线逐项比较，差异不代表统计显著性；完整逐订单结果在同目录 JSON。

- standard / seed 5105 / planner_min_delay：random 在 defect_percent, total_cost, max_share_percent 更低。
- standard / seed 5105 / planner_min_delay：greedy_biggest 在 defect_percent, total_cost 更低。
- standard / seed 5105 / planner_min_delay：cheapest 在 total_cost 更低。
- standard / seed 5105 / planner_min_defects：random 在 mean_days, p90_days, late_percent, total_cost, max_share_percent 更低。
- standard / seed 5105 / planner_min_defects：greedy_biggest 在 mean_days, p90_days, late_percent, total_cost 更低。
- standard / seed 5105 / planner_min_defects：cheapest 在 mean_days, p90_days, late_percent, total_cost 更低。
- standard / seed 5105 / planner_hybrid：random 在 total_cost, max_share_percent 更低。
- standard / seed 5105 / planner_hybrid：greedy_biggest 在 total_cost 更低。
- standard / seed 5105 / planner_hybrid：cheapest 在 total_cost 更低。
- standard / seed 5105 / planner_min_cost：random 在 mean_days, p90_days, late_percent, defect_percent, max_share_percent 更低。
- standard / seed 5105 / planner_min_cost：greedy_biggest 在 mean_days, p90_days, late_percent, defect_percent 更低。
- shock / seed 5105 / planner_min_delay：random 在 defect_percent, total_cost, max_share_percent 更低。
- shock / seed 5105 / planner_min_delay：greedy_biggest 在 defect_percent, total_cost 更低。
- shock / seed 5105 / planner_min_delay：cheapest 在 total_cost 更低。
- shock / seed 5105 / planner_min_defects：random 在 mean_days, p90_days, late_percent, total_cost, max_share_percent 更低。
- shock / seed 5105 / planner_min_defects：greedy_biggest 在 mean_days, p90_days, late_percent, total_cost 更低。
- shock / seed 5105 / planner_min_defects：cheapest 在 mean_days, p90_days, late_percent, total_cost 更低。
- shock / seed 5105 / planner_hybrid：random 在 total_cost, max_share_percent 更低。
- shock / seed 5105 / planner_hybrid：greedy_biggest 在 total_cost 更低。
- shock / seed 5105 / planner_hybrid：cheapest 在 total_cost 更低。
- shock / seed 5105 / planner_min_cost：random 在 mean_days, p90_days, late_percent, defect_percent, max_share_percent 更低。
- shock / seed 5105 / planner_min_cost：greedy_biggest 在 mean_days, p90_days, late_percent, defect_percent 更低。

## 10 个可复核的不利案例

取主设置在固定 seed 下的前 10 个不同订单损失案例，保留完整数值，不据此调整策略。这里只是算法比较，不代替最终要求的全部系统失败分析。

- ORD-076（standard，seed 5105）对比 random：本系统 W1 / 8.00 天 / 成本 1800.00；基线 W5 / 9.00 天 / 成本 1320.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-077（standard，seed 5105）对比 random：本系统 W5 / 7.50 天 / 成本 1100.00；基线 W3 / 10.35 天 / 成本 800.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-087（standard，seed 5105）对比 random：本系统 W5 / 10.00 天 / 成本 1100.00；基线 W6 / 8.69 天 / 成本 1200.00。较差项：turnaround。应结合不同历史队列、随机返工与冲击核查；单条结果不能证明局部选择错误。
- ORD-007（standard，seed 5105）对比 random：本系统 W1 / 10.67 天 / 成本 3000.00；基线 W3 / 16.04 天 / 成本 1600.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-105（standard，seed 5105）对比 random：本系统 W8 / 4.00 天 / 成本 200.00；基线 W1 / 1.67 天 / 成本 300.00。较差项：turnaround。应结合不同历史队列、随机返工与冲击核查；单条结果不能证明局部选择错误。
- ORD-039（standard，seed 5105）对比 random：本系统 W2 / 7.44 天 / 成本 780.00；基线 W3 / 22.35 天 / 成本 480.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-001（standard，seed 5105）对比 random：本系统 W2 / 12.32 天 / 成本 1300.00；基线 W6 / 29.69 天 / 成本 1200.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-089（standard，seed 5105）对比 random：本系统 W1 / 7.00 天 / 成本 1500.00；基线 W1 / 4.33 天 / 成本 1500.00。较差项：turnaround。应结合不同历史队列、随机返工与冲击核查；单条结果不能证明局部选择错误。
- ORD-052（standard，seed 5105）对比 random：本系统 W1 / 10.00 天 / 成本 1800.00；基线 W3 / 24.57 天 / 成本 960.00。较差项：cost。速度目标未约束总成本，因此可能选择更贵工坊。
- ORD-026（standard，seed 5105）对比 random：本系统 W5 / 9.00 天 / 成本 880.00；基线 W1 / 4.00 天 / 成本 1200.00。较差项：turnaround。应结合不同历史队列、随机返工与冲击核查；单条结果不能证明局部选择错误。

## 解释边界

混合分数为 `0.6 × 天数 + 0.4 × 缺陷率百分数`，权重沿用现有实现，未据本次结果调参。min_delay 是预计周转时间目标，不等于全局最少迟交。官方只接收单工坊选择；拆单收益另行测量。冲击对象不传入 allocator，不能声称策略能预知工坊故障。官方 shock 选择会额外消耗一次随机数，因此同 seed 的 standard/shock 返工样本也会不同；场景差值不能解释为纯停工效应。

系统相对简短启发式增加的能力：自然语言校验、约束执行、多轮澄清、可追溯分配、事务与生产生命周期；这些能力需由接口和可靠性测试证明，不能由模拟器分数替代。
