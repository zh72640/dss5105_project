# 已知限制 — Week 5/6 MVP v0.1

- **真实 LLM 未验收**：Google 官方 SDK / gemini-3.5-flash adapter 已实现，11条真实 SDK + 模拟 HTTP 测试通过；当前缺少 GEMINI_API_KEY，尚未调用真实模型。offline 的 60/60 不能当作真实 LLM 准确率。
- **Data Schema2 原件缺失**：当前 SQLite 根据两份计划列出的字段/表设计；需要和原始 ERD/DDL 核对。
- **解析覆盖有限**：离线模式以英文课程请求为主，含少量中文模式；保守证据校验也会限制真实 LLM 可接受的日期、数量和约束表达。复杂否定、金额预算、精确拆分、更多自由表达仍需扩展与 holdout 测试。
- **单条消息**：非空 context_messages 明确报错；澄清后必须提交完整新消息，尚无 sessions/messages 状态机。
- **订单精确检索**：缺 ID 不做客户猜测；消息字段与数据库冲突时澄清，不自动更改订单、日期或数量。
- **生产生命周期未实现**：completed/lapsed 状态有保护，源 completed 数据已导入；没有完工、取消、撤销、重派管理 API，也不会自动联系工坊或安排运输。
- **逾期是软提示**：原课程中的逾期订单仍可分配；显式 hard deadline 才阻止迟交方案。自动 lapsed 政策需团队确认。
- **队列和时间简化**：日历天、确定性产能，不模拟周日停工或随机返工；UI 交付日期使用 ceil，官方 harness 使用 round，二者需区分。
- **混合目标为启发式**：min_delay/min_cost/min_defects 的小规模最优性已用穷举验证；hybrid 未声称全局最优。还未将新分配器接入官方 simulator 比较性能，原 baseline/shock 仅做一致性回归。
- **初始标注待第二位人工复核**：60 条 parser golden 和原始 30 条行为标签不是独立盲测集。
- **本地服务**：绑定 127.0.0.1，无用户认证/角色/公网部署；只适合当前本机课程 MVP。
- **数据库错误日志有限**：业务事务回滚后尽量另记审计；整库不可用时 error_logged=false，需要调用方保存返回值。

- **Gemini SDK 是在线依赖**：固定 google-genai==2.23.0，已安装至项目 .venv；离线模式不需要 SDK。在线模式缺 SDK 会明确报 gemini_sdk_missing，不会静默降级。

后续操作入口：[下一阶段交接](docs/NEXT_STAGE_CN.md)。
