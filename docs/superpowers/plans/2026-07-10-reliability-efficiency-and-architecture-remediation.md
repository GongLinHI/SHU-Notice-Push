# 运行可靠性、抓取效率与代码职责治理实施计划

> **供执行型智能体使用：** 执行本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项完成并维护复选框状态。

**目标：** 修复日报正式发布、异常告警与失败快照的失效路径；消除生产配置双来源和重复逻辑；降低重复抓取成本；将持续膨胀的 Pipeline、存储、解析和 LLM 代码拆为职责清晰、可独立测试的模块。

**架构：** 将一次运行拆为“初始运行判定”“正式状态写入”“最终发布判定”三个阶段。工作流只编排显式输入、输出与 GitHub Actions 专属步骤；发布清单、Git 发布、快照构建、重试策略、配置校验等可测试逻辑移入 Python 模块。抓取侧以单次运行缓存复用巡检与正式抓取的成功响应，配置侧以 `runtime.yml` 为唯一生产行为来源。

**技术栈：** Python 3.12、pytest、requests、SQLite、PyYAML、GitHub Actions、Git、Pandoc。

---

## 0. 执行边界与完成标准

### 0.1 当前工作区约束

- 本计划以当前未提交的“日报正式发布与异常快照隔离”实现为基线，不覆盖、不回退其中任何用户现有改动。
- 当前阶段仅创建本计划；后续实施前需要用户再次批准。
- 执行阶段默认不自动提交、不推送。由于当前工作区已有未提交的功能改动，只有在用户明确授权并确认暂存范围后，才创建 Git 提交。
- 所有 Python 验证使用 `conda run --no-capture-output -n spider ...` 串行执行，避免 Windows 上并发 `conda run` 的临时文件锁竞争。
- 生产源站的选择器发生修改时，先运行本地 fixture 测试；只有 fixture 无法解释真实页面变化时，才使用本机 Google 浏览器的 Playwright MCP 采集最小必要页面结构，不将登录态、Cookie、密钥或完整敏感网页保存到仓库。

### 0.2 完成定义

1. 任意 pipeline、发布判定、HTML 渲染或正式 Git 推送失败，都不会发送正式日报，也不会把本次状态写入远程 `master`。
2. 上述失败都能生成最小 `publication.json`、Artifact、脱敏日志、异常告警邮件，并尝试写入 `bot/failure-snapshots`；快照推送失败时，Artifact 仍存在且告警明确说明。
3. `runtime.yml` 是通知源、LLM、路由、profile、解析和媒体限制的唯一生产配置；代码不再内置三个真实源站和生产 profile 数值作为静默回退。
4. 单次日报中，同一 URL 的成功文本响应最多请求一次；HTTP 不再对不可恢复的 4xx 进行盲目重试。
5. `pipeline.py`、`storage/database.py`、`parsing/html.py`、`llm/kimi.py` 的职责被拆分，且行为由回归测试锁定；不保留仅为旧入口服务的冗余 API。
6. 全量测试、编译检查、doctor、工作流静态检查和 Git 差异检查均通过。

### 0.3 批次依赖

| 批次 | 目标 | 依赖 | 完成后的独立价值 |
|---|---|---|---|
| 批次一 | 发布、快照、告警链路可靠 | 无 | 任何运行异常都可诊断，正式状态不被错误发布 |
| 批次二 | 配置单一来源与抓取效率 | 批次一 | 新增源站和调参无需修改 Python，减少重复网络请求 |
| 批次三 | 模块职责治理与持续质量 | 批次二 | 后续增加来源、模型、媒体类型时修改范围可控 |

## 1. 目标文件与职责边界

| 文件 | 最终职责 |
|---|---|
| `notice_push/observability/publication.py` | 纯发布资格规则：基于计数和退出码得出 `published`、`no_report`、`blocked` |
| `notice_push/observability/publication_manifest.py` | 不可变的 workflow 发布清单、严格 JSON 校验、序列化与 fallback 构造 |
| `notice_push/observability/failure_snapshot.py` | 只构建脱敏诊断目录和有上限的日期保留清理，不执行 Git 命令 |
| `scripts/workflow/evaluate_publication.py` | 从 pipeline 日志创建初始发布候选，不负责 GitHub 输出的最终可靠性 |
| `scripts/workflow/finalize_publication.py` | 汇总初始判定、渲染结果和正式 Git 写入结果，写入唯一的最终 `publication.json` 与 `$GITHUB_OUTPUT` |
| `scripts/workflow/write_blocked_publication_fallback.py` | 仅依赖 Python 标准库；当判定器异常时强制写入完整 `blocked` 输出和最小清单 |
| `scripts/workflow/publish_master.py` | 显式暂存、中文提交消息、push 正式 `master` 状态，输出可判定结果 |
| `scripts/workflow/publish_failure_snapshot.py` | 在独立 checkout 中初始化/更新快照分支、清理、提交、一次 rebase 重试 |
| `notice_push/settings/loader.py` | 严格读取和校验 YAML，不提供真实生产配置回退 |
| `notice_push/sources/selection.py` | 唯一的启用源/指定源选择规则与未知 source 错误 |
| `notice_push/http_cache.py` | 单次运行、线程安全、只缓存成功 `get_text` 结果的包装器 |
| `notice_push/http_retry.py` | HTTP 可重试状态、`Retry-After` 解析与退避延迟计算 |
| `notice_push/crawler/source_scan.py` | 目录翻页、去重、lookback 截断、源站级错误收集 |
| `notice_push/crawler/notice_processing.py` | 新通知、失败重试、正文更新、详情抓取和摘要候选协调 |
| `notice_push/storage/selection.py` | 批量读取和分类 SQLite notice 状态，避免逐条查询 |
| `notice_push/parsing/content.py`、`assets.py`、`pdfjs.py`、`dates.py` | 分别处理正文、资源、PDFJS 和日期解析 |
| `notice_push/llm/registry.py` | provider kind 到构造器的注册表 |
| `notice_push/llm/summary_format.py` | 通用的摘要格式规范化、校验与修复循环 |

## 2. 批次一：发布、快照与告警可靠性

### Task 1：建立最终发布清单的强类型契约

**目的：** 取代 `Mapping[str, object]` 和散落的 `dict.get`，让快照、告警、最终 workflow 输出使用同一份可验证数据。

**文件：**
- 新建：`notice_push/observability/publication_manifest.py`
- 修改：`notice_push/observability/failure_snapshot.py`
- 修改：`scripts/workflow/evaluate_publication.py`
- 新建：`tests/notice_push/test_publication_manifest.py`
- 修改：`tests/notice_push/test_failure_snapshot.py`
- 修改：`tests/scripts/test_evaluate_publication.py`

- [x] **Step 1：先写失败测试，定义完整清单的最小合法形态。**

```python
def test_publication_manifest_round_trips_and_rejects_missing_counts():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
    )

    restored = PublicationManifest.from_json(manifest.to_json())

    assert restored.status is PublicationStatus.BLOCKED
    assert restored.counts.source_error_count == 0
    with pytest.raises(ValueError, match="counts"):
        PublicationManifest.from_json({"schema_version": 1})
```

- [x] **Step 2：运行目标测试，确认失败原因是类型尚不存在。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_publication_manifest.py -q
```

预期：测试收集失败，提示 `PublicationManifest` 不存在。

- [x] **Step 3：实现不可变 manifest、计数值对象和严格解析。**

在 `publication_manifest.py` 定义以下接口；JSON 只接受已声明字段类型，缺失计数统一按 fallback 路径显式补零，普通反序列化不得静默吞掉字段错误：

```python
@dataclass(frozen=True)
class PublicationCounts:
    new_count: int = 0
    updated_count: int = 0
    retried_count: int = 0
    summarized_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0
    source_error_count: int = 0
    audit_error_count: int = 0
    audit_warning_count: int = 0
    refresh_seen_error_count: int = 0

@dataclass(frozen=True)
class PublicationManifest:
    report_date: str
    workflow_run_id: str
    workflow_url: str
    trigger: str
    git_sha: str
    pipeline_exit_code: int
    status: PublicationStatus
    blockers: tuple[str, ...]
    counts: PublicationCounts
    master_state_updated: bool
    report_email_sent: bool
    alert_email_requested: bool
    failure_snapshot_push_status: str
    failure_snapshot_branch: str
    failure_snapshot_path: str
    artifact_name: str

    def to_json(self) -> dict[str, object]: ...
    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "PublicationManifest": ...
    @classmethod
    def blocked_fallback(cls, ..., blocker: str) -> "PublicationManifest": ...
```

将 `FailureSnapshotContext.publication` 改为 `PublicationManifest`。`build_failure_snapshot`、`metadata.md`、fallback `run_summary.json` 全部通过 manifest 的属性访问，不再通过任意 Mapping 读取。

- [x] **Step 4：让初始判定器只创建候选 manifest。**

将 `evaluate_publication.py` 的输出职责改为写入 `--candidate-publication-json`。保留 `evaluate_pipeline_output()` 作为纯函数；候选 manifest 的状态只能来自 pipeline 日志与原始退出码，`master_state_updated=False`、`report_email_sent=False` 是初始已知事实。

- [x] **Step 5：运行模块测试与现有快照测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_publication_manifest.py tests/notice_push/test_failure_snapshot.py tests/scripts/test_evaluate_publication.py -q
```

预期：全部通过。

### Task 2：实现判定器失败时必定产出 `blocked` 的兜底路径

**目的：** 无论 `evaluate_publication.py` 是导入失败、日志不可读、候选 JSON 损坏还是输出写入失败，后续步骤都能得到 `publication_status=blocked` 和完整最小清单。

**文件：**
- 新建：`scripts/workflow/write_blocked_publication_fallback.py`
- 新建：`scripts/workflow/finalize_publication.py`
- 修改：`.github/workflows/daily_report.yml`
- 新建：`tests/scripts/test_finalize_publication.py`
- 修改：`tests/scripts/test_failure_snapshot_workflow_helpers.py`
- 修改：`tests/scripts/test_ci_workflow.py`

- [x] **Step 1：为候选缺失、候选损坏和初始判定器非零退出写失败测试。**

```python
def test_finalize_publication_emits_blocked_fallback_when_candidate_is_missing(tmp_path):
    result = finalize_publication(
        candidate_path=tmp_path / "missing.json",
        metadata=WorkflowMetadata.for_test(),
        render_html_outcome="skipped",
        master_publish_outcome="skipped",
    )

    assert result.manifest.status is PublicationStatus.BLOCKED
    assert "publication_evaluator_failed" in result.manifest.blockers
    assert result.outputs["publication_status"] == "blocked"
```

- [x] **Step 2：实现标准库独立 fallback helper。**

`write_blocked_publication_fallback.py` 只能依赖 `argparse`、`json`、`pathlib` 和 `os`。它接收报告日期、run ID、workflow URL、trigger、SHA、pipeline 原始退出码、失败阶段和输出路径，覆盖损坏的 manifest，并向 `$GITHUB_OUTPUT` 写入所有下游必需键：

```text
publication_status=blocked
publication_blockers=publication_evaluator_failed
report_exists=false
report_path=
run_summary_path=
pipeline_exit_code=2
snapshot_path=failure-snapshots/YYYY-MM-DD/run-ID
artifact_name=notice-failure-snapshot-YYYY-MM-DD-ID
# 所有十个计数均为 0
```

- [x] **Step 3：实现 `finalize_publication.py`。**

该脚本读取候选 manifest，并结合以下结果得出唯一最终 manifest：

```python
def finalize_publication(
    candidate: PublicationManifest | None,
    *,
    render_html_outcome: str,
    master_publish_status: str,
    master_state_updated: bool,
) -> PublicationManifest:
    """将候选状态收敛为最终发布状态，不执行 Git 或邮件。"""
```

收敛规则：

- 候选缺失或无效：`blocked`，原因 `publication_evaluator_failed`。
- 候选已是 `blocked`：保持其 blocker 与计数。
- 候选 `published` 且 HTML 渲染未成功：`blocked`，原因 `html_render_failed`。
- 候选 `published`/`no_report` 且正式 Git 发布未成功：`blocked`，原因 `master_publish_failed`。
- 其他情况：保持候选状态，并使用 `master_state_updated` 的真实值。

最终器必须覆盖写入 `$RUNNER_TEMP/publication.json`，然后才写 `$GITHUB_OUTPUT`。这保证 Artifact、告警和快照读取的是同一份最终事实。

- [x] **Step 4：重排工作流为“初始判定 -> 正式准备/提交 -> 最终判定”。**

在 `daily_report.yml` 中：

1. 将现有 `Evaluate publication` 改为 `Evaluate initial publication`，`id: initial_publication`，以 `continue-on-error: true` 写候选文件，不直接作为后续唯一条件。
2. 新增 `Finalize publication`，`id: publication`，`if: always()`；它调用 `finalize_publication.py`。
3. 用窄范围的 shell wrapper 包裹最终器：若最终器非零退出、未生成合法 JSON 或未写入 `publication_status`，立即调用 `write_blocked_publication_fallback.py`，wrapper 自身 `exit 0`。
4. 之后所有正式路径只判断 `steps.publication.outputs.publication_status`；所有异常路径只判断 `always() && ... == 'blocked'`。

- [x] **Step 5：运行目标测试与 workflow 静态测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/scripts/test_finalize_publication.py tests/scripts/test_failure_snapshot_workflow_helpers.py tests/scripts/test_ci_workflow.py -q
```

预期：候选缺失、损坏、helper 异常和正常候选均产生确定的最终输出。

### Task 3：将正式 `master` 发布变为可判定、可恢复的 Python helper

**目的：** 解决“日报邮件已发出、随后 Git push 失败”的状态不一致，并移除 YAML 中两段重复的 Git Shell。

**文件：**
- 新建：`scripts/workflow/publish_master.py`
- 新建：`tests/scripts/test_publish_master.py`
- 修改：`.github/workflows/daily_report.yml`
- 修改：`tests/scripts/test_ci_workflow.py`

- [x] **Step 1：写 Git 子仓库 fixture 测试。**

使用 `tmp_path` 初始化 bare remote 和本地 clone，覆盖：有报告发布、无报告仅状态库发布、无差异、push 被拒绝。测试不访问 GitHub：

```python
def test_publish_master_returns_failed_without_claiming_state_updated(git_repo):
    git_repo.reject_next_push()

    result = publish_master(PublishMasterRequest(...))

    assert result.status == "failed"
    assert result.master_state_updated is False
    assert "日报" in result.commit_subject
```

- [x] **Step 2：实现 `publish_master.py`。**

定义显式请求和结果对象：

```python
@dataclass(frozen=True)
class PublishMasterRequest:
    repository: Path
    branch: str
    mode: Literal["published", "no_report"]
    state_path: Path
    report_path: Path | None
    report_date: str
    counts: PublicationCounts

@dataclass(frozen=True)
class PublishMasterResult:
    status: Literal["succeeded", "no_changes", "failed"]
    master_state_updated: bool
    error: str = ""
```

实现要求：

- 路径必须解析后位于 `repository` 内；`published` 必须有存在的 Markdown 报告。
- 只运行 `git add -- <report> <state>` 或 `git add -- <state>`，禁止 `git add -A`、`git commit -am`。
- 提交标题、正文保持当前中文指标格式；无差异返回 `no_changes`，不创建空提交。
- 仅当 `git push origin HEAD:<branch>` 成功时返回 `master_state_updated=True`。
- Git 命令失败要保留 stdout/stderr 摘要供最终 manifest 和异常快照记录，但不得暴露环境变量。

- [x] **Step 3：调整 workflow 顺序。**

将当前“发送正式邮件 -> Git commit/push”调整为：

1. 候选 `published` 时渲染 HTML，步骤设 `continue-on-error: true` 并拥有 `id: render_html`。
2. 候选 `published` 或 `no_report` 时调用 `publish_master.py`，步骤设 `continue-on-error: true` 并拥有 `id: publish_master`。
3. `Finalize publication` 读取两个步骤结果；若正式状态未成功写入远程，则进入 `blocked`。
4. 仅最终状态为 `published` 时发送正式日报邮件，因此不可能先发邮件后发现 `master` 推送失败。

正式日报邮件失败不回滚已成功推送的正式状态；该步骤应保留为失败的 workflow 信号，并在运行日志中清楚说明“数据状态已发布、邮件投递失败”。不把它伪装为快照阻断，避免产生“远程 master 未更新”的错误告警。

- [x] **Step 4：运行 Git helper 与工作流测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/scripts/test_publish_master.py tests/scripts/test_finalize_publication.py tests/scripts/test_ci_workflow.py -q
```

预期：push 失败使最终状态为 `blocked`，正式邮件步骤只能位于最终发布判定之后。

### Task 4：抽离异常快照 Git 发布，并实现受限清理与安全告警路径

**目的：** 消除 46 行 `set +e` Shell；保证清理不会无上限扫描；保证构建快照失败时告警不会误读工作区文件。

**文件：**
- 新建：`scripts/workflow/publish_failure_snapshot.py`
- 修改：`notice_push/observability/failure_snapshot.py`
- 修改：`scripts/workflow/cleanup_failure_snapshots.py`
- 修改：`scripts/workflow/render_failure_alert.py`
- 修改：`.github/workflows/daily_report.yml`
- 新建：`tests/scripts/test_publish_failure_snapshot.py`
- 修改：`tests/notice_push/test_failure_snapshot.py`
- 修改：`tests/scripts/test_failure_snapshot_workflow_helpers.py`

- [x] **Step 1：为清理上限和空快照路径写失败测试。**

```python
def test_cleanup_stops_before_scanning_more_than_configured_limit(tmp_path):
    result = cleanup_expired_snapshot_dates(
        tmp_path,
        today=date(2026, 7, 10),
        retention_days=90,
        max_scan_entries=2,
    )

    assert result.limit_exceeded is True
    assert result.removed == ()

def test_alert_uses_explicit_publication_file_when_snapshot_path_is_empty(tmp_path):
    html = render_alert(snapshot_directory=None, publication_path=tmp_path / "publication.json", ...)
    assert "日报未发布" in html
```

- [x] **Step 2：将清理 API 改为结构化结果。**

```python
@dataclass(frozen=True)
class SnapshotCleanupResult:
    removed: tuple[Path, ...]
    scanned_entry_count: int
    limit_exceeded: bool

def cleanup_expired_snapshot_dates(
    root: Path,
    *,
    today: date,
    retention_days: int,
    max_scan_entries: int,
) -> SnapshotCleanupResult: ...
```

按名称排序后先检查目录数量；超过 `max_scan_entries` 时不删除任何目录、打印明确 warning、让本次快照继续提交。默认由 workflow 环境变量传入 `200`，而不是把 `200` 散落在 Python 和 YAML 中。

- [x] **Step 3：实现独立快照发布 helper。**

`publish_failure_snapshot.py` 接收独立 checkout、快照来源目录、目标分支、目标相对路径、保留参数和 `$GITHUB_OUTPUT`。它必须：

1. 用 `subprocess.run(..., cwd=checkout, check=False, capture_output=True, text=True)` 执行 Git，不依赖隐式 `cd`。
2. 远程分支存在时 `fetch` + `switch -C --track`；不存在时创建 orphan 分支并清空 checkout 内容。
3. 使用 `shutil.copytree(..., dirs_exist_ok=False)` 将本次快照复制到 `failure-snapshots/<date>/run-<id>`，目标已存在视为失败，避免覆盖诊断现场。
4. 只暂存新快照目录和 `SnapshotCleanupResult.removed` 列出的路径；不对整个 `failure-snapshots` 使用 `git add -u`。
5. 暂存为空、第一次 push 失败、rebase 冲突、第二次 push 失败分别返回可区分状态；首次 push 失败后最多 fetch/rebase/push 一次，冲突时执行 `git rebase --abort`。
6. 无论成功或预期失败，都写入 `snapshot_push_status=succeeded|failed`；意外异常使步骤失败，告警步骤以默认 `failed` 继续。

- [x] **Step 4：使告警渲染只接受显式有效快照目录。**

将 CLI 参数处理改为：空字符串、非目录、缺失目录都转换为 `None`；只有 `snapshot_directory.is_dir()` 且其中存在指定文件时才优先读取快照。`publication.json` 仍为必需 fallback，不能从当前目录猜测。

- [x] **Step 5：将 workflow 常量集中到顶层 `env`。**

在 `daily_report.yml` 顶层定义：

```yaml
env:
  FAILURE_SNAPSHOT_BRANCH: bot/failure-snapshots
  FAILURE_SNAPSHOT_RETENTION_DAYS: "90"
  FAILURE_SNAPSHOT_MAX_SCAN_ENTRIES: "200"
  FAILURE_SNAPSHOT_ARTIFACT_RETENTION_DAYS: "30"
```

替换 `Push failure snapshot` 中的 Shell 为 helper 调用；`Build/Upload/Alert/Fail` 均继续使用最终 `publication` 输出。移除旧的 `set +e` 大块脚本。

- [x] **Step 6：运行快照、告警和 workflow 测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_failure_snapshot.py tests/scripts/test_publish_failure_snapshot.py tests/scripts/test_failure_snapshot_workflow_helpers.py tests/scripts/test_ci_workflow.py -q
```

预期：200 目录上限、首次建分支、已有分支、一次重试、rebase 冲突、空路径告警和 Artifact 优先顺序均有测试。

### Task 5：批次一端到端回归与 PRD/TDD 对照

**文件：**
- 修改：`tests/scripts/test_ci_workflow.py`
- 修改：`docs/superpowers/tdds/2026-07-10-failure-snapshot-publication-policy-tdd.md`（仅当最终接口与原 TDD 不一致时）
- 修改：`docs/superpowers/prds/2026-07-10-failure-snapshot-publication-policy-prd.md`（仅当用户批准语义变化时）

- [x] **Step 1：增加 workflow 结构断言。**

断言：最终 `publication` 是唯一后续判断来源；正常邮件在 `publish_master` 和 `Finalize publication` 之后；`blocked` 分支包含 Artifact、快照、告警和最终 `exit 1`；没有超过 30 行的业务 Shell；没有 `set +e` 覆盖 Git 发布逻辑。

- [x] **Step 2：增加本地 Git 集成场景。**

使用本地 bare remote 模拟以下矩阵：

| 场景 | 最终状态 | 远程 master | 快照/告警资料 |
|---|---|---|---|
| 正常有报告 | `published` | 更新 | 不创建 |
| 正常无报告 | `no_report` | 仅状态库可更新 | 不创建 |
| pipeline 候选缺失 | `blocked` | 不更新 | 最小 manifest + 日志 |
| HTML 渲染失败 | `blocked` | 不更新 | 快照 |
| master push 失败 | `blocked` | 不更新 | 快照 |
| 快照 push 失败 | `blocked` | 不更新 | Artifact/告警仍可用 |

- [x] **Step 3：执行批次一完整验证。**

运行：

```powershell
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q notice_push scripts
conda run --no-capture-output -n spider python -m notice_push --doctor --state-path .tmp\publication-doctor.sqlite3
git diff --check
```

预期：全量测试通过，编译无输出，doctor 不产生 error，差异无空白错误。

## 3. 批次二：配置单一来源与抓取效率

### Task 6：让 `runtime.yml` 成为唯一生产配置来源

**目的：** 不再让删除/修改 YAML 后仍由 Python 静默恢复真实源站、模型、路由或运行参数。

**文件：**
- 修改：`notice_push/settings/loader.py`
- 删除或大幅收缩：`notice_push/settings/defaults.py`
- 修改：`notice_push/settings/profiles.py`
- 修改：`notice_push/domain/runtime.py`
- 修改：`resources/config/runtime.yml`
- 修改：`.env.example`
- 修改：`tests/notice_push/test_config_models.py`
- 新建：`tests/notice_push/test_runtime_config_contract.py`

- [ ] **Step 1：写严格 YAML 合同失败测试。**

```python
def test_load_config_rejects_missing_source_definition(tmp_path):
    write_runtime_yaml(tmp_path, sources={})

    with pytest.raises(ValueError, match="sources.shu_official"):
        load_config(repo_root=tmp_path, env={})

def test_load_config_does_not_restore_removed_builtin_provider(tmp_path):
    write_runtime_yaml(tmp_path, llm={"providers": {"custom": valid_provider()}})

    config = load_config(repo_root=tmp_path, env={})
    assert set(config.llm_providers) == {"custom"}
```

- [ ] **Step 2：删除真实生产默认值。**

删除 `_built_in_source_defaults()`、`DEFAULT_LLM_PROVIDERS`、`DEFAULT_LLM_ROUTING` 和 `PROFILE_DEFAULTS` 中的真实生产数值。Loader 必须要求：

- `sources` 非空；每个 source 显式包含 `name`、`base_url`、`list_url`、`adapter`、`enabled`。
- `llm.providers` 非空；每个 provider 显式包含 `base_url`、`api_key_env`、`model_env`、`default_model`、`kind`。
- `llm.routing` 显式定义 `text`、`pdf`、`image`，且均指向已声明 provider。
- `profiles.daily` 和 `profiles.backfill` 显式声明所有运行字段，包括后续 Task 7 加入的 HTTP 退避字段。
- `parsing`、`media`、`audit` 和 `detail_min_chars` 显式声明。

错误信息必须带完整 YAML 路径，例如 `profiles.daily.http_timeout must be an integer`，避免只报泛化 `KeyError`。

- [ ] **Step 3：补齐 YAML，并收紧 `.env.example`。**

`runtime.yml` 持有所有非机密配置。`.env.example` 只保留：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
KIMI_API_KEY=
KIMI_MODEL=kimi-k2.7-code
```

不在 `.env.example` 放 URL、页数、并发、超时、分支名或通知源地址。

- [ ] **Step 4：运行配置测试和 doctor。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_runtime_config_contract.py -q
conda run --no-capture-output -n spider python -m notice_push --doctor --state-path .tmp\config-doctor.sqlite3
```

预期：缺失配置明确失败，仓库真实 YAML 与 `.env` 均能通过 doctor。

### Task 7：统一 source 选择与失败重试常量

**目的：** 删除 CLI、Factory、Pipeline 三处重复的 source 选择规则，并消除永久失败类型的重复定义。

**文件：**
- 新建：`notice_push/sources/selection.py`
- 修改：`notice_push/cli.py`
- 修改：`notice_push/app_factory.py`
- 修改：`notice_push/pipeline.py`
- 修改：`notice_push/storage/database.py`
- 修改：`notice_push/crawler/failures.py`
- 新建：`tests/notice_push/test_source_selection.py`
- 修改：`tests/notice_push/test_storage.py`

- [ ] **Step 1：写 source 选择一致性测试。**

```python
def test_select_sources_rejects_unknown_ids_and_ignores_disabled_by_default():
    selected = select_sources(sources, requested_ids=())
    assert [source.id for source in selected] == ["enabled"]

    with pytest.raises(ValueError, match="Available sources: enabled, disabled"):
        select_sources(sources, requested_ids=("missing",))
```

- [ ] **Step 2：实现唯一选择函数。**

```python
def select_sources(
    sources: Iterable[NoticeSource],
    requested_ids: Iterable[str] | None = None,
) -> list[NoticeSource]: ...
```

CLI 在构建 pipeline 前用此函数校验；`run_source_audit` 和 Pipeline 使用同一函数。删除 `cli.select_sources`、`app_factory._select_sources`、`NoticePipeline._select_sources`。

- [ ] **Step 3：使 storage 复用失败分类规则。**

删除 `storage/database.py` 的 `PERMANENT_FAILURE_TYPES`。`_row_retryable()` 通过 `crawler.failures.is_retryable_failure_type()` 判断，确保新增永久失败类型只维护一次。

- [ ] **Step 4：删除无生产调用的旧 storage 筛选 API。**

确认 `filter_new_items`、`filter_processable_items`、`split_processable_items` 仅被旧测试使用后，删除它们并将测试改为 `split_pipeline_items` 的明确断言。这里不保留兼容层，因为项目不再需要旧入口兼容。

- [ ] **Step 5：运行针对性回归。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_source_selection.py tests/notice_push/test_storage.py tests/notice_push/test_cli.py tests/notice_push/test_pipeline.py -q
```

预期：source 错误信息统一，重试语义未变化。

### Task 8：实现 profile 化 HTTP 重试和单次运行文本缓存

**目的：** 减少巡检与正式抓取重复访问，避免对永久 4xx 反复请求，并使所有重试参数真正由 YAML profile 控制。

**文件：**
- 新建：`notice_push/http_retry.py`
- 新建：`notice_push/http_cache.py`
- 修改：`notice_push/http.py`
- 修改：`notice_push/domain/runtime.py`
- 修改：`notice_push/settings/loader.py`
- 修改：`notice_push/app_factory.py`
- 修改：`resources/config/runtime.yml`
- 新建：`tests/notice_push/test_http_retry.py`
- 新建：`tests/notice_push/test_http_cache.py`
- 修改：`tests/notice_push/test_config_models.py`

- [ ] **Step 1：写 HTTP 重试矩阵的失败测试。**

```python
@pytest.mark.parametrize("status,should_retry", [(404, False), (401, False), (429, True), (500, True), (503, True)])
def test_http_status_retry_policy(status, should_retry):
    assert is_retryable_http_status(status) is should_retry

def test_retry_after_is_capped_by_profile_limit():
    assert retry_delay_seconds("120", fallback_delay=1.0, max_delay=30.0) == 30.0
```

- [ ] **Step 2：实现 HTTP 重试策略。**

在 `http_retry.py` 定义：

```python
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

def is_retryable_http_status(status_code: int | None) -> bool: ...
def retry_delay_seconds(retry_after: str | None, *, fallback_delay: float, max_delay: float) -> float: ...
```

`HttpClient._get_response()` 只重试连接/读取超时类 `requests.RequestException`，以及集合内状态码；其他 4xx 立即抛出。遇到有 `Retry-After` 的 429/503 时优先使用其秒数或 HTTP 日期，并按 profile `http_max_retry_delay_seconds` 封顶。每次失败响应必须 `close()`，避免连接泄漏。

- [ ] **Step 3：将所有 HTTP 退避参数加入 profile。**

给 `NoticeRuntimeProfile` 和两个 YAML profile 增加：

```yaml
http_retry_backoff: 2.0
http_max_retry_delay_seconds: 30
```

`build_http_client()` 必须把已有 `http_initial_retry_delay`、新增退避倍数、延迟上限都传给 `HttpClient`，不能让 `HttpClient` 构造器默认值绕过 YAML。

- [ ] **Step 4：实现单次运行 `get_text` 成功响应缓存。**

```python
class RunScopedTextCache:
    def get_or_load(self, url: str, loader: Callable[[], str]) -> str: ...

class CachedHttpClient:
    def get_text(self, url: str) -> str: ...
    def get_bytes(self, url: str) -> bytes: ...
    def get_download_limited(self, url: str, max_bytes: int) -> DownloadedBytes: ...
```

缓存只存在于一次 `build_pipeline()` 所创建的对象中；只缓存成功的文本，不缓存异常、字节流或媒体下载。使用每 URL in-flight 同步，避免 audit 与后续并发详情请求产生缓存击穿。Pipeline 与 `SourceAuditor` 必须共享同一 `CachedHttpClient` 实例。

- [ ] **Step 5：写 audit 与扫描复用测试。**

```python
def test_audit_then_pipeline_fetches_same_list_and_detail_url_once():
    client = RecordingHttpClient(...)
    pipeline = build_pipeline_with_cached_client(client)

    pipeline.run(options_with_audit)

    assert client.calls[detail_url] == 1
```

- [ ] **Step 6：运行 transport 与 pipeline 测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_http_retry.py tests/notice_push/test_http_cache.py tests/notice_push/test_pipeline.py tests/notice_push/test_config_models.py -q
```

预期：404 不重试，429/5xx 按限制重试；同 URL 成功文本在单次运行内只抓取一次。

### Task 9：为三类通知源建立 fixture 驱动的解析合同

**目的：** 将站点 HTML 结构变化的影响收敛到小型 fixture 与 adapter 合同测试，而不是依赖每日线上运行才发现问题。

**文件：**
- 新建：`tests/fixtures/sources/shu_official/`
- 新建：`tests/fixtures/sources/management_school/`
- 新建：`tests/fixtures/sources/graduate_school/`
- 修改：`tests/notice_push/test_sources.py`
- 修改：`tests/notice_push/test_parsing.py` 或新建 `tests/notice_push/test_source_contracts.py`
- 可能修改：`notice_push/sources/*.py`

- [ ] **Step 1：确定 fixture 最小集合。**

每个来源至少保留：目录首页、包含文本正文的详情页；管理学院和研究生院另保留 PDF/图片或 PDFJS 详情页；研究生院保留外链视频页。Fixture 删除无关页面区域和可能包含个人信息的内容，但保留选择器、分页、编码、资源 URL 和日期结构。

- [ ] **Step 2：写 adapter 合同测试。**

```python
@pytest.mark.parametrize("source_id", ["shu_official", "management_school", "graduate_school"])
def test_source_adapter_contract(source_id, fixture_html):
    adapter = configured_adapter(source_id)
    items = adapter.parse_list_page(fixture_html.list_page, fixture_html.list_url)

    assert items
    assert all(item.title and item.url and item.canonical_url for item in items)
    assert adapter.find_next_page_url(fixture_html.list_page, fixture_html.list_url) == fixture_html.next_page_url
```

详情合同分别断言 `text`、`pdf`、`image`、`video` 的 `content_kind` 和 primary/attachment asset，不断言模型摘要内容。

- [ ] **Step 3：必要时使用 Playwright MCP 复核真实 DOM。**

仅当 fixture 与当前网页结构不一致时，打开来源目录与一条详情页，记录选择器变化和分页链接机制；将更新后的最小 HTML 结构整理为 fixture，再修改 adapter。不得把浏览器 profile、Cookie 或下载媒体文件提交到仓库。

- [ ] **Step 4：运行所有来源解析测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_sources.py tests/notice_push/test_source_contracts.py tests/notice_push/test_html_utils.py -q
```

预期：三个来源的列表、分页、文本、PDF、图片、视频路径均有离线回归保护。

## 4. 批次三：Pipeline、存储、解析与 LLM 职责拆分

### Task 10：拆分 Pipeline 的扫描、处理和结果装配职责

**目的：** 将当前 `NoticePipeline.run()` 的多重职责拆开，同时消除 `_summarize_notices()` 对 `daily` profile 的隐式依赖。

**文件：**
- 新建：`notice_push/crawler/source_scan.py`
- 新建：`notice_push/crawler/notice_processing.py`
- 新建：`notice_push/pipeline_result.py`
- 修改：`notice_push/pipeline.py`
- 修改：`tests/notice_push/test_pipeline.py`
- 新建：`tests/notice_push/test_source_scan.py`
- 新建：`tests/notice_push/test_notice_processing.py`

- [ ] **Step 1：为目录扫描提取写测试。**

```python
def test_scan_source_stops_on_repeat_url_cutoff_and_page_limit():
    outcome = scan_source_pages(source, adapter, client, max_pages=3, cutoff=cutoff)

    assert outcome.page_count == 2
    assert outcome.stop_reason == "repeated_page_url"
    assert outcome.source_errors == ()
```

- [ ] **Step 2：实现 `scan_source_pages()`。**

它只负责目录页：请求、解析、已访问 URL、页数、lookback、分页和 `SourceError`。返回不可变 `SourceScanOutcome`，包含按页的 `ScannedListPage`、停止原因和错误；不访问 SQLite、不抓详情、不调用 LLM。

- [ ] **Step 3：实现通知处理协调器。**

```python
class NoticeProcessor:
    def process_page(self, source: NoticeSource, page: ScannedListPage, options: PipelineRunOptions) -> ProcessingOutcome: ...
    def summarize(self, prepared: Sequence[PreparedNotice], *, max_workers: int, retry_policy: FailureRetryPolicy) -> SummaryOutcome: ...
```

它集中处理新通知、失败重试、`updated_seen`、详情抓取、刷新已见正文和摘要；保留当前列表顺序与计数语义。`max_workers` 必须来自 `PipelineRunOptions`，删除 `runtime_profile("daily")` 的隐藏 fallback。

- [ ] **Step 4：将 `NoticePipeline` 缩为应用编排器。**

`NoticePipeline.run()` 只做：选择源、可选审计、依次调用 scanner/processor、合并结果、渲染报告、写 run summary、checkpoint。目标是控制在约 150 行以内，且每个子模块可独立测试。

- [ ] **Step 5：运行行为回归。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_source_scan.py tests/notice_push/test_notice_processing.py tests/notice_push/test_pipeline.py -q
```

预期：dry-run、bootstrap、daily/backfill、分页循环、失败重试、正文更新和并发顺序测试全部通过。

### Task 11：拆分存储查询/写入职责并改为批量状态读取

**目的：** 消除 `NoticeStorage` 的查询与写入混杂，并避免每个列表项执行一次 `SELECT`。

**文件：**
- 新建：`notice_push/storage/selection.py`
- 新建：`notice_push/storage/source_repository.py`
- 新建：`notice_push/storage/notice_repository.py`
- 修改：`notice_push/storage/database.py`
- 修改：`notice_push/storage/__init__.py`
- 修改：`tests/notice_push/test_storage.py`
- 新建：`tests/notice_push/test_storage_selection.py`

- [ ] **Step 1：写批量分类查询测试。**

```python
def test_classify_pipeline_items_uses_one_select_per_chunk(storage, items, spy_connection):
    result = storage.classify_pipeline_items(items, retry_policy=policy)

    assert result.new_items == expected_new
    assert result.retry_items == expected_retry
    assert spy_connection.select_count <= 1
```

- [ ] **Step 2：实现 `NoticeSelectionRepository`。**

按同一 source 将 canonical URL 分块（每块最多 400 个，防止 SQLite 参数上限），用一条 `IN (...)` 查询拿到 `id`、`status`、失败字段和已见详情所需列。返回：

```python
@dataclass(frozen=True)
class PipelineItemSelection:
    new_items: tuple[NoticeListItem, ...]
    retry_items: tuple[NoticeListItem, ...]
    updated_seen: tuple[SelectedUpdatedNotice, ...]
    seen_rows: Mapping[str, sqlite3.Row]
```

保持输入顺序，避免并发后日报排序变化。

- [ ] **Step 3：按事务角色拆分写入。**

`SourceRepository` 负责 `sources` 表初始化/upsert；`NoticeRepository` 负责详情、摘要、失败、baseline 和 checkpoint；`NoticeStorage` 仅持有连接工厂、写锁与上述仓库组合，作为 Pipeline 注入的稳定门面。删除已确认无调用的旧筛选方法。

- [ ] **Step 4：运行 SQLite 迁移与并发测试。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py tests/notice_push/test_storage_selection.py tests/notice_push/test_sqlite_backup.py -q
```

预期：既有状态库迁移、WAL checkpoint、并发详情写入、失败重试和批量分类均通过。

### Task 12：按正文、资源、PDFJS、日期拆分 HTML 解析模块

**目的：** 让新增资源类型或修复站点结构时只修改对应解析模块，而不触碰 350 行通用文件。

**文件：**
- 新建：`notice_push/parsing/content.py`
- 新建：`notice_push/parsing/assets.py`
- 新建：`notice_push/parsing/pdfjs.py`
- 新建：`notice_push/parsing/dates.py`
- 新建：`notice_push/parsing/urls.py`
- 删除：`notice_push/parsing/html.py`
- 修改：`notice_push/parsing/detail.py`
- 修改：`notice_push/sources/base.py`
- 修改：`notice_push/sources/*.py`
- 修改：`tests/notice_push/test_html_utils.py`
- 修改：`tests/notice_push/test_sources.py`

- [ ] **Step 1：先移动测试导入，不改变断言内容。**

将日期测试导入改为 `notice_push.parsing.dates.parse_date`，PDFJS 测试改为 `notice_push.parsing.pdfjs.extract_pdfjs_assets`，资源测试改为 `notice_push.parsing.assets`，正文选择测试改为 `notice_push.parsing.content`。此步骤应先失败，证明迁移目标明确。

- [ ] **Step 2：按职责移动实现。**

模块规则：

- `urls.py`：`absolute_url()`、文件名提取与外部视频域名判断。
- `dates.py`：仅 `parse_date()`。
- `content.py`：文本清洗、噪声节点、正文选择、文本块提取、`ParsingRules`。
- `assets.py`：链接、图片、视频资源提取、去重、内容类型推断与 primary 提升。
- `pdfjs.py`：PDFJS viewer 参数和 `showVsbpdfIframe()` 解析。

更新 `DetailParser` 和 adapters 使用新模块；不保留 `html.py` 兼容转发层。

- [ ] **Step 3：运行解析与来源回归。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_html_utils.py tests/notice_push/test_sources.py tests/notice_push/test_source_contracts.py -q
```

预期：带 query 的 PDFJS、脚本 PDF、图片、视频、正文 fallback 和日期格式均保持原行为。

### Task 13：LLM builder 注册表与共享摘要格式生命周期

**目的：** 新增 provider kind 时不再修改 `app_factory` 的 `if` 链；消除 DeepSeek/Kimi 中重复的提示词加载、格式修复和硬编码环境变量读取。

**文件：**
- 新建：`notice_push/llm/registry.py`
- 新建：`notice_push/llm/summary_format.py`
- 可能新建：`notice_push/llm/client_factory.py`
- 修改：`notice_push/llm/text.py`
- 修改：`notice_push/llm/kimi.py`
- 修改：`notice_push/app_factory.py`
- 修改：`notice_push/llm/providers.py`
- 修改：`tests/notice_push/test_summarizer.py`
- 新建：`tests/notice_push/test_llm_registry.py`

- [ ] **Step 1：写注册表和环境隔离测试。**

```python
def test_registry_builds_configured_provider_without_factory_if_chain():
    builder = summarizer_builder_for("openai_text")
    assert builder is not None

def test_text_summarizer_does_not_read_deepseek_environment_when_factory_supplies_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    summarizer = NoticeSummarizer(api_key="configured-key", client=fake_client, ...)
    assert summarizer.summarize(1, detail).model == "configured-model"
```

- [ ] **Step 2：提取共享格式处理器。**

```python
class SummaryFormatProcessor:
    def normalize_validate_or_repair(
        self,
        markdown: str,
        *,
        source_detail: NoticeDetail,
        source_name: str | None,
        chat_for_repair: Callable[[str], str],
    ) -> str: ...
```

它负责 normalize、validate、按配置次数生成 repair prompt；文本和 Kimi 摘要器各自只提供初始消息构造和 text chat 回调。

- [ ] **Step 3：实现 registry。**

```python
SummarizerBuilder = Callable[[ResolvedLLMProvider, SummarizerDependencies], object]

def register_summarizer_builder(kind: str, builder: SummarizerBuilder) -> None: ...
def build_summarizer(provider: ResolvedLLMProvider, dependencies: SummarizerDependencies) -> object: ...
```

内建注册 `openai_text` 与 `kimi_multimodal`。`app_factory` 只遍历 provider 并调用 `build_summarizer()`；未知 kind 在配置加载阶段和 registry 构建阶段都给出清晰错误。

- [ ] **Step 4：移除模型类对环境变量的隐式读取。**

`ResolvedLLMProvider` 是唯一读取 `api_key_env`、`model_env` 的位置。`NoticeSummarizer` 和 `KimiMultimodalSummarizer` 在创建真实 `OpenAI` client 时只使用构造器传入的 `api_key`/`base_url`；若 client 未注入且 key 为空，错误消息使用 provider 名称，不硬编码 `DEEPSEEK_API_KEY` 或 `KIMI_API_KEY`。

- [ ] **Step 5：运行 LLM 回归。**

运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_llm_registry.py tests/notice_push/test_summarizer.py tests/notice_push/test_config_models.py -q
```

预期：文本、PDF、图片、上传/抽取重试、格式修复与 provider 路由行为保持不变。

### Task 14：最终质量门禁、文档和可维护性复审

**目的：** 将本轮改造的结构约束固定为自动检查，避免未来重新出现大段 workflow Shell、配置双来源和职责回流。

**文件：**
- 修改：`tests/scripts/test_ci_workflow.py`
- 修改：`.github/workflows/ci.yml`
- 修改：`README.md`
- 修改：`PROJECT_DOCUMENTATION.md`
- 修改：`docs/superpowers/tdds/2026-07-10-failure-snapshot-publication-policy-tdd.md`
- 新建：`docs/superpowers/reviews/2026-07-10-post-remediation-review.md`

- [ ] **Step 1：为结构约束增加静态测试。**

在工作流测试中断言：

- `daily_report.yml` 不含超过 30 行的业务 Shell；Git 发布只能通过 `python -m scripts.workflow.publish_master` 或 `publish_failure_snapshot`。
- 异常分支只读取最终 `steps.publication.outputs.*`。
- `runtime.yml` 定义三个生产源、两套 profile、全部 LLM provider/routing；Loader 不含三个生产 URL 和 provider 默认值。
- `NoticePipeline.run()` 不含 pagination 和 SQLite 查询 SQL；`app_factory` 不包含 `if provider.kind`。

必要时采用 AST 测试而不是脆弱的全文字符串计数。

- [ ] **Step 2：更新文档。**

README 说明：正式发布严格模式、`bot/failure-snapshots` 的诊断用途、Artifact 保留期、`runtime.yml` 与 `.env` 的职责边界、日常 profile 与 backfill profile 的配置位置。项目文档补充模块图和新增源/新增 provider 的最短路径。

- [ ] **Step 3：执行最终验证。**

运行：

```powershell
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q notice_push scripts
conda run --no-capture-output -n spider python -m notice_push --doctor --state-path .tmp\final-doctor.sqlite3
git diff --check
```

预期：全部通过。

- [ ] **Step 4：进行独立复审并写入结论。**

以当前 `master` 为基线审查未提交变更，重点确认：

1. 正式邮件与远程 `master` 状态不会再出现先后不一致。
2. 判定器、HTML、Git push、快照 Git push 的失败都能留下 Alert/Artifact/日志。
3. `runtime.yml` 删除任一生产项会明确失败而非被代码恢复。
4. 目录巡检和正式抓取不会重复成功文本请求。
5. 新 module 的职责边界没有新增循环依赖或兼容层残留。

将发现和剩余风险写入 `docs/superpowers/reviews/2026-07-10-post-remediation-review.md`，供用户确认后再决定提交与推送。

## 5. 建议执行顺序与审批点

1. **先执行 Task 1-5。** 这是生产正确性修复，完成后先让用户检查 workflow diff 和本地 Git 场景结果。
2. **批准后执行 Task 6-9。** 这是配置治理与抓取效率改造，完成后重点检查 YAML 严格性、请求次数和三个来源 fixture。
3. **最后执行 Task 10-14。** 这是行为锁定后的职责拆分；每完成一个模块拆分都运行对应小范围测试，批次末再运行全量测试。
4. 全部任务完成后，不自动提交或推送；先提交独立复审文档和中文提交建议，等待用户明确批准。

## 6. 计划自检

- 发布判定 fallback、master push 失败、异常快照 Git 重试、保留扫描上限、空路径告警问题分别由 Task 1-5 覆盖。
- 配置双来源、重复 source 选择、重复失败常量、HTTP 盲重试、巡检重复抓取、三个来源的离线回归分别由 Task 6-9 覆盖。
- Pipeline、存储、HTML、LLM 的过长文件和职责混杂分别由 Task 10-13 覆盖。
- 每个批次都有先测后改、针对性验证和最终全量验证；没有要求保留旧入口或旧兼容层。
