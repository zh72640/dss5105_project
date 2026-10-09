# MVP v0.5 验收与证据

整理：2026-10-09。测试在 10 月 7–9 日分阶段完成；中断后核对已有产物，没有重置运行数据或重复审批。发布为 `mvp_v0.5`，SQLite 仍为 v4，Parser/Prompt/Session 仍为 v1，原 Pipeline 保持 v0.2。

## 用户需求对照

| 需求 | 已实现 | 验证与边界 |
|---|---|---|
| 本机 DeepSeek API 接入 | 环境变量 Key、可选模型与超时、严格 JSON 校验、最多两次尝试、明确服务错误、无密钥状态接口 | 模拟 HTTPS 覆盖成功、缺 Key、认证/余额/限流、无效响应、重定向拦截；未调用真实账户 |
| 老板一眼看懂分配 | 待审批/已保存自然语言摘要，件数、工坊、日期、费用和逾期提示；首页最近五次分配 | 摘要与实际结果字段一致；Safari 实际批准并在首页看到同一摘要 |
| 追加要求可理解、可修复 | DeepSeek 解析本轮追加并保留旧约束；所有模式可用详情表单；具体问题和补充方法 | 缺订单、字段冲突、无资格工坊、不可行方案、服务错误分别处理；不支持的业务约束继续阻断 |
| 字号大中小 | Small 14px / Medium 16px / Large 20px，文本使用相对单位，本浏览器记忆 | 控制器验证保存与非法值回退；Safari 检查大字正文、导航、输入框、弹窗及刷新保留 |
| 文档与部署 | 修改说明、密钥配置、部署/回退、手动测试、接口契约、验收和发布冻结清单 | 原有 v0.4 清单归档；没有数据库迁移或密码重置 |

## 自动回归

- `evaluation/verify_mvp.py`：**203 项 Python 测试通过，0 失败、0 错误、0 跳过**。记录时间 `2026-10-07T21:03:45Z`，即新加坡 10 月 8 日。
- `node --test tests/test_ui_state.cjs`：**7 项通过**，包括字号持久化、表单安全重试、重复点击与不确定确认保护。
- 离线 parser 60/60；原始请求行为匹配 30/30；生命周期、会话持久化、幂等、队列一致性和外键检查通过。
- 官方模拟器基线一致，14 组策略比较完成；本轮没有修改分配算法和课程基准数据。

证据：[机器汇总](../evaluation/results/verification_summary.json)、[Python 测试输出](../evaluation/results/test_results.txt)、[前端测试输出](../evaluation/results/ui_controller_tests.txt)。新专项见 `tests/test_deepseek.py`、`tests/test_assistant_desk.py`，HTTP 新字段与审批摘要由 `tests/test_desk.py` 覆盖。

## Safari 实际检查

使用独立临时数据库与 `127.0.0.1:8015`，不写用户 `runtime/dispatch.sqlite3`。临时服务在结束后关闭。

1. 检查新版首页、Medium / Large、New request 弹窗，以及大字号的阅读和输入布局。
2. 输入缺订单的最低成本请求，显示 **Which order should I allocate?** 和具体 ID 示例，不能接受；通过表单补 `ORD-045` 得到推荐。
3. 刷新保留 Large、已有草稿和推荐，计算及对话详情默认折叠。
4. 10 月 9 日恢复该草稿并点击 **Accept allocation**。回复从 Proposed 变为 Approved and saved，保存 150 件给 BudgetWorks / W3、120 cost units、ETA 2026-04-10，并明确晚于交期；接受入口关闭，出现 Next request。
5. 回 Overview，**What was assigned?** 出现相同审批摘要；待办由 34 变 33，生产中由 0 变 1，W3 具名订单出现 ORD-045。

浏览器工具期间出现 `cgWindowNotFound`、窗口位置错误及超时；恢复后补完上述审批与首页检查。生产页、历史详情/导出和手机宽度的完整实机链路仍未完成，不能用 HTTP 或控制器测试替代这些布局验收。现有 `ui_latency.json` 是 v0.4 历史测量，本轮未重新测量延迟。

## 运行与剩余边界

10 月 9 日已启动新版 `http://127.0.0.1:8000`，健康接口返回 `mvp_v0.5`、backend=offline；账号接口确认需要登录且已有账号，无需重新设置。账号、订单和审批数据沿用现有运行库。

本轮没有真实 DeepSeek/Gemini 调用，没有写入 API Key，没有公网部署。DeepSeek 在线连通性与自由表达质量需用户本机设置 Key 后另行验证；`configured=true` 不代表在线验收通过。历史 Gemini 429 失败证据继续保留。

自然语言回复由真实分配字段生成，避免另一份模型输出改变数值；模型负责输入解析。预算上限、精确拆分比例、订单主数据编辑、任意中英文表达仍不承诺支持。审批仍在最新队列下重新计算，不能将先前预览视为最终已保存结果。

使用入口：[手动测试流程](V05_TEST_WALKTHROUGH_CN.md)、[DeepSeek 本机配置](DEEPSEEK_SETUP_CN.md)、[部署与回退](DEPLOYMENT_CN.md)、[具体修改](CHANGELOG_V05_CN.md)。
