# 多模型接入与请求级选择

实现使用 LangChain 的四家供应商集成与共用 LangGraph 调用节点。模型配置在创建应用时读入一次，后续请求使用已保存配置。

## 启动

```powershell
uv sync --locked
uv run --locked --env-file .env python -m app.server
```

已有数据库和账号可以继续使用；首次创建数据库请按 UV_SETUP.md 的初始化步骤执行。`.env` 不由 Python 自动加载，必须显式使用 `--env-file`。没有配置模型密钥时仍可启动，默认 LLM 文本请求会提示模型未配置，可以在界面切换 Offline 或使用 Edit details。

## 配置模型

```dotenv
AGENT_MODE=llm
OPENAI_API_KEY=your-key
OPENAI_MODELS={"model-a":"actual-api-id-a","model-b":"actual-api-id-b"}
ANTHROPIC_API_KEY=your-key
ANTHROPIC_MODELS={"claude-main":"actual-claude-api-id"}
LLM_DEFAULT_MODEL=model-a
```

使用供应商实际支持的 API ID 替换占位值。项目别名和界面产品名称不是 API ID 的验证依据。密钥仅保留在本地 `.env`，不放进请求体。

OpenAI、Claude、Gemini、DeepSeek 分别由 OPENAI、ANTHROPIC、GEMINI、DEEPSEEK 环境变量前缀确定供应商。支持每家一个 `*_MODEL`，或多个 `*_MODELS` JSON 映射；不同供应商的别名必须唯一。旧 GEMINI_API_KEY/GEMINI_MODEL 和 DEEPSEEK_API_KEY/DEEPSEEK_MODEL 保持兼容。

默认模式为 LLM；`--mode offline` 可覆盖启动默认模式。请求选择优先于启动默认值，无须重启。修改 `.env` 中的密钥或模型目录后需要重启。

## 页面使用

登录后在 Processing mode 中选择 LLM 或 Offline rules；LLM 下通过 Model 下拉框选择配置中的模型。下一条消息可以使用不同模型，session 草稿继续保留。未确认响应的请求会固定原来的模式和模型，并禁止改选，重试仍使用原请求 ID。

模型初始化成功只说明本地集成就绪；真实密钥、额度和模型访问权限在实际请求时验证。模型调用失败不自动换供应商。

## API

`GET /api/models`：返回默认模式、默认模型、已注册别名、供应商、API ID、配置/初始化状态，不包含密钥。

```json
{
  "request_id": "dispatch-001",
  "message": "Allocate ORD-045 fastest.",
  "mode": "llm",
  "model_key": "model-b"
}
```

模型选择随 **Chat v2** 会话创建与回合提交：`POST /api/chat/sessions` 与 `POST /api/chat/sessions/{id}/turns`。mode 和 model_key 都可以省略；省略时使用默认配置。offline 不能同时指定 model_key。旧 `POST /api/requests` 与 `/api/sessions` 已退役。

确认、关闭和结构化编辑不需要调用 LLM；即使没有 LLM 密钥，也可以通过 Edit details 填写订单并进行显式确认。

同 request_id 的相同输入可以重放；同 request_id 改模型/模式返回 409。重试省略模型时恢复第一次请求实际使用的选择，不因默认模型改变而重算。

## 可选模型参数

`*_TIMEOUT_SECONDS` 控制超时；`*_OPTIONS` 是参数 JSON，例如温度、输出 token 限额和供应商支持的 reasoning/thinking 参数。工厂不会强行给所有模型设置 temperature。

`*_STRUCTURED_OUTPUT` 默认 prompt，复用已有 JSON 提示和 validator。可按实际模型能力设置 json_schema、json_mode 或 function_calling；选择未被对应模型支持的方法会明确失败。输出始终经过项目的 schema、字段和原文证据检查。

Parser 拥有一次重试，集成 SDK 自动重试设为 0，避免重试次数相乘。响应的 parser_telemetry.execution 记录 mode、model_key、provider、API ID 和配置签名，其他 telemetry 保存 prompt、耗时、重试和可取得的用量。

## 兼容与限制

allocation、资格、估算、既有 SQLite CRUD/事务及 schema 原样保留。新增 gateway 和 read-only helper 完成模型选择与审计一致性检查。

旧 session.backend 字段继续保留历史值；每轮实际模式/模型以该轮 parser_telemetry.execution 为准。教授 simulator 仍走确定性分配器。

后台 jobs 仍使用既有任务格式，没有新增逐任务模型字段；后台执行使用启动配置的默认模型（历史 offline session 继续离线）。若要指定模型，使用 session turn 接口。业务数据库仍是唯一会话状态来源，切换模型不会自动新增完整对话历史推理功能。

## 配置代码位置

应用配置定义在 `app/config/settings.py`，模型环境配置解析在 `app/config/model_settings.py`，启动参数合并在 `app/config/bootstrap.py`。`app/core/lifespan.py` 启动时加载一次配置并初始化资源，关闭时清理资源。`app/main.py` 只组装应用。通过 `--env-file` 加载环境文件的启动方式保持不变；命令行参数优先于环境变量。
