# DeepSeek 本机配置与接入说明

更新：2026-10-07，适用于 MVP v0.5。不要把 API Key 发到聊天里、写入代码或提交到 Git。服务只读取启动进程的环境变量；浏览器不保存 Key，项目不自动加载 `.env`。

## 最快启动方法（macOS / zsh）

在你自己的终端进入 `Workspace`，先停止占用 8000 端口的旧服务，再执行：

```zsh
source .venv/bin/activate
read -rs 'DEEPSEEK_API_KEY?请输入 DeepSeek API Key（不回显）: '
printf '\n'
export DEEPSEEK_API_KEY
python -m app.server --backend deepseek
```

输入 Key 的那一步在你本机进行，输入不会显示，也不出现在上面的命令文本里。变量只对当前终端及其启动的子进程有效，关闭终端后需要重新设置。无需安装 OpenAI SDK；DeepSeek 接口使用 Python 标准库 HTTPS。

如果你已经在电脑环境中配置 `DEEPSEEK_API_KEY`，在能读取该变量的终端执行 `python -m app.server` 即可：未指定 `PARSER_BACKEND` 时，有 DeepSeek Key 自动使用 DeepSeek，没有则使用 offline。显式 `--backend` 的优先级最高，其次是 `PARSER_BACKEND`。为了明确演示使用哪个服务，也可以始终加 `--backend deepseek`。

**终端设置环境变量不会更新已经启动的服务。** 每次更新 Key、模型或后端后需要重启服务；创建新请求使用新后端，已有会话保留创建时的 backend。旧离线会话不会自动变成 DeepSeek 会话。

## 长期保存在本机：macOS 钥匙串

如果希望不反复输入，可由你在“钥匙串访问”中创建密码项目：项目名称 `sweaterco-deepseek`，账户填当前 macOS 用户名，密码填 DeepSeek Key。然后在你自己的启动终端执行：

```zsh
export DEEPSEEK_API_KEY="$(security find-generic-password -s sweaterco-deepseek -a "$USER" -w)"
python -m app.server --backend deepseek
```

命令从钥匙串读取到进程环境，不打印内容；首次可能出现 macOS 本机授权提示。需要自动加载时，可自行把上面的 `export` 行加入你的 shell 配置文件；配置文件中只有读取命令，Key 留在钥匙串。不要运行 `echo "$DEEPSEEK_API_KEY"` 或把包含环境变量的诊断结果发到聊天里。

## 可选配置

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 无 | 必需，由本机提供 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 可调整为账户支持的 `deepseek-*` 模型 |
| `DEEPSEEK_TIMEOUT_SECONDS` | `30` | 单次 HTTP 超时，范围大于 0 且不超过 300 秒 |
| `PARSER_BACKEND` | 自动选择 | `deepseek` / `offline` / `llm`（Gemini） |

截至本次核对，官方模型文档使用 `deepseek-flash`；JSON 输出要求 `response_format=json_object` 及明确 JSON 提示。本项目固定请求 `https://api.deepseek.com/chat/completions`，关闭 thinking、非流式返回，限制输出长度，并对模型结果再次执行既有字段和约束校验。模型名称可通过环境变量更换。[官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)、[JSON 输出说明](https://api-docs.deepseek.com/guides/json_mode/)、[Chat Completions 契约](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 如何确认接入

1. 登录 `http://127.0.0.1:8000`，页面应显示 **DeepSeek** 和配置的模型名称。
2. 登录后打开 `/api/ai/status`，只返回 backend、configured、model，不含 Key。`configured=true` 只表示本机提供了配置，不代表远端已验证通过。
3. 创建一个**新请求**：`Allocate ORD-045 at the lowest cost; exclude W3.`。若该订单已分配，请从 Inbox 选另一个 Ready 订单。
4. 查看推荐摘要；追加 `Please prioritize speed and use W6 for this order.`，应保留订单及 W3 排除，并更新目标与指定工坊。仍需点击 Accept allocation 才执行。
5. 无 Key、认证失败、余额不足、限流、连接失败或不合规范输出，会显示服务问题与具体处理方向。不会把服务错误当成“缺少订单信息”，也不会静默切成其他模型。

本轮使用模拟 HTTP 响应测试了接口契约、重试、错误处理与密钥不出现在遥测中；没有真实 DeepSeek 调用。你添加本机 Key 后，才可完成实际账户的连通性和模型效果验收。

## 使用范围

DeepSeek 负责把你输入的本轮文字转换为结构化要求；只发送输入文字、解析规则、示例和工坊名称词表，不上传整个数据库或账号信息。已有草稿在本机合并：未提及的要求保留，新排除工坊追加，已有订单不允许被悄悄替换。清空排除、取消指定工坊、取消硬交期优先使用表单或明确快捷命令。

分配算法继续在本机计算资格、件数、成本和 ETA；自然语言结果由实际方案字段生成，标明待审批或已保存，并把摘要写入会话审计。这里没有额外调用大模型改写数值，也没有让模型直接写数据库。表单修改在 DeepSeek 不可用时仍可使用。

Parser v1 的证据规则仍然保守，不能承诺任意中英文句式都支持。预算上限、精确拆分比例、修改订单登记资料等超出当前业务能力的要求会保留阻断，需要重写要求或人工处理。
