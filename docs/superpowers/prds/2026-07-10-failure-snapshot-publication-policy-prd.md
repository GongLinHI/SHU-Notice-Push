# PRD：日报正式发布与异常快照隔离

**状态：已批准并实施**
**日期：2026-07-10**
**适用范围：** `daily_report.yml` 驱动的上海大学通知日报任务

## 1. 背景与问题

当前日报任务会在同一次运行中抓取多个通知源、更新 SQLite 状态库，并可能生成日报。若其中一个源站目录页抓取失败、DOM 巡检发现致命异常，其他源站仍可能成功生成部分结果；现有流程存在把这类不完整结果提交到 `master` 或发送为正式日报的风险。

这会混淆两类状态：

- **正式状态：** 已完整验证、可作为下一次正常运行基线的通知状态与日报。
- **故障现场：** 为排查而保留的部分抓取结果、错误日志和运行后状态，不应影响下一次正式运行。

本 PRD 建立“正式状态严格发布，异常现场独立留存”的运行策略：保证异常一定告警、现场可追溯，同时避免故障运行污染 `master` 的正式状态库。

## 2. 目标与非目标

### 目标

1. 只有全部通知源满足正式发布条件时，才向 `master` 提交日报和 SQLite 正式状态。
2. 发生源站级或运行级异常时，必定发送独立异常告警，并同时保留可复现的诊断现场。
3. 每次阻断性异常都在独立分支保存运行后的 SQLite、日志、运行摘要和必要的部分输出，便于后续修复。
4. 下一次正常日报始终以 `master` 的最后一次正式状态为基线，不使用故障运行的状态。
5. 保留当前“单条通知失败进入人工复核”的能力，避免个别 PDF、图片或 LLM 摘要失败阻断所有正常通知。

### 非目标

- 不改变三个通知源的业务解析规则、LLM 路由或摘要内容格式。
- 不自动从异常快照分支恢复或合并 SQLite 状态到 `master`。
- 不把异常快照分支作为用户可订阅的日报来源。
- 不在本期引入外部监控平台；GitHub Actions、邮件告警、Artifact 与 Git 快照是唯一诊断渠道。

## 3. 核心概念与判定

| 名称 | 定义 | 对正式发布的影响 |
|---|---|---|
| 正式发布 | 本次所有已启用源站均完成目录抓取，且没有致命巡检或运行异常 | 可发送日报并更新 `master` |
| 正常无通知 | 已完成完整抓取，但没有需要生成日报的通知或人工复核项 | 可更新 SQLite；不发送日报 |
| 单条通知失败 | 详情抓取、媒体下载、LLM 摘要等针对单条通知的失败，已进入“人工复核” | 不阻断正式日报 |
| 发布阻断异常 | 运行无法可靠覆盖全部源站，或流程未能产生可信执行结果 | 不发送日报、不更新 `master`，保存异常快照 |
| 异常快照 | 仅用于诊断的运行现场，包括运行后 SQLite、日志、摘要和元数据 | 只写入异常快照分支与 Artifact |

### 发布阻断条件

满足以下任一条件即判定为“发布阻断异常”：

- `pipeline_exit_code = 2`，包括启动、配置、未处理异常或未能输出完整计数的失败。
- `source_error_count > 0`，即任一通知源目录页抓取或目录解析失败。
- `audit_error_count > 0`，即运行前 DOM 巡检发现致命结构异常。

以下情况**不**阻断正式发布，但必须写入日报运行概览、run summary 和必要的告警/日志：

- `failed_count > 0` 或 `manual_review_count > 0`：单条通知需要人工复核。
- `audit_warning_count > 0`：巡检警告。
- `refresh_seen_error_count > 0`：已见通知正文刷新异常。

这一边界保证“某源站整体不可用”不会被当作完整日报发布，同时保留个别通知失败的可见性与后续重试能力。

## 4. 运行与发布流程

### 4.1 正式发布路径

当本次运行不满足任何发布阻断条件时：

1. 保留现有日报生成、Markdown 转 HTML、正式日报邮件发送逻辑。
2. 若生成日报，则提交 `resources/results`（排除 `resources/results/html`）与 `resources/notice_state.sqlite3` 到 `master`。
3. 若为“正常无通知”，不发送日报邮件；如 SQLite 发生变化，仍可只提交正式状态库到 `master`。
4. Bot 提交继续使用中文标题和中文正文，标题包含新增、正文更新、人工复核计数，正文保留完整运行计数。

### 4.2 发布阻断路径

当本次运行满足任一发布阻断条件时：

1. 不渲染或发送正式日报 HTML，不向 `master` 提交 `resources/results` 或 `resources/notice_state.sqlite3`。
2. 无论是否已经生成了部分 Markdown 或部分 SQLite 变更，均将其视为诊断材料，不得作为正式发布内容。
3. 发送“上海大学通知推送运行异常”邮件，说明本次日报未发布、`master` 正式状态未更新，并提供 Actions 运行链接。
4. 将运行现场上传为 GitHub Artifact，并写入异常快照分支。
5. 在 workflow 最后以失败状态结束，使 GitHub Actions 页面明确标红；告警和快照步骤必须使用 `if: always()`，确保即使主流程异常也有机会执行。

### 4.3 异常快照分支

使用专用诊断分支：`bot/failure-snapshots`。该分支禁止 merge 或 rebase 回 `master`。

每次阻断性异常在该分支创建以下目录：

```text
failure-snapshots/<北京时间日期>/run-<github-run-id>/
  metadata.md
  notice_pipeline.log
  run_summary.json
  notice_state.sqlite3
  partial_report.md          # 仅在本次已经生成时保存
```

文件要求：

- `metadata.md` 记录报告日期、仓库 commit SHA、workflow run ID/URL、触发方式、发布判定、退出码、全部计数、阻断原因与生成时间。
- `notice_pipeline.log` 为完整标准输出/错误输出，禁止包含 API key、SMTP 密码等 Secret。
- `run_summary.json` 为本次运行生成的摘要；若主程序在生成该文件前异常，workflow 需生成一个最小 fallback JSON，至少记录退出码、阻断原因和日志路径。
- `notice_state.sqlite3` 为本次运行结束后的状态库副本，供离线排查；它不是下一次正式运行的基线。
- `partial_report.md` 仅用于诊断，不发送邮件、不出现在 `master`。

快照提交消息采用中文，例如：

```text
异常快照 2026-07-10: 源站异常 1 巡检异常 0 [bot]

运行 ID: 123456789
退出码: 2
阻断原因: source_error_count=1
```

### 4.4 Artifact 与保留策略

- 每次阻断性异常上传一个 `notice-failure-snapshot-<日期>-<run-id>` Artifact，内容与异常快照目录一致，保留 **30 天**。
- `bot/failure-snapshots` 默认保留最近 **90 天** 的快照目录；超过期限的目录由后续异常快照任务在该分支中清理并提交。
- 90 天是推荐默认值，后续应提取为 workflow 环境变量或运行配置，便于调整。
- 异常快照写入独立 Git 分支前，先显式拉取该分支；首次异常时创建分支。仅暂存当前 `failure-snapshots/.../run-...` 目录及保留清理造成的删除，严禁使用会把工作目录其他文件带入提交的全量暂存命令。

## 5. 告警与可观测性要求

异常告警邮件必须包含：

- 报告日期、GitHub run ID、workflow URL、触发方式与 Git SHA。
- 发布状态：`日报未发布；master 正式状态未更新`。
- `pipeline_exit_code`、`source_error_count`、`audit_error_count`、`audit_warning_count`、`refresh_seen_error_count`、`failed_count`、`manual_review_count`。
- 各源站的错误摘要；可识别时包含源站 ID、名称、失败阶段和页面 URL。
- Artifact 名称及异常快照分支路径。

正常日报邮件不包含源站级故障；若存在非阻断的人工复核项，则沿用日报中的“需要人工复核”章节。

run summary JSON 新增或明确维护以下发布字段：

```json
{
  "publication_status": "published | no_report | blocked",
  "publication_blockers": ["source_error_count=1"],
  "failure_snapshot_path": "failure-snapshots/2026-07-10/run-123456789",
  "master_state_updated": false
}
```

其中 `failure_snapshot_path` 仅在 `blocked` 时存在；`master_state_updated` 应反映 workflow 实际是否推送了正式状态，而非主程序是否写过本地 SQLite。

## 6. GitHub Actions 实现约束

1. 在解析 CLI 计数后，集中计算 `publication_status` 与 `publication_blockers`，后续步骤只依赖该结果，不再分散使用不一致的 `if` 条件。
2. 正式邮件、HTML 转换、`master` 提交步骤仅在 `publication_status = published` 时执行；正常无通知只允许正式 SQLite 状态提交。
3. 异常告警、Artifact 上传、异常快照创建步骤使用 `if: always()` 加上 `publication_status = blocked` 的条件。
4. 为避免混入故障产物，异常快照在独立临时目录中构建；正式提交和异常快照提交使用不同 checkout/worktree 与明确的 `git add` 路径。
5. 复用现有 workflow 并发组，保证同一时间只有一个日报任务写入 `master` 或异常快照分支。
6. 如果异常快照推送本身失败，workflow 仍须失败，告警邮件中标记“快照推送失败”，但 Artifact 上传应尽力完成。

## 7. 验收标准

### 场景 A：全部源站正常，有新通知

- 发送正式日报邮件。
- `master` 仅获得正式报告与正式 SQLite 状态更新。
- 不创建异常 Artifact 或异常快照提交。

### 场景 B：全部源站正常，无新通知

- 不发送正式日报邮件，也不发送异常邮件。
- 若 SQLite 有状态变化，可提交到 `master`。
- workflow 成功结束。

### 场景 C：一个源站目录抓取失败，其余源站有新通知

- 不发送正式日报，不在 `master` 提交任何本次报告或 SQLite 变更。
- 发送异常告警邮件，明确日报未发布且正式状态未更新。
- 生成并上传异常 Artifact，同时在 `bot/failure-snapshots` 写入包含运行后 SQLite、日志和部分报告的快照。
- workflow 最终失败。

### 场景 D：DOM 巡检出现 error

- 行为与场景 C 一致，阻断原因明确为巡检异常。

### 场景 E：一条 PDF/图片/LLM 摘要失败，但三个源站目录均正常

- 正式日报正常发送与提交。
- 失败通知出现在“需要人工复核”中，计数进入 run summary。
- 不创建异常快照分支提交。

### 场景 F：程序启动或配置失败，未生成 run summary

- 发送异常告警。
- workflow 生成最小 fallback summary 与日志 Artifact。
- 快照分支至少保存 `metadata.md`、日志和运行后的状态库（若存在）。
- workflow 最终失败。

## 8. 风险与默认决策

- Git 中保存 SQLite 会增加仓库体积，因此异常快照仅保留 90 天，并且只在阻断性异常时保存。正式 SQLite 继续遵循项目当前的短期提交策略。
- 故障运行不会推进 `master` 状态，故障恢复后可能对少量已抓取但未正式提交的通知再次请求详情或 LLM；这是用少量重复成本交换“不漏通知、不把不完整日报标记为完成”。
- 异常快照可能含通知正文和附件元数据，应将诊断分支保持为私有仓库分支，并禁止在日志中输出 Secret。
- 默认不将 `refresh_seen_error_count` 作为发布阻断条件，因为它只影响已见通知正文刷新；如后续发现该环节承担关键业务语义，可单独提升为阻断条件。
