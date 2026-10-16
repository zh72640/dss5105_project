# 下一阶段交接说明

更新：2026-10-09；GitHub分支 ningtao；当前发布 **MVP v0.5 / Session v1 / Parser、Prompt v1 / Database v4**。原分配Pipeline仍为v0.2，保留既有幂等语义。先阅读 [本轮修改](CHANGELOG_V05_CN.md)、[部署说明](DEPLOYMENT_CN.md) 和 [整体项目说明](PROJECT_OVERVIEW_CN.md)。

## 已经完成，不重复开发

1. 生命周期：部分/全部完工、撤销、失效、原子重派；订单版本、幂等、数量与队列守恒。
2. 持久化会话：sessions/messages、缺订单号澄清、显式约束修改、预览、确认、关闭、刷新恢复；页面/API/CLI及临时持久库演示。
3. 并发编辑/确认、跨会话隔离、模型失败阻断、审计故障回滚、v1/v2/v3到v4迁移已验证。Parser v1本身没有开放任意上下文。
4. 官方模拟器适配：生产planner单工坊模式，对三基线及四目标运行standard/shock，共14组；原harness和基线未修改。
5. 203条Python测试及7条前端控制器测试通过、0跳过；60/60离线解析、30/30行为标签；会话/生命周期demo通过。历史 Chrome 会话流程与本轮 Safari 部分检查按版本留存，不宣称 v0.5 完整浏览器验收。
6. 中文部署、整体说明、修改说明、Week8/9验收与Sprint1讲稿已整理。正式slides、团队信息和课程上传仍未完成。
7. DeepSeek 环境变量接入、自然语言追加、事实摘要、首页最近分配、具体澄清及无需 AI 的编辑表单、大中小字号已经实现；无需重复开发。配置见 [DeepSeek 本机接入](DEEPSEEK_SETUP_CN.md)。

证据入口：`evaluation/results/verification_summary.json`、`simulator_comparison_CN.md`、`session_demo.json`。当前冻结清单为 `docs/release_manifest.json`；历史 `file_change_manifest.json` 和Week5/6文档不代表最新版本。

## UI 交付与仍需补验

英文界面、登录、审批身份、工坊查询、历史分页与全量导出已经完成，不需要重写。资料：[操作指南](UI_GUIDE_CN.md)、[本轮验收](V05_ACCEPTANCE_CN.md)、[HTTP 契约](UI_API_CN.md)。数据库 004、原始需求副本和 v0.3/v0.4 冻结清单已保存。只有首次使用才用 `python -m app.auth 用户名` 建账号，已有账号不重建；旧库先备份。本轮无数据库迁移。

浏览器工具恢复后，优先补手机宽度、拒绝修订后的最终接受、历史导出及生产页完整点击链；Safari 已完成的检查见验收记录。HTTP/控制器通过不等于全部设备实机通过。不要重新调用真实 Gemini 来验证纯 UI 变动。

## 第一优先级：在线可靠性与外部验收

| 工作 | 下一步 | 完成条件 |
|---|---|---|
| DeepSeek 真实接入 | 用户在本机配置 Key，重启并创建新请求；先验证单条与追加要求，再扩展表达集 | 账户连通、字段正确、保留旧约束、明确服务错误；记录真实运行结果，不用模拟结果替代 |
| Gemini配额和全量回归 | 核查429原因，恢复后先冒烟，再按项目配额运行带间隔的full评估；保存原失败证据 | 全60条计入分母：首轮结构有效率≥98%、核心字段≥90%、观测补造为0 |
| 生产限速与有界退避 | 原Parser最多一次重试仍无退避；新增可测限速/退避与追踪，不无限重试 | 模拟时钟、并发、超时测试及真实流量确认；任何失败不得分配 |
| Data Schema2核对 | 获取原ERD/DDL，对照当前001–004逐列记录差异 | 有核对记录；需要变更时新增005，不重写已发布迁移 |
| 标签与holdout | 第二位成员复核60条解析及30条行为标签；另建未参与调试的表达集 | 有复核者、日期、分歧及独立结果，不反向按程序输出改expected |
| 解释忠实性 | 对原30条逐一核对决定和解释，数值、理由分别溯源 | 分类结果及失败分析，不能用行为30/30替代解释评分 |
| 主目标与业务规则 | 确认课程分配的主目标、混合权重、时间政策、cancel/lapse/重派含义 | 团队书面确认，必要时同步代码/测试/文档 |

最新真实 Gemini 结果仍为2026-10-02：冒烟成功，完整评估14/60匹配、46条最终HTTP429（尝试中另有503）。这说明在线全量验收未通过，不等于收到模型输出的准确率只有23.33%；不能剔除无输出用例宣布通过。本轮没有调用真实模型，也没有 DeepSeek 在线成绩。

```bash
source .venv/bin/activate
python evaluation/verify_gemini_live.py
python evaluation/verify_gemini_live.py --full --interval-seconds 10 --output-dir evaluation/live_results/next-run
```

10秒仅为示例，不保证满足配额；不得无间隔反复运行full。原始在线输出在忽略目录中，审阅无密钥摘要后再提交。

## 第二优先级：Week9正式展示与Sprint2准备

课程总要求为2026-10-16 15:00前上传Sprint1 slides、19:00展示。使用 [中文讲稿](SPRINT1_REVIEW_CN.md) 制作正式 `Presentation_GroupX_Sprint1.pptx/pdf`，填入组号、成员和讲述安排；进行5分钟彩排并准备2分钟问答。此轮为现场讲述，不能写成已经完成视频或正式上传。

展示时区分离线功能验收、模拟器实验和真实模型结果。速度目标时间指标占优，但成本、部分质量及集中程度有基线更好；这些权衡应主动披露。Sprint2成功标准和建议角色已列在讲稿中，实际负责人由团队填写。

## 第三优先级：工坊管理与进一步评估

- 工坊关闭/恢复、产能变更和队列校正：先明确数据来自事件还是外部快照；使用新迁移、版本检查和操作者审计。必须维护 baseline + 活动预留 = current_queue_days，不能直接修改聚合队列而丢掉分项。
- 评估扩展：适配已完成，不必重写；预先固定更多seeds及分析方法，再跑主/次/hybrid配置。单工坊官方结果与拆单补充实验分开；标准与shock的返工抽样不同，不把差值解释为纯停工效应。
- 语言扩展：在现有session_v1边界之外，优先收集复合约束、自由表达和中文失败例。先明确变更契约及证据校验，再扩展；不直接把历史拼接给模型后允许写库。
- 时间和策略：当前日历天FIFO、UI ceil/官方round；hybrid混合不同单位且为启发式。先确认业务规则和权重，再考虑其他优化算法。

RAG、Agent编排、公网部署、角色与租户权限、自动完工/过期继续留待明确需求，不阻塞当前课程主链路。

## 下次接手检查

```bash
git status --short --branch
git log --oneline -8
source .venv/bin/activate
python -m demos.session_demo
python -m app.server --db runtime/next-stage.sqlite3
```

先对照工作区与已保存验收记录判断是否需要重跑；仅文档变动不重复调用模型或全量测试。代码有改动时运行相应测试，再按风险执行 `python evaluation/verify_mvp.py`。已有运行库按部署说明先备份，演示优先使用独立库。继续按功能/修改目标分组英文commit并及时推送ningtao，中文文档同步更新。
