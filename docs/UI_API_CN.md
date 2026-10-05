# MVP v0.4 UI HTTP 契约

本机服务地址默认 `http://127.0.0.1:8000`，所有写接口只接受 `application/json`，拒绝不匹配的 Origin。除静态资源、health、auth/me 和 login 外，默认需登录。账户共享全部工作区数据，没有逐用户订单授权。

## 登录

| 方法与地址 | 输入 / 返回 |
|---|---|
| GET `/api/auth/me` | username、auth_required、setup_required；未登录 username 为 null |
| POST `/api/auth/login` | JSON 仅 username、password；成功返回 username 并设置 HttpOnly/SameSite=Strict Cookie |
| POST `/api/auth/logout` | JSON `{}`；删除服务器 token，清除 Cookie |
| GET `/api/health` | status、backend、as_of_date、version、pipeline_version |

登录会话 8 小时，账号通过 `python -m app.auth USERNAME --db PATH` 创建/重设。登录失败返回 401；每服务进程 60 秒超过 10 次尝试返回 429。无账号不自动开放业务权限。`--no-auth` 显式演示模式使用 local-demo，非实名认证。

## 查询

| 方法与地址 | 主要字段与行为 |
|---|---|
| GET `/api/dashboard` | stats、inbox、orders、workshops、business_date、audit_date_utc |
| GET `/api/workshops?q=&status=&category=` | items、business_date；q 名称/ID 子串，status/category 精确匹配 |
| GET `/api/audit?q=&status=&page=1&page_size=25` | items、total、page、page_size；q 订单/请求 ID 字面子串；page_size 1–100 |
| GET `/api/audit/{request_id}` | 单个完整决策条目；不存在返回 404 |
| GET `/api/audit/export?format=json` | 所有条目，忽略筛选和分页；下载 JSON |
| GET `/api/audit/export?format=csv` | 所有条目，CSV 带 UTF-8 BOM，潜在公式单元格加单引号 |
| GET `/api/sessions/{session_id}` | 保持既有会话契约，含 messages 与 last_response |
| GET `/api/orders/{order_id}` | 保持既有生命周期快照契约 |
| GET `/api/history` | 兼容旧页面的最近 30 条简略历史；新页面使用 audit |

audit 条目包含 request_id、session_id、order_id、status、timestamp、original_message、message_time、turn_message、parsed、result、actor、approved、approved_by、approval_timestamp、trace。会话原文取第一条用户消息；本回合内容在 turn_message。成功 ALLOCATE/REASSIGNED 是 approved；没有 actor 的历史保持 null。result 保存实际决定，trace 保留订单与队列等依据。

workshop 条目包含 workshop_id、name、capacity、lead_days、defect_rate、cost、makes、status、max_batch、queue_days、notes、orders。orders 只列仍有未完工件数的工作分配，含 order_id、remaining_pieces。

stats.pending 为可处理开放会话及没有开放会话代表的待分配订单数；clarification 为有回合且待澄清的会话数；allocated_today 为当前 UTC 日 ALLOCATE 的不同订单数；lapsed/assigned/unallocated_orders 为当前订单状态计数。它们不是同一个计数实体，不能直接相加当作所有订单数。

## 草稿与确认

创建：`POST /api/sessions`，可传 session_id 和 objective。配置 backend、as_of 由服务端固定，不能在 JSON 覆盖。

回合：`POST /api/sessions/{id}/turns`：

```json
{
  "request_id": "unique-turn-id",
  "expected_version": 0,
  "action": "message",
  "message": "Allocate ORD-045."
}
```

action 为 message、replace、confirm、close。confirm/close 的 message 必须为空；只有 confirm 且 result.success 才 committed=true。拒绝采用 message=`Reject recommendation`，产生 RECOMMENDATION_REJECTED 阻断，后续有效修订解除。同一会话不能换订单。

客户端不得提交 actor，服务端从登录态注入。带 actor 的幂等指纹绑定身份，actor 审计、会话和业务改变在同一事务保存。409 包括版本冲突、关闭会话或幂等冲突；503 保存失败可沿用原 ID 重试；200 中仍可能是 CLARIFY/REFUSE 等业务结果，调用方必须检查 result/committed。

原 `POST /api/requests` 直接分配接口仍可用，登录后由服务端注入 actor。`POST /api/events` 保持旧 payload，认证模式覆盖其中 actor 为登录用户名。客户端不能把 UI 新增登录理解为对本机 CLI/数据库文件权限的限制。

## 兼容及错误处理

未知字段返回 400，JSON 类型错误返回 400，跨 Origin 写入返回 403，不支持的 Content-Type 返回 415，非法请求大小返回 413。默认服务的业务访问未登录返回 401。静态文件采用固定白名单，不开放任意路径读取。

旧客户端如需继续无认证访问，只能显式选择本机演示模式，或增加 Cookie 登录。不要把原 `api/history` 的 30 条限制用于新导出，也不要在网络失败时为同一未知结果创建新请求 ID。
