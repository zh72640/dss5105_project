# MVP v0.4 部署与升级说明

更新：2026-10-06。仓库：<https://github.com/zh72640/dss5105_project>，分支 `ningtao`。这是本机课程 MVP，服务绑定 `127.0.0.1`。本轮提供账号登录与审批身份，所有账号共享同一工作区；没有公网托管、角色/租户权限或 HTTPS 终止配置。

## 1. 环境和版本

| 项目 | 配置 |
|---|---|
| Python | 3.10+，已验证 3.14.3 |
| 应用 | mvp_v0.4 |
| 数据库 | SQLite，migrations 001–004 |
| Parser / Prompt / Session | parser_v1 / parser_v1 / session_v1 |
| 原分配 Pipeline | mvp_v0.2，未传 actor 的旧调用保留原指纹 |
| 默认模式 | offline，无需 Python 第三方库 |
| 在线依赖 | google-genai==2.23.0，见 requirements.txt |
| UI | 原生 HTML/CSS/JavaScript，无 npm 构建步骤 |
| 前端测试 | 可选 Node 18+，不影响应用运行 |
| 默认业务日期 | 2026-04-01 |

## 2. 干净安装与登录

```bash
git clone --branch ningtao https://github.com/zh72640/dss5105_project.git
cd dss5105_project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 交互输入密码，两次一致，至少 12 字符
python -m app.auth dispatcher
python -m app.server --backend offline --port 8000
```

打开 <http://127.0.0.1:8000>，使用 dispatcher 和自己刚才设置的密码登录。账号创建会初始化同一个默认数据库。没有公共默认账号/密码，密码不会作为 CLI 参数、环境变量或日志输出。离线使用可省略 pip 安装；完整 SDK 模拟测试需要安装 requirements.txt。

默认数据库为 `runtime/dispatch.sqlite3`。首次导入 120 个订单、8 个工坊，其中 86 个订单已完工，34 个待分配；后续启动不会重新导入。停止服务用 `Ctrl+C`。

指定其他数据库时，账号和服务器必须使用同一条 `--db`：

```bash
python -m app.auth presenter --db runtime/ui-demo.sqlite3
python -m app.server --db runtime/ui-demo.sqlite3 --port 8001
```

该模式适合课程演示，不影响日常运行库。纯本机、无登录的临时演示可显式启动 `python -m app.server --db runtime/anonymous-demo.sqlite3 --port 8002 --no-auth`；页面显示 Local demo，不能将其审批身份视为实名。正常部署使用默认登录模式。

## 3. 从 v0.3 或更早版本升级

先停止所有使用该库的 HTTP/CLI 写操作，保留未提交 Git 工作。**创建账号也会触发数据库升级，因此务必先备份。**

在旧仓库根目录运行：

```bash
python3 - <<'PY'
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
backup_dir = Path('runtime/backups')
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup_path = backup_dir / ('dispatch-before-v04-' + stamp + '.sqlite3')
with closing(sqlite3.connect('file:runtime/dispatch.sqlite3?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print(backup_path)
PY
```

核对备份路径后：

```bash
git pull --ff-only origin ningtao
source .venv/bin/activate
python -m pip install -r requirements.txt
python evaluation/verify_mvp.py
python -m app.auth dispatcher
python -m app.server
```

v3 只应用 004，增加 desk_users、login_sessions、request_actors；不修改 orders、working_order、队列或已保存的会话内容。v1/v2 会按顺序应用缺失迁移。DDL 和版本登记在事务内完成，失败回滚，未知未来版本拒绝打开。旧迁移 001–003 保持原文。

新版 `/api/health`、静态页面和 `/api/auth/me` 可公开读取；业务读取、写入和导出默认均需登录。旧脚本必须登录取得 Cookie，或者在独立本机演示环境明确使用 `--no-auth`。原 `/api/requests` 仍是直接分配接口；新英文 UI 的主流程只使用会话预览与确认。旧中文界面地址变为 `/legacy`，建议先从 `/` 登录再打开。

旧客户端如有升级前未确认响应的请求，先查询历史和订单状态。带认证的 HTTP 写入现在绑定 actor，旧请求 ID 的指纹可能不同；不要为解决冲突盲目生成新 ID 再提交。

## 4. 账号维护

为每位需要在同一工作区操作的人创建不同用户名：

```bash
python -m app.auth team_member
```

再次对同一用户名执行该命令会重设密码，并撤销此用户全部登录。用户名允许 1–64 个英文字母、数字、点、下划线或连字符；密码 12–256 字符。数据库保存带随机盐的密码哈希，不保存明文。

登录有效期 8 小时；退出会撤销服务器会话，浏览器页面也清理当前账号本地状态。服务进程在 60 秒内最多允许 10 次登录尝试，超过后等待一分钟。此限速只针对登录，不等于 Gemini 全局限速。后台没有找回密码邮件、注册页面或角色管理，忘记密码在拥有该本机数据库权限的终端通过上述命令重设。

## 5. 启动后检查

打开 `/api/health`，应显示 `version=mvp_v0.4`、`pipeline_version=mvp_v0.2`、backend 与业务日期。登录后核对 Overview、已有订单和会话，确保数据仍在。

只读数据库检查：

```bash
python3 - <<'PY'
import sqlite3
from contextlib import closing
with closing(sqlite3.connect('file:runtime/dispatch.sqlite3?mode=ro', uri=True)) as db:
    print('schema version:', db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0])
    print('integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])
    print('foreign keys:', db.execute('PRAGMA foreign_key_check').fetchall())
PY
```

预期 version 4、integrity `ok`、foreign keys `[]`。此检查不会初始化或升级数据库。

## 6. 验证与课程演示

```bash
python evaluation/verify_mvp.py
python evaluation/verify_ui.py
node --test tests/test_ui_state.cjs
```

完整 Python 验收使用模拟的 SDK，不调用真实模型。测试跳过不能称为全部通过。性能验证和演示脚本使用独立临时库；验收产物写入 `evaluation/results/`。

当前证据为 181 个 Python 测试、5 个前端控制器测试通过。离线 HTTP 延迟样本全部小于 3 秒。浏览器及移动端检查边界见 [验收记录](UI_ACCEPTANCE_CN.md)。五分钟演示步骤见 [UI 操作指南](UI_GUIDE_CN.md)。

## 7. Gemini 模式

在启动服务的终端安全设置 `GEMINI_API_KEY`，再运行 `python -m app.server --backend llm`。不自动读取 .env。模型和官方地址已固定；会话创建时固定 backend，切换解析模式后需新建会话。

最新真实在线结果仍为 2026-10-02：冒烟成功，完整 60 条中的 46 条最终 HTTP 429，未通过全量验收。本轮没有调用真实模型，也不承诺在线响应小于 3 秒。配额恢复后先运行 `python evaluation/verify_gemini_live.py`，再根据实际限额执行带间隔的 `--full`，不要反复无间隔请求。

## 8. 备份、恢复与回退

日常备份也可用第 3 节 SQLite backup 方法，修改输出文件名前缀即可。备份现在同时包含账号哈希和登录 token 哈希，应像业务数据一样妥善保管，不提交 Git。

恢复时停止服务，保留当前库，将可信备份复制到新的恢复路径，通过 `--db` 启动该副本。恢复后建议用 `app.auth` 重设需要继续使用的账号密码，以撤销备份中的旧登录。

回退到 v0.3 时，在独立 checkout 使用 `6b5244c` 与升级前 v3 备份副本。不要让旧代码打开 v4 数据库，也不要删除 migration 行伪装降级。恢复升级前备份会舍弃备份之后的新审批和生产操作，应先保存这些记录。

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| 页面提示账号未设置 | 确认 app.auth 与 app.server 的 `--db` 路径一致 |
| 旧 API 脚本返回 401 | 使用登录 Cookie；无认证演示只能显式开启 `--no-auth` |
| 登录失败或 429 | 核对账号/库，必要时重设密码；超过频率限制等待一分钟 |
| 测试不能绑定端口 | 允许本机回环端口；不要将权限错误当成功或跳过 |
| Request 尚未确认 | 保持输入不变，点击 Retry safely，保留原请求 ID |
| 版本冲突 | 重新读取当前订单/会话，核对后再操作 |
| 端口占用 | 更换 `--port` 并同步浏览器地址 |
| 页面显示旧版本 | 重启服务并刷新，确认 `/api/health` 版本及访问端口 |
