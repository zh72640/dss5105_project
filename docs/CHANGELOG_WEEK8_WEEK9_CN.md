# MVP v0.3 修改说明与提交记录

日期：2026-10-03；起点 `df50f64`；目标分支 `ningtao`。本轮按功能/修改目标分批创建英文 commit 并及时推送，未修改其他远程分支。

## 1. 已完成的功能提交

| 提交 | 英文说明 | 范围 |
|---|---|---|
| 60e032f | Add persistent clarification sessions with atomic allocation confirmation | migration003、会话契约与核心、迁移和状态测试、中文会话说明 |
| bdb179e | Expose resumable session drafts in the UI API and CLI | 页面、HTTP、CLI、恢复上次结果、连续演示、接口测试 |
| d6062b5 | Compare production allocation objectives against official simulator baselines | 官方适配、四目标/三基线实验、测试、逐订单JSON及中文结果 |
| c471780 | Verify session reliability and record MVP v0.3 acceptance evidence | 发布版本、完整验收脚本、追加并发/解析失败测试、168条验收产物 |
| 5a1267b | Document MVP v0.3 deployment architecture and session contracts | 中文部署、整体架构、操作与数据库说明、Parser/会话边界 |

Week8/9材料和最终发布冻结分别归入后续文档提交；具体哈希以本文件及相关文件的 Git 历史为准，不对自身提交号递归改写。

## 2. 文件变更目的

| 文件 / 范围 | 改动 |
|---|---|
| app/db/database.py、003_sessions.sql | 数据库升v3，旧v1/v2依次迁移，新增sessions/messages，不改001/002 |
| app/sessions.py | 有限语法合并、草稿预览、版本保护、确认/关闭、共享幂等及事务 |
| app/server.py、app/ui/index.html、sessions.js | 会话创建/读取/回合接口，中文操作入口，刷新恢复和原key重试 |
| app/session_cli.py、demos/session_demo.py | 命令行会话操作与独立临时持久库演示 |
| app/__init__.py | 应用发布版本v0.3，与原Pipeline v0.2分开 |
| tests/test_sessions.py、test_session_cli.py、test_server.py | 13条核心、1条CLI、2条HTTP新增测试；旧生命周期迁移断言更新到v3 |
| evaluation/simulator_adapter.py、compare_simulator.py | 复用生产planner单工坊模式，保留完整结果、基线胜出和不利案例 |
| tests/test_simulator_adapter.py | 2条确定性、输入不变、指标及队列影响测试 |
| evaluation/verify_mvp.py、results | 纳入会话demo和14组实验；跳过测试也不能作为完整验收成功 |
| docs/DEPLOYMENT_CN.md、PROJECT_OVERVIEW_CN.md | 当前部署、升级、备份、恢复、架构、规则与评估边界 |
| docs/WEEK8_WEEK9_ACCEPTANCE_CN.md、SPRINT1_REVIEW_CN.md | 内部目标映射、验收、5分钟讲稿、风险与Sprint2成功标准 |
| README、Parser/系统/数据库说明、KNOWN_ISSUES、NEXT_STAGE | 消除“尚无会话/尚无官方比较”等过期描述，保留真实外部验收缺口 |
| docs/release_manifest.json | v0.3版本及代码/验证产物SHA-256冻结 |

## 3. 关键设计选择

会话不改变 Parser v1 的非空上下文报错语义；初始消息及完整替换走原Parser，后续短回复以完整匹配命令合并，避免吞掉未知尾部约束。替换会清除未重新说明的旧约束，UI明确提示。

发送和修改只预览，显式确认才写生产；确认使用最新队列重算，订单版本变化拒绝旧确认。多轮记录、草稿、请求/决策审计和分配/队列在同一事务提交。会话恢复读取最近保存结果；实际浏览器验证中发现并修复“刷新只恢复草稿但丢失预览和提示”的问题。

应用版本升级为v0.3，原Pipeline保持v0.2，保留既有分配key重放。官方harness只返回单工坊选择，适配器不把拆单表现混入官方分数；混合权重和生产算法本身未因本轮评估调参。

## 4. 验证结果

168测试全部通过，0失败/错误/跳过；60离线parser和30原始行为回归保持全匹配。会话及生命周期持久库连续演示通过，官方基线一致。Chrome核验缺订单、修改、刷新、确认后为单次分配。完整证据见 [验收记录](WEEK8_WEEK9_ACCEPTANCE_CN.md)。

模拟器seed5105，共14组运行、24组新策略/基线比较。速度目标标准场景平均8.05天、迟交1.67%，同时披露成本和部分质量指标上基线更优。报告保留396条不利比较记录和10个不同订单例子。

## 5. 保留与未完成

原始data、官方harness、Week4 baseline、Parser/Prompt v1、migration001/002、在线模型及依赖版本保留。用户runtime库未重置；本轮实际浏览器演示使用独立/tmp库。不提交密钥、.env、.venv、业务库或原始服务错误。

本轮未重跑真实Gemini请求；在线全量验收仍失败。原始Schema、标签复核、独立holdout、解释评分与业务确认仍待完成。正式Week9 slides/上传/彩排未冒充完成；后续见 [交接](NEXT_STAGE_CN.md)。
