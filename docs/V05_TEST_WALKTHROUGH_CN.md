# v0.5 手动测试与课程演示

先启动并登录 `http://127.0.0.1:8000`。需要独立数据时，按部署指南使用新 `--db` 路径创建账号和启动；下面的接受操作会真实改变你选择的数据库。

1. 顶部依次点击 **Small / Medium / Large**，观察正文、导航、输入框和弹窗。刷新页面，字号应保留。默认 Medium 已大于 v0.4。
2. 点击 **New request**，输入 `Allocate at the lowest cost.`。应问 **Which order should I allocate?**，给出具体 ID 示例，并自动展开详情表单。Accept 不可用。
3. 在表单中选择一个 Ready 订单，比如尚未处理的 `ORD-045`。保持 Lowest cost，勾选排除 `W3`，点击 **Update recommendation**。最初导入数据下应推荐 FreshStart / W8，150 件、150 cost units、ETA 2026-04-05；队列已经变化时以当前实际结果为准。
4. 先读顶部 **Proposed — awaiting your approval** 回复。此时仅有建议，没有分配。展开 **Calculation & eligibility details**，对照摘要中的件数、工坊、日期和成本。
5. 用 **Edit details** 把目标改为 Fastest completion、最大工坊数改为 2，更新后核对 W3 排除仍保留。也可在输入框发 `exclude W6`，验证单项追加。
6. 输入一条离线模式不支持的复杂追加要求，检查提示应明确说当前模式无法应用，并引导表单；不能确认旧草稿。通过表单修改有效字段恢复推荐。
7. 点击 **Accept allocation**，回复变为 **Approved and saved**。回 Overview，**What was assigned?** 出现该订单分配摘要；再到 Allocation history 查看审批人、时间与结果，Production 查看实际分配。
8. 新开另一个请求，输入 `Allocate ORD-045 999 pieces.`，若该 ID 仍存在，字段冲突提示应告诉你登记数量；不要对已经分配的订单再次批准。选 **Use registered order details** 可消除字段冲突，但订单已分配状态仍会阻止重复分配。

DeepSeek 专项：按 [本机配置](DEEPSEEK_SETUP_CN.md) 在你自己的终端设置 Key，重启后创建新请求。输入完整请求，随后追加 `Please prioritize speed and use W6 for this order.`。观察目标与偏好变化，旧排除保留。旧 offline 会话仍使用 offline，请勿误认为重启后所有会话都会切换。

接口未配置 Key 时创建 DeepSeek 会话并发送文本，应提示 API key 配置问题；表单路径仍能工作。服务错误不能被描述为缺少订单信息，也不能显示成已批准。
