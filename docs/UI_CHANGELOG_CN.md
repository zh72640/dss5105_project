# MVP v0.4 英文 Dispatch Desk 修改说明

更新：2026-10-06。起点为 `6b5244c`，分支 `ningtao`。本次根据 `UI_requirement` 的 Word 功能要求和 PowerPoint 页面草图，将原来的单页工具整理为用于课程展示的英文操作台。页面语言按用户确认使用英文，说明文档使用中文。

## 功能变化

| 页面或功能 | 本次实现 | 对使用者的意义 |
|---|---|---|
| Sign in | 本地账号密码登录、退出、8 小时有效会话 | 进入业务接口前验证身份，审批记录能追溯到登录用户 |
| Overview | Pending、Needs clarification、Allocated today、Lapsed 四项统计，待办检索、工坊队列概览 | 打开首页即可判断需要处理的请求和当前产能情况 |
| Request intake | New request 弹窗，支持自然语言及默认目标 | 请求先成为持久化草稿，发送时不分配生产 |
| Recommendations | 左侧订单队列、原始消息、数据库订单字段、约束、澄清输入、候选工坊、推荐及 ETA | 将输入、核对和接受放在同一条工作流程内 |
| Decision review | 时间组成、费用、目标说明、资格排除原因、Accept、Reject & revise | 审批前可以检查数值依据，拒绝后继续修改 |
| Allocation history | 订单/请求检索、状态筛选、分页、原文与解析内容、审批人及时间、CSV/JSON 全量导出 | 不再只看到最近 30 条简略记录 |
| Workshop explorer | 名称/ID、状态、产品类别筛选，产能、批量上限、成本、缺陷率、队列及活动订单 | 可独立查询工坊，无需先发起分配 |
| Production | 英文完工、撤销、重派、失效操作页，操作原因及确认窗口 | 保留 v0.2/v0.3 的生产闭环 |
| 小屏布局 | 800px 以下改为顶部导航与单列内容，统计卡两列、表格局部横向滚动 | 提供响应式布局；移动端实机验收边界见验收文档 |

原中文页面保留在 `/legacy`，用于已有操作流程的兼容。正常入口 `/` 使用新英文界面。原始 Word/PPTX 的副本在 [requirements](requirements/README.md)。

## 如何保证审批与数据一致

新页面只调用会话预览和显式确认。没有订单号、存在澄清阻断、已经关闭或缺少有效推荐时，Accept 不可用；服务端也独立校验，修改按钮状态不能绕过规则。确认时重新检查订单版本和最新队列，然后在同一事务中写入分配、队列、消息、决策审计及审批人。

Reject & revise 会先记录 `Reject recommendation` 回合，并将草稿设置为待澄清，再打开修订对话框。对话框承接同一个会话，以便连续保留原文、拒绝和修改记录。它不会撤销已经提交的分配；已分配订单应使用 Production。关闭修订窗口不会自动恢复被拒绝的推荐。

页面将未确认响应的操作保存到当前浏览器、当前用户名对应的 localStorage。网络失败或服务端 5xx 时，Retry safely 使用原 request ID 和版本；快速重复点击不会创建第二次写入。未确认操作存在时禁止退出登录，防止丢失本地重试信息。登录过期仍可重新登录并继续重试。草稿和对话内容本身保存在数据库。

## 登录和审计范围

新增 `app.auth` 命令行工具创建或重设本地账号；没有预置通用密码。密码使用随机盐和 PBKDF2-HMAC-SHA256（600,000 次）存储，数据库仅保存登录 token 的 SHA-256。Cookie 使用 HttpOnly、SameSite=Strict、8 小时到期。退出或重设密码会撤销登录。每个服务进程每 60 秒最多处理 10 次登录尝试。

HTTP 的审批人由服务端从登录会话确定。生产操作也覆盖客户端传来的 actor，不能伪造他人的审批姓名。历史数据以及未提供 actor 的本地 CLI 分配显示“Not recorded (legacy)”，不会伪造审批人。`--no-auth` 演示模式的会话/直接分配标识为 `local-demo`，不应当作实名审批。

所有登录用户共享一个工作区，均可查看和处理其中的请求；没有角色、部门权限或租户隔离。服务仍只绑定 `127.0.0.1`，没有增加公网部署。HTTP Cookie 的配置针对本机 HTTP，不能直接作为公网 HTTPS 系统的部署方案。

## 后端及文件变化

| 文件 | 作用 |
|---|---|
| `app/ui/index.html`、`desk.css`、`desk.js` | 英文界面、响应式样式、路由、请求状态、重试及页面数据展示 |
| `app/ui/legacy.html` | 保留原中文页面，原 `sessions.js` 继续供其使用 |
| `app/auth.py` | 账号管理、密码验证、登录状态与撤销 |
| `app/desk.py` | 首页、工坊和历史的数据库读取模型；CSV 安全转义 |
| `app/server.py` | 登录保护、新查询/导出接口、静态资源、服务端审批身份 |
| `app/sessions.py` | 拒绝推荐回合、英文提示、预览解释、事务内审批人记录 |
| `app/pipeline.py` | 为直接分配接口增加可选 actor 审计，保留旧 CLI 调用方式 |
| `app/db/migrations/004_desk.sql` | 新增用户、登录和请求操作者表，不修改 001–003 |
| `app/db/database.py` | v1/v2/v3 到 v4 的事务升级 |
| `tests/test_desk.py` | 13 条登录、审批、历史导出、查询及升级测试 |
| `tests/test_ui_state.cjs` | 5 条前端控制器测试，无第三方 Node 依赖 |
| `evaluation/verify_ui.py` | 使用临时库测量认证后的离线 HTTP 响应时间 |
| `docs/UI_GUIDE_CN.md`、`UI_ACCEPTANCE_CN.md` | 页面操作和课程演示步骤、需求映射及验证边界 |

应用版本为 `mvp_v0.4`，数据库版本为 4。Parser/Prompt/Session 版本保持 v1，原 Pipeline 版本保持 `mvp_v0.2`。没有传入 actor 的旧 API/CLI 指纹结构保持不变；带 actor 的 HTTP 操作额外绑定操作者，避免同一请求 ID 被不同用户冒领。升级前遗留且尚未取得响应的 HTTP 请求，不应在新身份下盲目换 key 重发，应先查历史和订单状态。

## 验证结果与保留事项

181 条 Python 自动测试全部通过，0 跳过；新增 5 条前端控制器测试通过。60/60 离线解析、30/30 原有行为匹配、生命周期与会话演示、14 组模拟器运行仍通过。离线本机 HTTP 性能样本全部小于 3 秒，详细分位数在 [延迟报告](../evaluation/results/ui_latency.json)。

Safari 已实际检查登录、首页、缺订单号澄清、补充 ORD-045、刷新恢复、候选与解释页，以及拒绝后弹出的修订窗口。后续浏览器控制不可用，修订后的最终接受由接口测试覆盖；手机尺寸、最终历史页/生产页的完整实机流程尚未验收。不能将控制器或 HTTP 测试写成完整浏览器端验收。详见 [验收记录](UI_ACCEPTANCE_CN.md)。

本次没有调用真实 Gemini，旧在线配额问题仍存在。没有更改原始 CSV、模拟器基线或用户 runtime 业务库；浏览器及性能测试均使用独立临时库。需求源文件和新文档会随代码提交，编辑器临时文件、密码、数据库、.venv 和密钥不纳入提交。

## Git 交付记录

功能与验证提交：`5eff0da` — `Build authenticated English dispatch desk with auditable approvals and exports`。文档与发布清单归入后续独立提交，具体编号以 Git 历史为准。发布清单保存在 `docs/release_manifest.json`；上一版原始清单保留在 `docs/releases/mvp_v0.3_manifest.json`。
