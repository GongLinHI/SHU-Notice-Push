# TDD：日报正式发布与异常快照隔离

**对应 PRD：** [`2026-07-10-failure-snapshot-publication-policy-prd.md`](../prds/2026-07-10-failure-snapshot-publication-policy-prd.md)
**状态：已批准并实施**
**日期：2026-07-10**

## 1. 设计目标

本设计将日报运行拆为两个明确边界：

1. **Python 运行事实层：** 爬虫产生通知、失败、源站异常、DOM 巡检结果和 SQLite 状态；它只判断“本次是否具备正式发布资格”。
2. **GitHub Actions 发布编排层：** 在实际发送邮件、提交 `master`、创建异常快照分支后，记录“实际发布结果”。

这避免把 Git push 是否成功等 workflow 事实塞入 SQLite，也保证即使 Python 进程在生成 run summary 前崩溃，workflow 仍能基于 fallback 文件统一执行告警、Artifact 和异常快照。

### 设计原则

- `master` 只保存最后一次完整成功运行的正式 SQLite 基线与正式日报。
- `bot/failure-snapshots` 只保存阻断性失败的只读诊断现场，永不回流到 `master`。
- 单条通知失败是业务可恢复失败，进入人工复核和后续重试；源站级/运行级失败才阻断发布。
- 发布判定由单一、可单测的函数给出，workflow 不再在多个 `if` 表达式中重复推导。
- 所有 Git 写入均使用明确路径暂存，禁止 `git add -A`。

## 2. 目标架构

```text
notice_push CLI / Pipeline
  ├─ SQLite：通知、摘要、失败重试状态
  ├─ result Markdown（可能是部分结果）
  ├─ pipeline run summary（运行事实）
  └─ stdout：完整计数与 run_summary_path
                 │
                 ▼
GitHub Actions 发布判定器
  ├─ published / no_report / blocked
  ├─ published：正式邮件 + master 正式提交
  ├─ no_report：仅 master SQLite 提交（如有变化）
  └─ blocked：告警 + fallback summary + Artifact + failure snapshot branch + job failure
```

### 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| `notice_push.pipeline` | 抓取、摘要、SQLite 写入、生成运行事实 | Git 分支、邮件发送、Artifact |
| `notice_push.observability.publication`（新增） | 从计数与退出码判定发布资格，构造阻断原因 | 真正执行 Git/邮件命令 |
| `notice_push.observability.run_summary` | 写入 Python 运行事实 JSON | 记录 Git push 成败 |
| workflow shell helpers（新增） | 读取 stdout/JSON、构造 fallback、打包快照、Git 操作、邮件 | 重复业务判定规则 |
| `daily_report.yml` | 编排步骤、条件执行、机密注入、最终状态码 | 解析通知正文或定义重试规则 |

`publication` 模块不访问网络、不访问 SQLite，输入与输出均为不可变 dataclass，因此可在 Python 单元测试中覆盖完整决策矩阵。

## 3. 数据模型与接口设计

### 3.1 Python 发布资格与 workflow 最终判定接口

新增 `notice_push/observability/publication.py`：

```python
from dataclasses import dataclass
from enum import StrEnum


class PublicationStatus(StrEnum):
    PUBLISHED = "published"
    NO_REPORT = "no_report"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PublicationFacts:
    report_path: str
    source_error_count: int
    audit_error_count: int


@dataclass(frozen=True)
class PublicationDecision:
    status: PublicationStatus
    blockers: tuple[str, ...]
    may_send_report: bool
    may_update_master: bool
    requires_failure_snapshot: bool


def decide_pipeline_publication(facts: PublicationFacts) -> PublicationDecision:
    ...
```

判定规则固定如下：

| 条件 | `status` | `may_send_report` | `may_update_master` | `requires_failure_snapshot` |
|---|---|---:|---:|---:|
| `source_error_count > 0` | `blocked` | 否 | 否 | 是 |
| `audit_error_count > 0` | `blocked` | 否 | 否 | 是 |
| 无阻断项且 `report_path != ""` | `published` | 是 | 是 | 否 |
| 无阻断项且 `report_path == ""` | `no_report` | 否 | 是 | 否 |

`NoticePipeline` 只有在成功返回 `PipelineResult` 后才能调用该函数，因此它不能、也不应猜测 shell 进程退出码。Python 侧的阻断原因固定为 `source_error_count=<n>`、`audit_error_count=<n>`，顺序稳定。

workflow 在 Python 进程结束后调用第二个纯函数或等价 helper：

```python
@dataclass(frozen=True)
class WorkflowPublicationInput:
    raw_exit_code: int
    expected_counts_present: bool
    pipeline_decision: PublicationDecision | None


def decide_workflow_publication(input: WorkflowPublicationInput) -> PublicationDecision:
    ...
```

若原始退出码不是 `0` 或 `1`，或 stdout 缺失必需计数，则 workflow 决策覆盖为 `blocked`，首个阻断原因固定为 `pipeline_exit_code=2`。其中 `1` 仅表示当前 CLI 的“无报告”结果，必须结合 Python 资格继续判定，不得直接视为失败。

`failed_count`、`manual_review_count`、`audit_warning_count`、`refresh_seen_error_count` 均不参与该函数的阻断判断。

### 3.2 CLI 输出契约

现有 CLI 继续输出计数与可选的 `report_path`、`run_summary_path`。新增一行：

```text
publication_eligibility=published|no_report|blocked
publication_blockers=source_error_count=1,audit_error_count=1
```

约束：

- CLI 仅输出“资格”，不输出 `master_state_updated`，因为它尚未发生。
- `publication_blockers` 无内容时输出空值：`publication_blockers=`。
- CLI 未捕获异常时，workflow 必须视为 `pipeline_exit_code=2`，自行构建 fallback，而不能依赖该两行存在。

### 3.3 运行摘要 JSON 契约

`notice_push.observability.run_summary` 在现有字段基础上新增运行资格字段：

```json
{
  "schema_version": 2,
  "publication_eligibility": "blocked",
  "publication_blockers": ["source_error_count=1"],
  "report_path": "resources/results/2026-07-10.md"
}
```

字段语义：

| 字段 | 类型 | 产生方 | 说明 |
|---|---|---|---|
| `schema_version` | integer | Python | 固定为 `2`，用于识别新增发布字段 |
| `publication_eligibility` | string | Python | `published`、`no_report`、`blocked` |
| `publication_blockers` | string array | Python | 稳定排序的阻断原因；非阻断时为空数组 |
| `report_path` | string | Python | 本地 Markdown 路径；不存在时空字符串 |
| `publication_status` | string | workflow | 仅快照/Artifact 中的最终清单使用，见下节 |
| `master_state_updated` | boolean | workflow | 仅快照/Artifact 中的最终清单使用 |

为避免 workflow 重新写回或修改 Python 生成的 JSON，新增独立的 **发布清单** `publication.json`。它是 Actions 层唯一权威，不修改 `run_summary.json`。

### 3.4 发布清单 JSON

workflow 在判定为 `blocked` 后、上传 Artifact 前，于临时快照目录生成不可变的 `publication.json`。它记录本次**发布决策与已知的保证结果**，而不伪造尚未执行的 Git/邮件结果：

```json
{
  "schema_version": 1,
  "report_date": "2026-07-10",
  "workflow_run_id": "123456789",
  "workflow_url": "https://github.com/<owner>/<repo>/actions/runs/123456789",
  "trigger": "schedule",
  "git_sha": "<40-char-sha>",
  "pipeline_exit_code": 2,
  "publication_status": "blocked",
  "publication_blockers": ["pipeline_exit_code=2"],
  "master_state_updated": false,
  "report_email_sent": false,
  "alert_email_requested": true,
  "failure_snapshot_push_status": "pending",
  "failure_snapshot_branch": "bot/failure-snapshots",
  "failure_snapshot_path": "failure-snapshots/2026-07-10/run-123456789",
  "artifact_name": "notice-failure-snapshot-2026-07-10-123456789",
  "failure_detail": "",
  "counts": {
    "new_count": 0,
    "updated_count": 0,
    "retried_count": 0,
    "summarized_count": 0,
    "failed_count": 0,
    "manual_review_count": 0,
    "source_error_count": 1,
    "audit_error_count": 0,
    "audit_warning_count": 0,
    "refresh_seen_error_count": 0
  }
}
```

`master_state_updated=false` 与 `report_email_sent=false` 在 blocked 分支上是发布前即可确定的保证。`publication.json` 还需用于 `metadata.md` 生成和 Artifact 打包。若主程序未产生 run summary，字段仍完整，计数默认 `0`，且 `pipeline_exit_code`/阻断原因必须正确。

`failure_detail` 默认是空字符串。当正式 Git 发布失败时，它记录经过 URL 凭据脱敏、换行压缩和长度限制的 Git 错误摘要，并进入异常快照元数据与告警邮件；不得写入环境变量或原始凭据。

异常快照 push 执行后，workflow 将 `failure_snapshot_push_status` 作为步骤输出和告警邮件字段记录；Artifact 因必须先于 push 上传，保留 `pending` 值是预期行为。若 push 失败，告警邮件明确提示 Artifact 是唯一可用现场，workflow 最终失败。

### 3.5 SQLite 设计与边界

不新增 SQLite 表、列或迁移。

现有 `sources`、`notices` 表仍只承担爬虫业务状态：

- `sources`：三个通知源的配置镜像与启用状态。
- `notices`：目录项、正文、内容类型、媒体资产、摘要、摘要模型、失败类型、失败次数、下次重试时间。
- WAL 在 Python pipeline 结束时通过 `checkpoint()` 截断；异常快照必须在 checkpoint 之后复制 SQLite 主文件。

SQLite 复制协议：

1. pipeline 完成或异常捕获后，若 `resources/notice_state.sqlite3` 存在，使用 `sqlite3` 的 `backup` API 生成快照文件；不使用裸 `cp` 作为唯一保证。
2. 若 pipeline 在数据库初始化前崩溃，快照中省略状态库，并在 `metadata.md` 与 `publication.json` 标记 `state_snapshot_available=false`。
3. failure snapshot 分支中的 `.sqlite3` 是诊断副本，不是增量补丁，不允许恢复到 `master`。

为实现第 1 条，新增一个仅处理文件的模块或脚本接口：

```python
def backup_sqlite(source_path: Path, destination_path: Path) -> bool:
    """创建一致性 SQLite 备份；源库不存在时返回 False。"""
```

它只供 Actions 的诊断快照步骤调用，并为现有“运行前备份”提供可替换实现。

### 3.6 异常快照文件协议

目录严格为：

```text
failure-snapshots/YYYY-MM-DD/run-<GITHUB_RUN_ID>/
  metadata.md
  publication.json
  notice_pipeline.log
  run_summary.json
  notice_state.sqlite3             # 可选
  partial_report.md                # 可选
```

`metadata.md` 由模板生成，必须包含：运行时间（北京时间）、报告日期、触发方式、commit SHA、workflow URL、发布状态、阻断原因、全部计数、Artifact 名称、SQLite 是否存在。

`notice_pipeline.log` 必须是 pipeline 子进程的完整 stdout/stderr。日志写入前，workflow 对包含下列环境变量字面值的文本执行替换：`DEEPSEEK_API_KEY`、`KIMI_API_KEY`、`MAIL_PASSWORD`，替换为 `***`；不打印整个环境变量表。

### 3.7 GitHub Actions 输出接口

`Run notice pipeline` 后增加唯一的 `Evaluate publication` 步骤，向 `$GITHUB_OUTPUT` 写入：

```text
publication_status=published|no_report|blocked
publication_blockers=<逗号分隔列表>
report_exists=true|false
snapshot_path=failure-snapshots/YYYY-MM-DD/run-<id>
artifact_name=notice-failure-snapshot-YYYY-MM-DD-<id>
```

工作流所有后续条件只使用这些输出：

| 步骤 | 条件 |
|---|---|
| 渲染 HTML、发送正式日报 | `publication_status == 'published'` |
| 提交正式 Markdown + SQLite 到 `master` | `publication_status == 'published'` |
| 仅提交 SQLite 到 `master` | `publication_status == 'no_report'` |
| 生成异常目录、上传异常 Artifact、异常快照 Git push、发送异常告警 | `always() && publication_status == 'blocked'` |
| 最终退出失败 | `publication_status == 'blocked'` |

`no_report` 情况只在状态库实际有差异时提交；不得创建空 commit。

### 3.8 异常快照 Git 写入协议

在 workflow 的独立目录（建议 `$RUNNER_TEMP/failure-snapshot-repo`）执行，避免把主 checkout 的产物与临时文件混入快照：

1. 使用 `actions/checkout@v4` 的第二个 checkout，`path: .failure-snapshot-repo`、`fetch-depth: 0`；该路径位于 `$GITHUB_WORKSPACE` 内，符合 action 的 path 约束。
2. 如果远程分支存在，显式 fetch 后 checkout `bot/failure-snapshots`；否则从当前 `GITHUB_SHA` 创建 orphan 分支 `bot/failure-snapshots`，并只保留快照目录树。
3. 将 `$RUNNER_TEMP/failure-snapshot/...` 复制到该 checkout 的 `failure-snapshots/.../run-<id>`。
4. 在该 checkout 内执行保留清理：删除目录名日期早于 UTC/上海时区当前日期减 90 天的快照目录；日期格式不合法的目录不自动删除。
5. 只执行：`git add -- failure-snapshots/<日期>/run-<id>` 与已明确列出的过期目录删除；禁止 `git add -A`、`git commit -am`。
6. 若 staging 为空，视为异常并使步骤失败，因为每个 blocked 运行至少应有新快照。
7. 提交并 push 到 `origin bot/failure-snapshots`。如果冲突，fetch/rebase 一次后重试一次；第二次仍失败则记录 `failure_snapshot_push_failed=true`，告警邮件和最终状态必须反映它。

异常快照 commit：

```text
异常快照 2026-07-10: 源站异常 1 巡检异常 0 [bot]

运行 ID: 123456789
退出码: 2
阻断原因: source_error_count=1
Artifact: notice-failure-snapshot-2026-07-10-123456789
```

### 3.9 邮件接口

保留现有 `dawidd6/action-send-mail@v3`。新增/调整规则：

- 正式日报只接收 `published` 运行。
- `blocked` 运行一定尝试发送异常邮件；邮件失败不应跳过 Artifact 与快照步骤。
- 异常邮件 HTML 从 `publication.json` 与已存在的 `run_summary.json` 渲染，不直接拼接未净化的异常对象。
- 邮件显示的“日报未发布；master 正式状态未更新”由 `publication_status=blocked` 固定决定。
- 快照推送失败时邮件额外显示“异常快照分支推送失败，请从 Artifact 下载现场”。

## 4. 详细执行顺序

1. **准备：** checkout `master`，恢复正式 SQLite；记录运行前 SQLite 备份并上传成功运行/失败运行均可用的回滚 Artifact。
2. **运行：** 执行 `python -m notice_push`，始终捕获 stdout/stderr、退出码和可选 `run_summary_path`；不在该步骤直接失败 job。
3. **判定：** 调用 Python 发布资格函数或等价 CLI 子命令，优先读取 run summary；若文件不存在，使用 stdout 计数与退出码构造 `PublicationInput`。
4. **正式路径：** `published` 先生成 HTML，再显式 `git add resources/results/<date>.md resources/notice_state.sqlite3` 并提交到 `master`；`no_report` 仅显式暂存 SQLite。随后汇总 HTML 与 Git 结果形成最终发布清单，只有最终状态仍为 `published` 才发送日报邮件。
5. **阻断路径：** 使用 `always()` 构建异常目录、拷贝可用输出、以 SQLite backup API 创建状态库副本、生成 fallback run summary（必要时）与 `publication.json`、上传 Artifact、推送异常快照、发送告警邮件。
6. **收尾：** 若 `blocked`，最后单独的 `Fail blocked publication` 步骤 `exit 1`；其余状态以成功结束。

步骤 5 的 Artifact 上传必须先于异常快照 Git push：即使 Git 分支不可用，用户仍可从 Actions 下载诊断现场。

## 5. 非功能性要求

### 一致性与恢复

- 阻断运行不得改变远程 `master` 的日报、HTML 或 SQLite；本地 runner 的临时变更会随 job 结束丢弃。
- SQLite 快照必须可用 `sqlite3` 打开并通过 `pragma integrity_check`；备份失败本身是快照不完整，应作为附加阻断原因记录。
- `bot/failure-snapshots` 永不作为日常 pipeline checkout 的来源，正常运行始终 checkout `master`。
- Actions 并发组覆盖正式提交与异常快照写入，禁止同一仓库同时有两个日报任务竞争状态。

### 性能与成本

- 正常成功路径不得增加网络抓取、LLM 调用或额外源站请求。
- 阻断路径仅复制现有产物；SQLite 备份和 Artifact/快照写入目标为小于 60 秒（20 MB 状态库基线）。
- 快照保留清理为目录元数据操作，单次最多处理 200 个日期目录；超过该数量时仅记录警告并保留，避免一次 workflow 执行失控。

### 安全与隐私

- 所有 Token、API key、SMTP 密码仅通过 GitHub Secrets 注入，禁止写入日志、Artifact、Git commit、JSON 或 Markdown。
- 因异常快照含正文和链接，仓库必须保持私有；若未来改为公开仓库，本功能默认禁用并在 workflow 中失败提醒。
- GitHub Token 最小权限仍为 `contents: write`；不新增 PAT、部署密钥或跨仓库凭据。

### 可维护性

- 发布判定、JSON 生成、SQLite 备份使用 Python 模块实现并单元测试；workflow 仅保留输入/输出粘合和 GitHub 特有命令。
- shell 片段集中在一个受版本控制的 `scripts/workflow/` 目录，避免在 YAML 内维护超过 30 行的业务 shell；脚本接收显式路径与环境变量，不依赖当前目录隐式状态。
- 所有新增 JSON 采用 `schema_version`，兼容读取旧的 run summary（缺失发布字段时按当前计数重新计算资格）。

## 6. 测试设计与验收

### 6.1 Python 单元测试

新增 `tests/notice_push/test_publication.py`：

- 退出码 2、源站异常、巡检异常分别阻断；多阻断项顺序稳定。
- 无阻断且有报告为 `published`；无报告为 `no_report`。
- 单条通知失败、人工复核、巡检警告、正文刷新失败不改变发布资格。
- run summary v2 正确携带资格与阻断数组；旧 summary 缺字段时读取兼容。
- SQLite backup 对存在数据库生成可通过 `pragma integrity_check` 的副本；源文件不存在返回 `False`；目的路径父目录自动创建。

扩展 `tests/notice_push/test_cli.py`：

- 正常运行输出资格与空阻断原因。
- 源站异常输出 `publication_eligibility=blocked` 与对应原因。
- 未捕获异常不要求 CLI 输出，但测试应定义 workflow fallback 的输入约束。

### 6.2 Pipeline 集成测试

扩展 `tests/notice_push/test_pipeline.py`：

- 已存在的源站异常/巡检异常测试额外断言 run summary 的资格字段。
- 单条详情/摘要失败仍生成报告且资格为 `published`。
- 报告为空、无阻断时资格为 `no_report`。
- 运行后 SQLite checkpoint 后，备份 API 产生的快照可读。

### 6.3 Workflow 静态与行为测试

扩展 `tests/scripts/test_ci_workflow.py`，以文本断言保护以下行为：

- 存在唯一 `Evaluate publication` 步骤，并输出 `publication_status`、`publication_blockers`、`snapshot_path`、`artifact_name`。
- 正式日报/HTML/`master` 提交只依赖 `published`；`no_report` 仅提交 SQLite。
- 所有 blocked 处理步骤带 `always()` 和 `publication_status == 'blocked'`。
- 使用独立 checkout/worktree 操作 `bot/failure-snapshots`，使用显式 `git add -- failure-snapshots/...`，不存在 `git add -A` 或 `git commit -am`。
- Artifact 先于异常快照 push；最后才存在 `exit 1`。
- 成功 bot commit 保留中文标题与中文指标正文。

新增可运行的 workflow helper 测试（使用临时目录，不访问 GitHub）：

- pipeline 未生成 JSON 时生成的 fallback `publication.json` 包含正确的退出码、阻断原因和零值计数。
- 部分报告、日志与 SQLite 被打包到正确的快照目录；缺失 SQLite 时生成可读 metadata 而不崩溃。
- 日志脱敏不泄露传入的模拟 Secret。
- 90 天边界清理仅删除格式正确、早于阈值的目录，不删除当前 run 或格式异常目录。

### 6.4 GitHub Actions 手工验收

在非生产的 `workflow_dispatch` 测试入口中通过受控环境变量模拟三类结果；模拟开关必须只允许仓库 Owner 手动触发，默认关闭，且不得影响定时运行：

1. 正常有报告：确认正式邮件/提交走 `master`，无失败快照。
2. 模拟 `source_error_count=1`：确认没有正式邮件或 `master` 提交，异常邮件、Artifact、快照 commit 与红色 job 全部出现。
3. 模拟单条人工复核：确认仍发布日报，快照分支不变化。

完成后删除或禁用模拟输入，保留测试记录链接在 PR 描述中。

### 6.5 最终验证命令

```powershell
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q notice_push scripts
conda run --no-capture-output -n spider python -m notice_push --doctor --state-path .tmp\publication-doctor.sqlite3
git diff --check
```

## 7. 迁移与发布顺序

1. 先引入并测试 Python 发布资格模块、run summary v2、SQLite 备份与 workflow helper，不改变 `daily_report.yml` 的发布条件。
2. 更新 workflow，先以只记录资格和 Artifact 的“观察模式”运行一次手动 dispatch，确认输出与现有计数一致。
3. 启用阻断路径、异常快照分支和最终失败状态。
4. 在首次成功与首次阻断运行后，核对 `master`、Artifact、`bot/failure-snapshots` 的内容和邮件文案。
5. 在 90 天后验证清理任务；清理失败不能删除当前快照，必须保留并告警。

## 8. 明确默认值

- 异常快照分支：`bot/failure-snapshots`。
- Artifact 保留：30 天。
- Git 快照保留：90 天，可配置。
- 阻断条件：`pipeline_exit_code=2`、`source_error_count>0`、`audit_error_count>0`。
- 非阻断条件：单条通知失败、人工复核、巡检 warning、已见通知刷新失败。
- 主分支：`master`；正式状态从不从快照分支恢复。
- 快照写入失败：workflow 保持失败，Artifact 和异常邮件仍尽力保留；不重试超过一次 Git rebase/push。
