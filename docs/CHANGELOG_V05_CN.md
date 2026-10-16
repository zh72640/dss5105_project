# MVP v0.5：DeepSeek、老板视图与可操作澄清

更新：2026-10-07。延续英文界面用于课程展示，说明文档使用中文。数据库仍为 v4，没有新增迁移；Parser v1、Session v1 和原分配算法的核心契约保持兼容。

## 本轮具体修改

| 用户问题 | 新行为 | 主要文件 |
|---|---|---|
| 需要 DeepSeek，Key 只保存在本机 | 新增环境变量接口、自动后端选择、模型/超时配置、配置状态展示、稳定错误码 | `app/agent/deepseek_client.py`、`parser.py`、`server.py`、CLI |
| 不能快速看懂分配结果 | 推荐页首先显示订单、总件数、各工坊件数、ETA、总成本和目标的一段话；区分 Proposed 与 Approved and saved | `app/assistant_reply.py`、`sessions.py`、`desk.js` |
| 老板需要看清最近完成了什么 | 首页 What was assigned? 列出最近五次审批摘要，并可进入当前生产进度 | `app/desk.py`、`index.html` |
| 追加要求总提示补内容 | 缺失字段、冲突原因、示例及处理动作分别展示；服务错误单独说明；增加 Edit details 表单 | `assistant_reply.py`、`agent/draft_edits.py`、`sessions.py`、UI |
| 不方便写固定命令 | DeepSeek 会话可理解本轮自然语言追加内容，本机保留未变更约束；所有后端均可用表单直接修改 | `draft_edits.py`、`sessions.py` |
| 字体太小 | 顶部 Small / Medium / Large，一键切换，默认 Medium 比原版大；刷新和重新登录后保留本浏览器偏好 | `desk.css`、`desk.js`、`index.html` |
| 页面信息过多 | 原始字段、对话、候选工坊和计算详情默认折叠；优先显示摘要、缺失项及审批入口 | `index.html`、`desk.js` |

字号的根字号分别为 14 / 16 / 20px，各类文本换成相对单位；导航、表格、弹窗、输入框一起缩放。小屏布局保留纵向排列与表格局部滚动。

## 交互与业务边界

发送消息、修改表单只更新草稿。Accept allocation 才提交分配，审批仍检查会话/订单版本和最新工坊队列。最终摘要使用确认时实际结果，可能与较早预览不同。晚于交期时摘要会明确提示。

表单提供订单、目标、最大工坊数、偏好工坊、排除、硬交期及可选日期。产品、数量或日期与订单登记冲突时，可显式选择 **Use registered order details**，清除冲突的输入值并使用已有订单。此操作不修改订单登记资料，也不会创建新业务订单。

“新要求超出当前能力”仍会阻断确认，例如预算上限或精确拆分。界面现在说明不支持的原因和下一步，不再反复只说“补充内容”。不相关的字段修改不能自动消除未解决的约束。

DeepSeek 只负责解析，摘要由实际分配数据生成，不额外收费调用模型生成另一份结果；离线也能显示同样的自然语言回复。服务器读取 Key，不提供浏览器输入框，也不写入 Git、日志或数据库。

## 文件和部署

新增 `tests/test_deepseek.py`、`tests/test_assistant_desk.py`，扩展 HTTP 与前端控制器测试；保存完整回归结果。详细证据见 [v0.5 验收记录](V05_ACCEPTANCE_CN.md)。

运行无需前端构建。已有 v4 数据库与账号可直接使用；升级前备份并重启服务。DeepSeek 的非回显输入和 macOS 钥匙串方案见 [DeepSeek 本机配置](DEEPSEEK_SETUP_CN.md)；完整安装和回退见 [部署说明](DEPLOYMENT_CN.md)。

本轮没有重设现有登录密码，没有运行真实 DeepSeek/Gemini 请求，没有上线公网。真实模型的稳定性与效果需你添加本机 Key 后验收。
