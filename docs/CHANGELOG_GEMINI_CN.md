# Google Gemini 接入变更日志

日期：2026-09-14。此日志记录用户明确指定 Gemini 后的增量修改，路径均相对于 `Workspace/`。

## 初次接入2.5 Flash（历史记录）

当前配置以文末3.5 Flash迁移记录为准。

初次接入新增 **5** 个文件、修改 **23** 个文件、删除 **0** 个文件。

固定配置：Google Gemini Developer API / 官方 google-genai SDK 2.23.0 / gemini-2.5-flash / GEMINI_API_KEY / Google 官方默认地址。

## 新增文件

| 文件 | 内容 |
|---|---|
| `docs/CHANGELOG_GEMINI_CN.md` | 本次Gemini适配增删改明细。 |
| `evaluation/results/gemini_live_status.json` | 当前在线预检证据：NOT_RUN / gemini_api_key_missing；没有真实模型调用。 |
| `evaluation/verify_gemini_live.py` | 新增显式在线冒烟与 --full 60条真实模型验收，缺key时NOT_RUN/退出码1。 |
| `requirements.txt` | 固定 Google 官方 SDK google-genai==2.23.0；仅在线模式与SDK测试需要。 |
| `tests/test_gemini_sdk.py` | 新增10条真实SDK配合模拟HTTP的测试，验证官方URL、key、schema、限流、认证、超时、截断和关闭。 |

## 修改文件

| 文件 | 修改说明 |
|---|---|
| `.env.example` | 改为 GEMINI_API_KEY、GEMINI_TIMEOUT_SECONDS 和已固定的服务商/模型说明。 |
| `.gitignore` | 忽略本地 .venv 和线上评估输出目录。 |
| `KNOWN_ISSUES.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `README.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `README_parser.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `app/agent/llm_client.py` | 移除 OpenAI 兼容 transport，改为 Google 官方 SDK；固定模型/官方地址，仅显式读取 GEMINI_API_KEY；处理 schema、错误、超时、客户端关闭及关闭SDK重试。 |
| `app/agent/parser.py` | 记录 Gemini provider/model；解析结束关闭自己创建的SDK客户端。 |
| `app/pipeline.py` | 幂等指纹使用实际 Gemini 服务商/模型/temperature，不读取旧 LLM_MODEL。 |
| `docs/CHANGELOG_WEEK5_WEEK6_CN.md` | 更新累计变更列表，并链接本次Gemini增量日志。 |
| `docs/NEXT_STAGE_CN.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `docs/SYSTEM_GUIDE_CN.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `docs/WEEK5_WEEK6_ACCEPTANCE_CN.md` | 更新为Gemini专用安装/运行/手动配置/验收说明及待办。 |
| `docs/file_change_manifest.json` | 更新自Week4起的累计源文件SHA256；自身不递归计算hash。 |
| `docs/release_manifest.json` | 更新传输层冻结hash和Gemini配置；schema/prompt/业务校验/DB语义不变。 |
| `evaluation/results/dispatch_runs.jsonl` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/parser_offline_metrics.json` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/parser_offline_runs.jsonl` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/test_results.txt` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/verification_summary.json` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/week5_mock_demo.jsonl` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/results/week6_demo.json` | 更新此次116条测试、离线回归、demo和版本记录；并非真实LLM结果。 |
| `evaluation/verify_mvp.py` | 记录SDK版本、跳过数、已固定模型及独立在线验收入口。 |
| `tests/test_parser.py` | 更新缺少 Gemini key 的断言，并确保不使用其他服务商的 key。 |

## 删除文件

无。旧 OpenAI 兼容 transport 代码已在 llm_client.py 内替换，不保留为可选生产路径。

## 验证与边界

- 116条完整测试通过，0失败、0错误、0跳过；Google SDK专项10条使用MockTransport，不消耗线上配额。
- 60/60离线Golden、30/30原始行为、官方standard/shock基线一致。
- SDK请求已验证实际发送到Google官方地址，使用gemini-2.5-flash且请求header取自GEMINI_API_KEY，即便其他key/Vertex变量存在。
- 当前进程未配置GEMINI_API_KEY；在线预检为NOT_RUN，CLI缺key时不会继续检索或分配。
- Parser v1 schema、Prompt、rule_parser/validator和001数据库迁移hash与接入前一致。

## 环境文件

通过已批准的安装命令在 Workspace/.venv 安装SDK及依赖，未修改系统Python。该可再生环境（含大量第三方包）不逐文件纳入源码变更表；requirements.txt记录直接依赖版本。Python缓存和临时开发输出同样不计入源码清单。

运行命令及环境变量配置见 [系统说明](SYSTEM_GUIDE_CN.md)。累计变更见 [Week5/6日志](CHANGELOG_WEEK5_WEEK6_CN.md)。

## 404 故障排查增补（2026-09-14）

- 新增 `evaluation/diagnose_gemini.py`：通过官方SDK检查固定模型的查询和最小生成请求，输出已去除密钥/原始错误的诊断；不修改业务数据库。
- 修改 `docs/SYSTEM_GUIDE_CN.md`：新增404排查、200查询不等于可生成的说明，并引用Google模型访问答复。
- 修改本日志及累计变更日志/机器可读hash清单，记录以上增补。
- 当前执行进程仍无GEMINI_API_KEY，无法代替用户验证其项目访问权限；当时模型配置保持gemini-2.5-flash，随后按用户确认执行下述迁移。

## 用户确认改用 Gemini 3.5 Flash（2026-09-14）

本次模型迁移新增 **0** 个文件、修改 **24** 个文件、删除 **0** 个文件。上节诊断脚本已在模型迁移前新增，自动读取当前模型常量。

- `app/agent/llm_client.py`：模型改为 `gemini-3.5-flash`，官方SDK/URL/密钥变量保留；使用 `thinking_level=minimal`，移除显式采样参数，按Google建议采用模型默认值。
- `app/agent/parser.py`、`app/pipeline.py`：审计同步记录模型/思考级别，temperature=null表示模型默认值；幂等指纹包含新配置，旧请求ID不能用于不同模型配置。
- `tests/test_gemini_sdk.py`、`tests/test_parser.py`：验证真实SDK序列化后的3.5地址、无采样覆盖、minimal思考级别和审计字段；新增404不重试/不自动切换测试。
- README、环境变量样例、运行手册、下一阶段说明、验收表、已知问题：同步模型/参数/117条测试结果；补充停止旧服务、重启、刷新页面和使用新请求ID的步骤。
- 冻结清单及累计变更清单：更新源码SHA-256和配置；数据库/原始数据/固定Prompt/Schema未改动。
- 验证产物：重新运行本地完整验收。117/117测试通过，0跳过；离线golden60/60、原始行为30/30、官方standard/shock基线一致。11条SDK测试为模拟HTTP，不代表真实模型验收。在线预检重新记录当前模型为3.5，当前执行进程缺密钥，状态仍为NOT_RUN。

参数依据：[Google官方3.5迁移说明](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5)。保留现有 `google-genai==2.23.0`，无需再次安装或改用其他API。

完整修改文件列表（路径相对于Workspace，排除Git元数据、运行库和可再生环境）：

- `.env.example`
- `KNOWN_ISSUES.md`
- `README.md`
- `README_parser.md`
- `app/agent/llm_client.py`
- `app/agent/parser.py`
- `app/pipeline.py`
- `docs/CHANGELOG_GEMINI_CN.md`
- `docs/CHANGELOG_WEEK5_WEEK6_CN.md`
- `docs/NEXT_STAGE_CN.md`
- `docs/SYSTEM_GUIDE_CN.md`
- `docs/WEEK5_WEEK6_ACCEPTANCE_CN.md`
- `docs/file_change_manifest.json`
- `docs/release_manifest.json`
- `evaluation/results/dispatch_runs.jsonl`
- `evaluation/results/gemini_live_status.json`
- `evaluation/results/parser_offline_metrics.json`
- `evaluation/results/parser_offline_runs.jsonl`
- `evaluation/results/test_results.txt`
- `evaluation/results/verification_summary.json`
- `evaluation/results/week5_mock_demo.jsonl`
- `evaluation/results/week6_demo.json`
- `tests/test_gemini_sdk.py`
- `tests/test_parser.py`
