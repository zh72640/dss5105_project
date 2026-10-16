# MVP v0.2 本轮变更与验收

日期：2026-10-02。基于 `2207f29`，目标为 GitHub `zh72640/dss5105_project` 的 `ningtao` 分支；未改其他分支。新增代码注释及 commit 信息使用英文，使用说明和交接文档使用中文。

## 逐项提交

| 提交 | 内容 |
|---|---|
| bb02527 | 真实 Gemini 在线验收证据、限流分类、评估间隔参数和回归测试 |
| c84be0f | migration 002、部分完工/撤销/失效/原子重派、FIFO 预留、版本与审计、27 条专项测试 |
| e93af25 | 页面、HTTP API、CLI、完整生命周期演示和接口测试 |
| 文档与验收提交（查看本文件的 Git 历史） | 更新当前说明、下一步计划、release manifest 及全部验收产物 |

## 新增文件

| 文件 | 用途 |
|---|---|
| app/db/migrations/002_lifecycle.sql | 增加订单版本、累计完工数、分配预留和事件审计表 |
| app/lifecycle.py | 生产状态转换、版本检查、幂等、事务/保存点与审计 |
| app/repositories/queue_repository.py | FIFO 队列衰减、仅释放目标分配的剩余预留 |
| app/lifecycle_cli.py | inspect/complete/cancel/lapse/reassign 命令行入口 |
| demos/lifecycle_demo.py | 单一持久化临时库的完整生命周期演示及不变量检查 |
| tests/test_lifecycle.py | 27 条状态、数量、队列、并发、失败注入和迁移测试 |
| tests/test_lifecycle_cli.py | 跨真实 CLI 进程的查询、完工、重放及退出码测试 |
| tests/test_evaluation.py | 2 条限流分母/错误分类和非法间隔测试 |
| docs/LIFECYCLE_CN.md | 业务语义、队列、迁移、审计、页面/API/CLI 操作说明 |
| docs/GEMINI_LIVE_ACCEPTANCE_CN.md | 首次真实在线验收及服务限流问题 |
| docs/CHANGELOG_LIFECYCLE_CN.md | 本次交付、文件变化及验证范围 |
| evaluation/results/parser_llm_metrics.json | 首次真实模型完整评估指标，明确验收失败 |
| evaluation/results/lifecycle_demo.json | 生命周期连续演示、队列/外键/幂等检查证据 |

## 修改文件

| 文件 | 变更 |
|---|---|
| app/db/database.py | 支持 v1 → v2 事务迁移，回填旧预留，不重导种子数据 |
| app/pipeline.py | 版本升为 mvp_v0.2，只分配未完工数，维护订单版本和分项队列 |
| app/server.py | 新增订单读取/生产事件接口，历史显示人工操作对应订单 |
| app/ui/index.html | 增加读取订单、完工、撤销、重派、失效、版本和历史；修复动态表单隐藏/校验 |
| evaluation/evaluate_parser.py | 配置用例间隔、服务错误统计，与验收阈值一致的 validated 标记 |
| evaluation/verify_gemini_live.py | 暴露间隔参数、在线摘要包含服务失败证据 |
| evaluation/verify_mvp.py | 加入完整生命周期 demo 的检查与产物 |
| tests/test_server.py | 增加 3 条 HTTP/页面测试，HTTPError 响应及时关闭 |
| README.md / README_parser.md / KNOWN_ISSUES.md | 更新版本、功能入口、真实验收状态与剩余限制 |
| docs/SYSTEM_GUIDE_CN.md / DATABASE_SCHEMA_CN.md / schema_contracts.md | 同步当前接口、迁移、数量与状态语义，保留历史契约 |
| docs/NEXT_STAGE_CN.md | 标记生命周期已完成，明确 Gemini 配额、Session、数据管理和课程评估的顺序及验收条件 |
| docs/WEEK5_WEEK6_ACCEPTANCE_CN.md | 标记主体为历史记录，追加 v0.2 当前结果 |
| docs/release_manifest.json | 更新版本、冻结文件 SHA-256 和真实验收状态 |
| evaluation/results/gemini_live_status.json | 从缺 key / NOT_RUN 更新为真实冒烟成功、完整验收失败 |
| evaluation/results/verification_summary.json / test_results.txt | 最新 150 条自动测试与完整验收摘要 |
| evaluation/results/parser_offline_metrics.json / parser_offline_runs.jsonl | 离线解析指标及逐条证据 |
| evaluation/results/dispatch_runs.jsonl / week5_mock_demo.jsonl / week6_demo.json | 更新本轮回归、版本和演示产物 |

## 验证结果与限制

执行 `.venv/bin/python evaluation/verify_mvp.py`：**150 条通过，0 失败、0 错误、0 跳过**。相比原 117 条，新增 27 条生命周期/迁移、2 条评估、3 条 HTTP/页面、1 条 CLI 测试。

- 60/60 离线 parser golden、30/30 原始行为标签匹配。
- 官方 standard/shock 模拟器输出与历史基线完全一致，未声称新分配器更优。
- 生命周期演示 verified=true，队列守恒、外键、重放全部通过。
- Chrome 在独立 /tmp 测试库真实执行 ORD-045：W6 分配150 → 完成50 → W8重派100 → 刷新 → 完成100；最终 COMPLETED、150/150、剩余0、version4，历史可见。
- Gemini 真实端到端冒烟成功；60条中14条匹配，其余46条最终HTTP429，完整验收未通过。尝试中出现91次429及6次503，不能把无输出的服务失败解释为模型字段错误，也不能剔除失败用例来宣布达标。
- Data Schema2原始DDL核对、业务方政策确认、第二位人工标注复核及独立holdout仍待完成。

所有 UI/自动验收使用独立临时或内存数据库，未重置用户 runtime。原始 data、官方 harness、Week4 fixtures/baseline、Parser/Prompt v1、migration001 和依赖版本不变；没有提交密钥、.env、运行数据库、.venv 或原始服务错误。历史 `file_change_manifest.json` 保留为旧版档案，当前冻结以 release_manifest 为准。

下一阶段执行入口：[NEXT_STAGE_CN.md](NEXT_STAGE_CN.md)。
