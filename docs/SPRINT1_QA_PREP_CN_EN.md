# SweaterCo Sprint 1 Q&A：英文短答＋中文讲解

准备日期：2026-10-16。依据当前 MVP v0.5 代码、已保存的评估结果和课程原始要求；未使用今晚正式演示 slides，因为工作区未找到。以下问题是按课程要求推测的高概率问题，不是老师的已知题目。

适用场景：5 分钟展示后的 2 分钟 Q&A。先回答 20–30 秒，老师继续追问再展开。英文中的 “we plan” 是建议的下一步，只有团队同意后才作为承诺；个人贡献必须换成真实分工。

## 先背这段项目定位

> We are building a dispatch decision-support system for SweaterCo. It turns chat requests into structured constraints, checks workshop eligibility and current queues, and recommends an allocation with traceable calculations. The dispatcher reviews and approves the recommendation before it is committed through the UI.

中文：自然语言收需求，代码算方案，人来审批，系统留记录。这里的人工审批指 UI 会话流程；不要把所有 CLI/API 入口都描述为自动具有同样的双步骤审批。

## A. 最优先准备的 12 题

### 1. What problem are you solving, and what is the business value?

> Dispatchers currently make allocation decisions from group-chat messages while checking capability, backlog, price and delivery dates manually. Our system brings those checks into one workflow and records the reasons behind each decision. We have simulation evidence for delivery performance, but we have not yet measured real dispatcher time savings or financial returns.

中文：业务价值是减少反复查资料、漏约束和决策无记录。模拟器的周转天数改善不是人工操作时间改善，更不是已经实现的利润。

### 2. Why do you need an LLM? Could rules or a form do the same job?

> Rules and forms are useful for structured requests, and we support both. The LLM's intended role is to interpret varied chat messages and help resolve missing information. Eligibility checks, arithmetic and database updates remain deterministic. We still need held-out testing to show whether the LLM improves language coverage over our rule parser.

中文：承认表单能做结构化任务。LLM 的价值假设是理解真实群聊表达，不能拿离线规则的 60/60 证明它已优于规则。当前证据校验依赖部分规则识别，因此也会限制 LLM 能接受的自由表达。

追问 “Is this an autonomous agent?”：

> It is a bounded workflow with an LLM-assisted language interface. We use explicit application states and deterministic planning, with human approval for UI allocations. We do not claim open-ended autonomous planning.

### 3. How does your allocation algorithm work?

> We first remove workshops that violate capability, status, batch-size or user constraints. For each feasible single-workshop option, we estimate completion time as queue time plus processing time plus transport time. We then rank options using the configured objective. For split orders, we preserve integer quantities and evaluate when the last part finishes.

中文：先筛资格，再比指标。单工坊公式：`T = queue_days + pieces / capacity_per_day + pickup_lead_days`；成本：`C = pieces × cost_per_piece`。多工坊的完成时间取最慢一部分，不是各部分求和。

追问 “Why not always choose the fastest workshop?”：

> Capacity alone ignores backlog and transport. A high-capacity workshop can still finish later when its queue is long.

### 4. What evidence shows that your policy is better than the baselines?

> In the standard simulator run over 120 orders, our turnaround policy achieved 8.05 days on average, compared with 21.52 for random, 49.02 for highest capacity, and 105.13 for cheapest. However, it cost more than all three baselines. These are results from one fixed seed on the provided data, so we do not claim statistical significance or real-world savings.

中文：说明在什么实验、什么指标上赢，再主动交代代价。相对 random，平均时间减少约 62.6%，成本增加约 3.5%；迟交率从 34.17% 到 1.67%，降低的是 **32.50 个百分点**。这组成绩来自确定性 planner，不是 LLM 实验。

| standard，seed 5105，120 订单 | 平均天数 | 迟交率 | 缺陷批次率 | 总成本（数据单位） |
|---|---:|---:|---:|---:|
| Random | 21.52 | 34.17% | 4.17% | 111,780 |
| Highest capacity | 49.02 | 84.17% | 4.17% | 108,430 |
| Cheapest | 105.13 | 93.33% | 7.50% | 85,960 |
| Planner: min_delay | 8.05 | 1.67% | 5.00% | 115,640 |
| Planner: hybrid | 8.79 | 2.50% | 3.33% | 113,480 |

### 5. Are you actually minimizing lateness, or just completion time?

> Our current min_delay setting minimizes estimated turnaround for the incoming order. That is a useful proxy, but it is not the same as minimizing the total number of late orders. We report lateness separately. If lateness is our assigned primary objective, our next step is to align the policy directly with that objective and compare it with the current proxy.

中文：这是最重要的技术边界之一。课程候选主目标包括迟交、缺陷、公平、故障稳健性；仓库尚未确认团队被分配的主目标。上台前和队友统一主目标。不要说算法已求得“全局迟交最优”。`min_cost` 是额外设置，不能自动代替课程主目标。

### 6. How do you prevent hallucinations and incorrect allocations?

> We validate the model's structured output against a strict schema and evidence in the input, then check it against registered order data. Missing or conflicting information blocks allocation and triggers clarification. Costs, dates and eligibility come from code, and the UI requires approval. These controls reduce risk, but we have not proved that every possible language error is eliminated.

中文：四道控制是结构校验、原文证据、数据库核对、人工审批。验证失败最多再尝试一次，持续失败停止处理。不要把有限回归集里的零补造称为“永不 hallucinate”。

### 7. You report 100% accuracy. Is that credible?

> We do not claim 100% general accuracy. The offline parser matched all 60 development regression cases, and the system matched the expected behavior labels on the 30 provided requests. Those are limited checks. They are not held-out LLM results, and correct behavior labels do not establish that every explanation is faithful.

中文：区分四类证据：软件回归、语言字段、业务行为、解释忠实性。203 条 Python 测试和 7 条前端控制器测试通过是已保存的工程记录，不能当业务准确率。30 条行为评估每条使用新库，也不证明连续生产状态全部正确。

### 8. Does the live LLM integration actually work?

> The integrations are implemented, but full live acceptance is incomplete. In the saved Gemini evaluation, 14 of 60 cases matched, while 46 failed because of rate limits. DeepSeek has mocked integration tests but no recorded full live acceptance. For the presentation, we should identify the backend clearly and distinguish an offline workflow demo from live LLM validation.

中文：14 个收到结果的样本均匹配，不等于 60/60，更不能剔除 46 个服务失败后宣称在线 100%。如果今晚使用 offline，就直说。LLM 调用失败不会静默冒充成功；离线后端或表单可供明确选择，不能称为已实现所有失败的自动降级。

### 9. Why is your hybrid weighted 0.6 and 0.4?

> These are initial heuristic weights, not weights learned from users or calibrated to business costs. The score combines estimated days and defect percentage points, so its behavior also depends on their scales. We should test sensitivity and use stakeholder priorities or explicit constraints before treating it as a business-optimal policy.

中文：真实公式是 `0.6 × days + 0.4 × defect_rate × 100`，**没有成本项，也没有完成尺度归一化**。不能把 0.6 解释为已经证明的“业务价值中速度占 60%”。拆单 hybrid 也未声称全局最优。

### 10. What does your system add over a ten-line heuristic?

> A short heuristic can produce the same workshop choice in some settings. Our contribution is the surrounding decision workflow: interpreting requests, preserving constraints, asking for clarification, showing traceable alternatives, and recording approved changes without duplicate allocation. We evaluate the scheduling policy separately from these interaction and reliability features.

中文：承认简单方法可能同样好。`min_cost` 本次与 cheapest 结果相同。增加界面、审计和生命周期是系统贡献，不应伪装成算法创新，也不能用模拟器指标代替这些功能的验证。

### 11. What are your most important assumptions and risks?

> We assume the workshop profiles and queues are accurate, and the planner uses fixed capacities and calendar-day estimates. It does not model every real production delay or guarantee delivery dates. The main remaining risks are live model availability, unseen language inputs, and stale operational data. We need targeted evaluation for each of those risks.

中文：课程背景说工厂周日休息，但当前官方模拟器与 planner 按日历天；生产 ETA 未把随机返工加入公式。工坊数据当前不是外部实时同步。用“估计＋假设”，不要承诺准时到货。

### 12. What will you deliver in Sprint 2, and how will you measure success?

> We propose three priorities: reliable live parsing, independent evaluation, and operational data updates. Success means reporting service failures alongside language accuracy, testing unseen requests, and scoring decisions and explanations separately. We also need multiple-seed simulator comparisons and an auditable way to update workshop status and capacity.

中文：这是建议路线，正式回答应带真实负责人和团队认可的标准。若需要具体指标，可讨论：首轮结构有效率≥98%、核心字段匹配≥90%、测试中观测补造为0；这些来自已有路线草案，**不是已达成结果或课程强制阈值**。另建未参与开发的语言集；完成原始30条的解释评分及至少10个系统失败案例分析。

## B. 技术追问：知道怎么答即可

### 13. What happens if information is missing or the requested workshop is ineligible?

> If the order is ambiguous, we ask for its ID instead of guessing. If the user explicitly requests an ineligible workshop, we refuse that choice and explain the rule. If the data cannot answer a question, we say so. If no feasible allocation meets the constraints, we escalate instead of silently relaxing them.

中文例子：R03 的 TrendCart 有多个订单，应澄清；R08 给 FreshStart 400件，超过300件上限；R11 指定 OldMill，但它是暂停状态；R13 问客户报价，工坊加工单价不能替代客户报价。

边界：课程还要求拒绝时给替代建议；当前不能仅凭 REFUSE 标签匹配就宣称每个拒绝案例的替代方案和解释都完整合格。

### 14. Why can the system allocate an order that is already overdue?

> We distinguish a soft due date from a hard deadline. With a soft due date, the system can recommend the best available option while displaying a lateness warning. If on-time delivery is explicitly required and no plan can meet it, the system reports infeasibility. It does not invent a feasible date.

中文：默认逾期是风险提示，不自动终止订单。真实业务中逾期后继续做还是作废，需要业务方确认。

### 15. How do you avoid duplicate or conflicting allocations?

> Requests use idempotency keys, and orders and sessions have version checks. Confirmation runs in a transaction and uses the latest data, so a retry does not create another allocation. If the order has changed, stale confirmation is rejected. A failed transaction rolls back the related production changes.

中文：幂等解决重复点/网络重试；版本解决旧页面提交；事务解决写了一半失败。锁内重算会使用新队列。

追问 “Can the accepted plan differ from the preview?”：

> Yes. Another order can change the queues between preview and confirmation. We recalculate before committing, so the final plan can differ. Requiring another approval when the plan changes materially would be a useful improvement to approval semantics.

中文：当前实现不能说“每次预览变化都已要求重新批准”。目标订单版本变化会拒绝；其他订单导致队列变化时会重算并可能提交不同方案。

### 16. Is your allocation globally optimal?

> We evaluate the current order against the current queues. We have checked small instances of the single-objective split planner against exhaustive enumeration. That does not prove a globally optimal schedule across future orders, and we do not claim global optimality for the hybrid split strategy.

中文：单次决策好，不等于所有订单联合调度最优；未来订单未知。不要把小规模穷举测试说成形式化证明。

### 17. How do you split orders, and can it scale?

> We enumerate allowed workshop subsets and allocate integer quantities within their limits. For turnaround, we search for the earliest completion time with enough capacity. This is manageable with eight workshops, but subset enumeration grows exponentially. A larger deployment would need pruning or an optimization solver, plus load testing.

中文：单工坊候选遍历近似线性；全拆单最多8家时非空子集理论上255个，实际受资格与最大工坊数限制。不能说当前方法能直接扩展到几千家工坊。“最多2家”不等于必须拆2家。

### 18. How does your system handle workshop failures?

> We tested the unchanged official simulator's shock scenario. Our policy uses the queues it receives, but it is not told the outage target and does not explicitly detect or predict a failure. Those results are an initial stress test, not proof of a complete outage-response system. Operational failure detection and status updates remain future work.

中文：standard 与 shock 即使同 seed，返工随机样本也不同，因此差值不能全归因于停工。当前业务系统支持人工重派剩余件数，不等于已实现自动故障发现与自动恢复。

### 19. Are your improvements caused by the LLM?

> No. The simulator calls the deterministic planner directly with structured batch data. It measures allocation policy performance. To establish the LLM's contribution, we need a separate comparison against the rule parser on unseen language inputs, including accuracy, failure rate and latency.

中文：这是回答因果归因的关键。模拟器单工坊接口也没有验证多轮交互或拆单带来的收益。

### 20. How do you know the explanations are faithful?

> The displayed summaries are generated from the actual plan fields, so costs, quantities and workshop choices have a direct data source. That reduces opportunities for invented explanations. However, we still need an independent explanation assessment; matching the expected decision label alone does not establish faithfulness.

中文：当前摘要是基于计划字段生成，不是额外调用 LLM 自由写理由。应逐项核对解释数字、拒绝理由、遗漏的重要条件与方案是否一致。

### 21. Is this RAG? Why not use a vector database?

> We retrieve structured records by order ID and workshop attributes. With small tables and exact operational constraints, direct database queries are appropriate. We do not need semantic document search for the current scope, and we do not use retrieval similarity to guess which order the user intended.

中文：可以说 grounded retrieval，但不必包装成向量 RAG。结构化订单精确查询更符合任务。

### 22. Is this ready for real deployment?

> It is a local course MVP with login, persistent records and audited production changes. It has not been validated as a multi-tenant production service. Before deployment, we need reliable data integration, role-based permissions, concurrency and recovery testing, and evidence from real dispatcher use.

中文：服务绑定 localhost，账号共享工作区，有账号登录但没有完整角色/租户隔离。已有事务和幂等，不代表通过企业级负载测试。

### 23. Why are there 120 orders in the experiment but only 34 open orders in the UI?

> The simulator replays all 120 orders as a historical experiment. The operational UI imports 86 completed orders as completed and exposes the remaining 34 as initial pending work. The two views answer different questions: policy performance over the full replay versus what needs action in the current workspace.

中文：这是实验回放和运行状态的区别，不是数据丢失。业务日期默认2026-04-01；审计时间为真实UTC时间，两者也别混用。

### 24. What exactly does the defect metric mean?

> In the official simulator, it is the fraction of batches that trigger a defect event. A defective batch requires half of its production work to be redone. It is not the percentage of individual garments found defective, and it is not a real-world quality measurement.

中文：不要把表里的5%解释为“5%的衣服坏了”。planner 对拆单使用按件数加权的工坊缺陷率评分，和官方单工坊实验中的观测缺陷批次率也不是同一个统计量。

### 25. Have you optimized fairness across workshops?

> We report allocation concentration, but we have not implemented fairness as an explicit objective. A lower maximum share can indicate less concentration, but it is not sufficient to establish fairness because workshops differ in capability and capacity.

中文：max share 是某工坊承接件数占总件数的最大比例，不是订单比例，也不是公平性优化已实现的证据。如果团队主目标被分到公平性，这是要优先补的差距。

### 26. What is your strongest failure example?

> For ORD-076 in the standard run, our turnaround policy cost 1,800 units versus 1,320 for random, while completing in 8 rather than 9 days. It shows the policy can pay substantially more for a small speed improvement. That motivates explicit business constraints rather than assuming the fastest option is always best.

中文：这是可核对的算法代价案例，不是程序出错。还可回答服务失败：Gemini 46/60 受429影响。不要只说“偶尔网络有点慢”。

### 27. Why not add more agents or a framework?

> The workflow is small and well defined, so explicit application states and typed functions make behavior easier to inspect and test. More agents would need to solve a specific coordination problem to justify the added complexity. Our priority is a correct, auditable decision.

中文：课程明确允许单一dispatcher或多agent，不按机制复杂度评分。不要声称自己用了并不存在的多agent竞价/协商。

### 28. Have you shown that the interface is easier for users?

> We have checked key interaction flows and made recommendations, warnings and approval states visible. We have not yet run a controlled usability study with dispatchers. A useful next test would compare completion time, correction rate and user confidence against the current manual workflow on the same tasks.

中文：浏览器验收证明交互能跑通，不等于真实用户认可，也不等于已证明节省时间。

### 29. What did you personally contribute?

> My main responsibility was [your actual component]. I implemented [specific change], and verified it using [specific test or result]. I also worked with [teammate or role] on [actual interface or integration]. The main remaining limitation in my part is [specific limitation].

中文：只填自己真实完成的工作。组内提前统一谁回答模型/算法/评估/界面问题，所有成员都准备一句贡献说明；不要临场替他人认领工作。

## C. 五个不要说错的句子

| 不准确的说法 | 建议改成 |
|---|---|
| Our LLM achieves 100% accuracy. | Our offline parser passed all 60 development regression cases; full live LLM validation is incomplete. |
| We minimize lateness globally. | Our current policy minimizes estimated turnaround and reports lateness separately. |
| We outperform every baseline. | We outperform the three baselines on turnaround in this fixed-seed run, with higher cost. |
| Our system automatically detects workshop failures. | We tested a shock scenario; explicit outage detection is not yet implemented. |
| We have proven real business savings. | We have simulation results and a working workflow; field savings remain unmeasured. |

还要注意：历史 Sprint 1 讲稿按 v0.3 写，有“168条测试”“没有账号权限”等旧信息。当前 v0.5 保存的结果是203条Python测试、7条控制器测试，并已有本地登录。正式slides应以实际展示版本为准。

## D. 现场答题方法

1. **先给结论**：Yes / Not yet / In the current version…
2. **给一个机制或数字**：不要把所有测试、所有模块一次念完。
3. **补一个边界或下一步**：避免泛泛地说 “we will improve it”。

可直接使用：

> We have not validated that yet. What we can show today is [evidence]. To answer it properly, we would need [specific test].

> The current implementation supports [implemented behavior]. [Requested capability] is planned, but not implemented yet.

如果只剩10分钟：先练第2、4、5、7、8、10、12题；记住8.05天、1.67%迟交、成本更高，以及“60条离线回归不等于LLM准确率”。

## E. 核对来源

- 课程Sprint安排、评估诚信与评分：../../Capstone_Project_Spec.pdf，第2–3、5–7页。
- Track2功能、主目标和模拟器要求：../../Capstone_Project_Tracks.pdf，第4–7页。
- 当前功能与边界：[项目说明](PROJECT_OVERVIEW_CN.md)、[已知限制](../KNOWN_ISSUES.md)、[UI指南](UI_GUIDE_CN.md)。
- 算法：[planner.py](../app/allocator/planner.py)、[模拟器适配](../evaluation/simulator_adapter.py)、[官方harness](../harness/simulate.py)。
- 模型验证：[validator.py](../app/agent/validator.py)、[离线指标](../evaluation/results/parser_offline_metrics.json)、[在线指标](../evaluation/results/parser_llm_metrics.json)。
- 实验结果：[对比报告](../evaluation/results/simulator_comparison_CN.md)、[行为指标](../evaluation/results/dispatch_behavior_metrics.json)、[保存的工程验证](../evaluation/results/verification_summary.json)。

本次只读检查确认：对比报告记录的数据、planner、适配器与harness的哈希均匹配当前文件；项目harness与课程原件一致。没有重新运行全套测试或真实模型调用。
