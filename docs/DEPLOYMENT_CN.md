# MVP v0.3 部署与升级说明

更新：2026-10-03。仓库：<https://github.com/zh72640/dss5105_project>，分支 `ningtao`。本版为本机运行的课程 MVP；服务绑定 `127.0.0.1`，没有账号认证及公网部署。部署目标是让团队成员从干净 checkout 启动同一套系统。

## 1. 版本与环境

| 项目 | 本版配置 |
|---|---|
| Python | 3.10+；实际完整验收环境为 macOS / 3.14.3 |
| 应用版本 | mvp_v0.3 |
| 原分配接口版本 | mvp_v0.2，保留原幂等指纹 |
| 解析 / Prompt / 会话 | parser_v1 / parser_v1 / session_v1 |
| SQLite | Python 标准库，migrations 001–003 |
| 在线依赖 | requirements.txt 固定 google-genai==2.23.0 |
| 默认模式 | offline；无需密钥即可运行功能演示 |
| 默认业务日期 | 2026-04-01，来自课程数据；不是当前系统日期 |

## 2. 干净安装

```bash
git clone --branch ningtao https://github.com/zh72640/dss5105_project.git
cd dss5105_project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python evaluation/verify_mvp.py
python -m app.server --backend offline --port 8000
```

打开 <http://127.0.0.1:8000>。离线运行本身不依赖第三方库；安装 requirements.txt 是为了在线解析和完整 SDK 模拟测试。验收脚本不调用真实模型。SDK 未安装导致测试跳过时，完整验收返回非零，不能称为全部通过。

首次启动创建 `runtime/dispatch.sqlite3`，导入 120 个订单、8 个工坊；后续启动保留已有状态。停止服务使用 `Ctrl+C`。端口被占用时改用 `--port 8001` 并同步修改浏览器地址。运行目录是 clone 后的仓库根目录，不需要额外进入 Workspace 子目录。

## 3. 升级既有 v1/v2 数据库

先停止所有使用该库的服务和 CLI 写操作，查看 `git status --short --branch`，妥善保留未提交工作；不要用 reset 或删除数据库来升级。

在旧仓库根目录运行以下备份命令。只读打开原库，写入带时间戳的独立备份，能包含 SQLite 已提交状态；原文件不变。

```bash
python3 - <<'PY'
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
backup_dir = Path('runtime/backups')
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup_path = backup_dir / ('dispatch-before-v03-' + stamp + '.sqlite3')
with closing(sqlite3.connect('file:runtime/dispatch.sqlite3?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print(backup_path)
PY
```

确认备份路径后更新代码：

```bash
git pull --ff-only origin ningtao
source .venv/bin/activate
python -m pip install -r requirements.txt
python evaluation/verify_mvp.py
python -m app.server --backend offline
```

启动时 v1 顺序应用 002/003，v2 应用 003；DDL、版本记录及旧库回填在事务内完成。v3 不重复迁移。003 只增加会话表和索引，不重新导入 CSV、不重置队列或已完工件数。迁移失败回滚；未知未来版本被拒绝。迁移测试已覆盖 v1/v2 保留数据与失败回滚。

## 4. 启动后核对

浏览器打开 `/api/health`，应看到 `version=mvp_v0.3`、`pipeline_version=mvp_v0.2`、所选 backend 和业务日期。在“生产进度”读取已有订单，确认状态、已完工数量和分配仍在。

需要查看库版本时可在另一个终端运行只读查询：

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

预期版本 3、integrity 为 ok、foreign keys 为空列表。此查询不改变业务数据，也不会触发建库或迁移。

## 5. 演示与评估

```bash
python -m demos.session_demo
python -m demos.lifecycle_demo
python -m evaluation.compare_simulator
```

两个 demo 使用各自独立临时持久库，可重复执行。模拟器输出保存在 `evaluation/results/simulator_comparison.json` 和中文报告，包含 14 组运行、24 组新策略与基线比较和逐订单结果。原始 CSV、官方 harness、Week 4 baseline 均不改动。

页面演示另开专用库：

```bash
python -m app.server --db runtime/week9-rehearsal.sqlite3 --port 8001
```

进入“多轮澄清与分配确认”，依次新建、发送 `Allocate cheapest; exclude W03.`、`ORD-045`、`改成两个工坊`，然后核对并确认。已确认的订单不能重复分配；再次彩排可用新的演示库路径或自动 demo，不删除原库。

## 6. 在线模式

在启动服务的同一终端设置 `GEMINI_API_KEY`（安全输入方法见 [操作手册](SYSTEM_GUIDE_CN.md)），再运行 `python -m app.server --backend llm`。不自动加载 .env。会话在创建时固定 backend；切换服务模式后需新建会话，已有会话仍使用其原配置。

最新真实在线证据仍为 2026-10-02：冒烟成功，全量 60 条中 46 条最终 HTTP 429，完整验收失败。本轮没有重新调用真实模型。恢复配额后先运行 `python evaluation/verify_gemini_live.py`，再按实际限额执行带间隔的 `--full`。评估等待间隔不等于生产全局限速/退避。

## 7. 恢复与回退

停止服务，保留当前运行库及其辅助文件用于诊断；将可信备份复制到一个新的恢复路径，再通过 `--db` 启动该副本。使用 v0.3 代码启动旧备份时会再次迁移。

需要回到 v0.2 代码时，可在独立 checkout 使用历史提交 `df50f64` 和升级前 v2 备份副本。不要用旧代码打开已升级 v3 库，也不要删除 schema_migrations 行伪装降级。恢复备份会舍弃备份时间之后的状态，需要先核对并保留这些变更记录。

## 8. 发布检查结果

本次验证：168 测试通过、0 跳过；60/60 离线 parser、30/30 行为回归；会话/生命周期 demo 通过；官方基线一致；14 组模拟器对比完成。Chrome 实际多轮、刷新恢复与确认验证见 [会话说明](SESSIONS_CN.md)。最新机器可读证据为 [verification_summary.json](../evaluation/results/verification_summary.json)，代码指纹见 [release_manifest.json](release_manifest.json)。
