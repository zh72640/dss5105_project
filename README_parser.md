# Parser v1 接口与冻结说明

版本：`parser_v1`。源契约是 `app/schemas/parser_schema.py`，Prompt 是 `app/agent/prompts.py`。`docs/release_manifest.json` 记录本次冻结的代码 SHA-256。Week 6 下游仅消费 `ParseResult`，不读取原始自然语言。

## 调用

```python
from app.agent.parser import parse_request, parse_with_telemetry

parsed = parse_request(
    "Allocate ORD-045 cheapest; exclude W03; at most two workshops.",
    context_messages=[], backend="offline",
)
assert parsed.parse_status == "ok"
print(parsed.to_dict())
```

`parse_request(message, context_messages=None, *, backend=None, reference_date=date(2026,4,1)) -> ParseResult`。

- `backend`: `offline` 或 `llm`；未传时读取 `PARSER_BACKEND`，缺省为 offline。测试可注入实现 `complete()` 的对象。
- `context_messages` 必须为空；非空返回 `context_not_supported`，不会把上次信息偷偷加入本条消息。
- 普通非法意图返回 `parse_status=invalid`。两次结构/证据校验失败时，此便利接口抛出 `ValidationError('parser_error:...')`。
- 集成端使用 `parse_with_telemetry()`；它返回 `ParserOutcome(parsed, telemetry, error)`，失败时 `parsed=None`。Pipeline 转成 `ERROR/PARSER_ERROR`，不会执行分配。
- `request_id` 由 Pipeline 为每条消息创建，位于外层；R09 是原始文件的标签，session_id 预留为 NULL，两者都不能作为模型猜测订单的依据。

## 字段

| 字段 | 类型 / 默认 | 规则 |
|---|---|---|
| order_id | string / null | 原文明确 ID，规范大写；不按客户猜订单 |
| customer, product | string / null | 必须有原文证据；产品可做单复数归一化 |
| category | TOPS / ACCESSORIES / null | 可从原文服装类型做词典归一化 |
| pieces | positive integer / null | 不接受 bool、小数、零、负数；不从订单表回填 |
| order_date, due_date | ISO YYYY-MM-DD / null | 月日使用显式 reference_date 的年份；相对日期需澄清 |
| objective | min_delay / min_cost / min_defects / hybrid / null | 未说目标为 null，默认策略由业务层选择 |
| exclusion | string[] / [] | 工坊 ID；W03 → W3，BudgetWorks → W3；不会保存排除句子 |
| num_workshop_allowed | positive integer / null | 最大工坊数，不是必须使用的数量；null 在 MVP 业务层默认 1 |
| parse_status | ok / needs_clarification / invalid | 非 ok 绝不进入检索/分配 |
| missing_fields | string[] / [] | 缺订单号时包含 order_id |
| ambiguities | string[] / [] | 冲突、相对日期、暂未确认详情等诊断代码 |
| preferred_workshop | string / null | v1 保留的 Week 4 兼容字段；明确要求送往某工坊时，整单必须由其接收并满足资格 |
| deadline_required | boolean / false | v1 扩展；仅“must arrive/on time/can still make”等表达启用硬交期 |

最后两个字段在 Week 5 的 v1 中一起冻结，分别保留 R08/R11/R14/R24 的指定工坊语义、R21 的交期限制。Schema2 的计划内 10 个解析字段一一映射；扩展映射另见数据库文档。

推荐输入的完整输出：

```json
{"order_id":"ORD-045","customer":null,"product":null,"category":null,"pieces":null,"order_date":null,"due_date":null,"objective":"min_cost","exclusion":["W3"],"num_workshop_allowed":2,"parse_status":"ok","missing_fields":[],"ambiguities":[],"preferred_workshop":null,"deadline_required":false}
```

## 校验与重试

流程：模型/规则原始字符串 → 严格 JSON 解析 → 全字段/类型/枚举校验 → 数量、日期和关键约束证据校验 → 一次重试 → 终止。

拒绝重复 JSON key、额外字段、数字类型强转、无法在原文中核对的订单/数量/日期/工坊，以及明确约束被删除的输出。业务校验独立于 LLM；负数/零输出记为 invalid，拒绝值只保留在 raw telemetry。校验器不会从数据库补造字段。

日期、数量限制、目标和工坊约束采用保守的词典/规则证据校验。未涵盖的自由表达可能被拒绝或要求澄清；LLM 接口接通不等于无限制自然语言理解。金额预算、精确拆分数量、复杂否定等未支持约束会阻断已识别的请求。

JSON 错误、输出不完整、连接失败、HTTP 408/429/5xx 最多再试 1 次；配置错误、认证失败和模型拒绝不盲目重试。没有从 llm 静默退回 offline 的逻辑。每次尝试保存 `raw_output`、`validated_output`、错误代码；外层记录 prompt/schema 版本、backend、model、temperature、thinking_level（Gemini）、latency_ms、retry_count、validation_result。API Key 不进入日志。Gemini SDK 自带重试关闭（attempts=1），避免与外层 retry 叠加。SDK 客户端在解析结束时关闭。

## 模型接口与评估

`LLMBackend` 使用 Google 官方 `google-genai` SDK 的 `client.models.generate_content(model="gemini-3.5-flash", ...)`，通过 `response_mime_type="application/json"` 和 `response_json_schema` 请求结构化结果。所有字段 required，禁止 additionalProperties；nullable enum 转为等价 anyOf 供 Gemini 使用，Parser v1 原契约保持不变。实现依据 [Google 官方 Python SDK：JSON Schema](https://googleapis.github.io/python-genai/) 和 [Gemini 结构化输出说明](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)。

配置与命令见 [系统说明](docs/SYSTEM_GUIDE_CN.md)。模型固定为 `gemini-3.5-flash`，只读取 `GEMINI_API_KEY`；无需配置 Base URL。不显式设置 temperature/top_p/top_k（保留模型默认值）、thinking_level=minimal、超时由 GEMINI_TIMEOUT_SECONDS 控制（默认30秒）。其他服务商密钥和模型变量不参与选择。先激活 .venv 并安装 requirements.txt，再运行 llm 模式。

```bash
python3 -m demos.week5_mock
python3 evaluation/evaluate_parser.py --backend offline
python3 evaluation/verify_gemini_live.py --full
```

`tests/parser_golden.jsonl` 有 60 条完整 expected JSON，46 条标记 edge case。报告区分首轮/最终结构有效率、核心字段 exact match、字段 normalized match、完整样例 exact match、缺失字段补造率。Parser 错误会降低准确率，不会作为“无幻觉的成功解析”隐藏。null/空 exclusion 槽的补造率分母单独记录。

这套 expected JSON 是本次实现时编写的回归基准，尚待第二位人工复核。仅运行 offline 的成绩不能用于宣称真实 LLM 达到计划的 ≥98% / ≥90% 指标。

## Week 4 兼容

旧 dataclass/allocator/tools 保留，用于历史基线。固定样例解析器移至 `app/agent/legacy_parser.py`，由 `fake_parse_request()` 显式调用；主流程不会调用它。旧 `quantity / required_date / excluded_workshops / objective_override` 分别对应新 `pieces / due_date / exclusion / objective`。使用旧 `conversation.gate_request()` 的外部代码应继续传旧 StructuredRequest，或迁移到新 Pipeline，不能混传两个版本

### Gemini 3.5 Flash 迁移（2026-09-14）

根据用户确认，模型已从2.5 Flash改为3.5 Flash。依照[Google官方迁移说明](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5)，移除显式temperature，改用thinking_level=minimal。telemetry中的temperature=null表示采用模型默认值，不表示温度为0；minimal也不保证完全关闭思考。输出仍由固定Schema、原文证据校验和最多一次重试约束，真实准确率需重新做在线验收。
