# SweaterCo Dispatch Desk — MVP v0.5

DSS5105 Track 2 的本机外包调度系统：自然语言请求、澄清草稿、工坊资格和队列分析、推荐与显式审批、生产进度及完整审计。

**2026-10-08 更新：**新增 DeepSeek 环境变量接入、自然语言分配摘要、首页最近审批、具体澄清问题、无需 AI 的修改表单，以及 Small / Medium / Large 字号设置。详情见 [v0.5 修改说明](docs/CHANGELOG_V05_CN.md)、[本机配置 DeepSeek](docs/DEEPSEEK_SETUP_CN.md) 和 [新版测试流程](docs/V05_TEST_WALKTHROUGH_CN.md)。界面继续采用英文，审批和历史导出保留。

## 立即运行

在仓库根目录（本机为 `Workspace`）执行，Python 3.10+：

```bash
# 首次运行：创建本地账号，交互输入至少 12 位密码
python3 -m app.auth dispatcher

# 启动并登录英文操作台
python3 -m app.server --backend offline
```

打开 <http://127.0.0.1:8000>。无预置通用密码，离线运行不需要第三方依赖。首次建立 `runtime/dispatch.sqlite3`，导入 120 个订单、8 个工坊；以后保留已有数据。**已有数据库先停服务备份，再创建账号或启动新版**，两者均可能自动应用 migration 004。步骤见 [部署与升级](docs/DEPLOYMENT_CN.md)。

页面流程：New request → 澄清缺失内容 → 核对推荐/理由 → Accept allocation。发送和修改仅保存草稿，接受才分配。Production 支持部分/全部完工、撤销、失效和重派。原中文页面保留于 `/legacy`，同样受业务接口登录保护。

## 文档入口

- [UI 修改说明](docs/UI_CHANGELOG_CN.md)：新增什么、为何修改、文件与版本变化。
- [v0.5 验收](docs/V05_ACCEPTANCE_CN.md)：本轮自动测试、浏览器检查和真实模型验证边界。
- [UI 操作与课程演示](docs/UI_GUIDE_CN.md)：英文按钮、业务口径及五分钟演示顺序。
- [UI 需求映射与验收](docs/UI_ACCEPTANCE_CN.md)、[需求原件](docs/requirements/README.md)。
- [部署、升级、账号、备份与恢复](docs/DEPLOYMENT_CN.md)。
- [项目整体说明](docs/PROJECT_OVERVIEW_CN.md)、[下一阶段交接](docs/NEXT_STAGE_CN.md)。
- [会话契约](docs/SESSIONS_CN.md)、[生命周期](docs/LIFECYCLE_CN.md)、[数据库](docs/DATABASE_SCHEMA_CN.md)、[系统/API/CLI](docs/SYSTEM_GUIDE_CN.md)。
- [模拟器对比](evaluation/results/simulator_comparison_CN.md)、[Gemini 在线验收](docs/GEMINI_LIVE_ACCEPTANCE_CN.md)、[已知限制](KNOWN_ISSUES.md)。
- [历史 v0.3 修改](docs/CHANGELOG_WEEK8_WEEK9_CN.md)、[Sprint 1 讲稿](docs/SPRINT1_REVIEW_CN.md)。

## 演示与验证

```bash
python3 -m demos.session_demo
python3 -m demos.lifecycle_demo

# 完整 Python 验收需安装固定 Gemini SDK，用模拟传输测试，不调用真实模型
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python evaluation/verify_mvp.py
python evaluation/verify_ui.py

# 前端控制器验证需 Node 18+；应用运行无需 Node/npm
node --test tests/test_ui_state.cjs
```

已保存：**203 条 Python 测试及 7 条前端控制器测试通过**；60/60 离线解析、30/30 原始行为匹配；会话/生命周期及 14 组模拟器回归通过。机器结果见 [verification_summary.json](evaluation/results/verification_summary.json)。[ui_latency.json](evaluation/results/ui_latency.json) 是 v0.4 的历史离线测量，不代表 DeepSeek 在线性能。

Safari 已检查新版首页、大字体、新建请求、具体澄清、表单补订单、实际审批与首页摘要；生产页、历史导出和移动端边界见 [本轮验收](docs/V05_ACCEPTANCE_CN.md)。自动测试不代表真实 DeepSeek/Gemini 连通性与效果通过。

## 当前边界

默认业务日期为 `2026-04-01`，统计审批“今天”使用真实 UTC 日期。发布 v0.5、DB v4、Session/Parser/Prompt v1；Pipeline 保持 v0.2。服务只绑定 `127.0.0.1`，登录用户共享一个工作区，尚无角色与租户隔离。

DeepSeek 从 `DEEPSEEK_API_KEY` 读取本机密钥，默认模型 `deepseek-flash`，以 `python -m app.server --backend deepseek` 启动。未显式指定后端且存在 Key 时也会自动选择 DeepSeek；`.env` 不会自动加载。已有会话保留原后端，需要创建新请求。Gemini 仍可用 `--backend llm`。本轮没有真实模型调用；2026-10-02 Gemini 全量评估的 429 失败结论仍保留。全局限速/退避、工坊产能编辑、自动过期和独立数据评估仍待完成。
