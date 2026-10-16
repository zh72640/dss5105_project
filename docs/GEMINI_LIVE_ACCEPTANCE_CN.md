# Gemini 首次在线验收记录

日期：2026-10-02。沿用已指定的 Google Gemini / gemini-3.5-flash / 官方 SDK 和 GEMINI_API_KEY；密钥未写入代码、文档或提交。

## 结论

真实端到端冒烟成功，订单分配和同 key 重放通过；完整 60 条评估结果为 **ACCEPTANCE_FAILED**。原“缺少密钥、未调用真实模型”的记录已由此次证据更新，但不能将其写成在线质量验收通过。

| 指标 | 结果 |
|---|---|
| 完整匹配 | 14 / 60 |
| 首次通过解析校验 | 9 / 60，15% |
| 最终通过解析校验 / 核心字段匹配 | 14 / 60，23.33% |
| 最终错误 | 46 条 gemini_http_429 |
| 所有尝试中的服务错误 | 91 次 HTTP 429，6 次 HTTP 503 |
| 收到模型输出的用例 | 14 条，均通过字段核对 |
| 有效结果中的缺失字段补造 | 0 / 549 个评估缺失槽；大量用例未收到结果，不构成零补造能力证明 |

完整指标：[parser_llm_metrics.json](../evaluation/results/parser_llm_metrics.json)；状态：[gemini_live_status.json](../evaluation/results/gemini_live_status.json)。raw/validated 明细保留在本地已忽略的 `evaluation/live_results/`，不提交凭据或原始服务错误体。此次记录来自生命周期修改前的 v0.1 在线运行，Parser/Prompt/模型参数与 v0.2 相同。

当前失败的直接证据是服务限流；仅凭 HTTP 429 不能区分分钟配额、每日配额或服务容量，也不能据此断言解析准确率只有 23.33%。验收仍按全部 60 条计入分母，不剔除服务失败来提高成绩。

## 本次补充

- 评估报告增加最终错误数、每次尝试的错误数及实际收到模型输出的用例数。
- 统一 `live_llm_validated` 与计划阈值：首次有效率 ≥98%、核心字段 ≥90%、观测补造为零。
- 新增 `--interval-seconds`（0–60 秒），供根据项目配额控制评估速度；默认 0 保留原行为。它只控制用例之间的等待，不改变 Parser 最多一次重试的既有规则，不保证消除配额不足。
- 新增模拟限流和非法间隔的测试，确保服务失败不会从验收分母中消失。

## 下一步

1. 在 Google 项目中确认可用配额及 HTTP 429 原因，必要时等待配额恢复。
2. 先执行 `python evaluation/verify_gemini_live.py`，成功后再依据配额运行完整回归，例如：

   ```bash
   python evaluation/verify_gemini_live.py --full --interval-seconds 10
   ```

3. 将新运行放到独立输出目录保留本次失败基线；按完整指标判断是否通过，记录配置和时间。
4. 若仍大量 429，优先补充运行配置的有界退避/请求限速，保持失败不进入分配器；不要改 expected 标签来掩盖服务失败。
5. 由第二位团队成员复核标签，再另建未参与调试的 holdout 集。此次只是既有开发集回归。
