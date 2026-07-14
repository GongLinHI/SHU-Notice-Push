# 可靠性、效率与架构治理最终复审

**复审日期：** 2026-07-14
**对应计划：** `docs/superpowers/plans/2026-07-10-reliability-efficiency-and-architecture-remediation.md`
**结论：** 通过，未发现仍需阻止提交的 Critical、High 或 Medium 问题。

## 1. 结论与发现

本轮复审覆盖 Task 1-14 的最终工作区。发布一致性、异常现场、配置单一来源、请求复用、模块职责和 JSON 合同均达到计划要求。复审过程中发现的以下问题已在形成结论前修复：

1. 文本与 Kimi summarizer 仍内置生产 API endpoint；现已改为必须由 `runtime.yml` 显式注入。
2. `ParsingConfig`、`MediaPolicy`、`AuditPolicy` 和解析规则仍复制生产默认值；现已删除生产回退，来源合同测试也改为使用应用装配器注入 YAML 规则。
3. 最终发布 emergency fallback 一度依赖 Pydantic 和项目包，削弱了项目导入失败时的恢复能力；现已恢复为仅依赖标准库，并增加 AST 约束测试。
4. 发布计数允许负数，异常日志理论上可能绕过 `source_error_count > 0` 判定；现已改为严格非负整数合同。
5. CI 重复执行定向 pytest，且编译检查遗漏 `scripts`；现已收敛为一次全量测试、完整编译和 `git diff --check`。
6. README 的发布顺序仍描述为先发邮件后提交；现已同步为先推送正式状态、最终判定成功后再发送日报。

## 2. 架构复核

### Pipeline 与抓取

- `NoticePipeline.run()` 只保留来源选择、审计、扫描、页面处理和结果装配的协调逻辑。
- 分页、重复 URL 保护、时间窗口和硬页数上限位于 `crawler/source_scan.py`。
- 新通知、失败重试、`updated_seen`、详情并发、摘要并发和已见正文刷新位于 `crawler/notice_processing.py`。
- Audit 与正式扫描共享单次运行 `CachedHttpClient`，成功的列表页和抽样详情响应不会重复请求。

### Storage、Parsing 与 LLM

- SQLite 门面、批量选择、来源写入和通知写入已按事务职责拆分；批量选择按来源和 400 URL 分块，避免逐条查询。
- 原 `parsing/html.py` 已移除，正文、资源、PDFJS、日期和 URL 解析各自独立，无旧兼容入口残留。
- LLM 构造通过 registry 按 provider kind 分派；`app_factory` 不包含 provider 分支，客户端与提示词均按实例缓存。
- 当前最长业务 Python 文件约 233 行，没有重新出现单文件承载完整 Pipeline、Storage 或 HTML 解析的问题。

## 3. 发布与异常链路复核

- 正式日报邮件只在远程 `master` 状态成功发布并完成最终判定后发送，不再出现先发邮件再发现 Git push 失败。
- evaluator、HTML 渲染、正式 Git 发布和最终器失败都会收敛为 `blocked`；blocked 路径上传 Artifact、尝试推送 `bot/failure-snapshots`、渲染告警并最终使 job 失败。
- 快照 Git push 失败不会影响先前 Artifact，告警会提示 Artifact 是可用现场。
- `master_state_updated` 在后续步骤失败时仍保留真实值，避免错误声称远程正式状态未更新。
- emergency fallback 不导入 `notice_push` 或第三方包；即使正常合同模块无法导入，也能写出完整 blocked Actions 输出。

## 4. JSON 与硬编码策略

- `publication.json`、正常/失败 run summary、正式 Git 发布结果和快照发布结果使用 Pydantic 进行序列化、反序列化与结构校验。
- 合同拒绝未知字段、错误基础类型和负数计数，并通过 `schema_version` 标识结构版本。
- SQLite 附件和媒体 JSON 使用 Pydantic `TypeAdapter` 校验读取；写入保留标准库稳定键排序，因为其字节表示参与历史 `content_hash`。
- emergency fallback 使用标准库 JSON 是有意的故障隔离例外，其产物会在正常模块可用时接受 `PublicationManifest` 校验。
- 生产通知源 URL、LLM endpoint、模型名和业务策略只存在于 `resources/config/runtime.yml`；Python 包中未发现对应生产值回退。

## 5. 验证结果

在 `spider` conda 环境中执行：

```text
pytest -q --basetemp .tmp/pytest-task14-final-3       287 passed
python -m compileall -q notice_push scripts           passed
python -m notice_push --doctor --state-path .tmp/...  passed
git diff --check                                      passed
```

此外已单独验证 workflow YAML 可解析，结构测试覆盖 Shell 行数、Git helper 边界、最终 publication 输出来源和标准库 fallback 导入约束。

## 6. 剩余风险

- 本地测试不能验证 GitHub Environment 权限、真实远程 push 和 SMTP 投递，合并后仍应手动触发一次 `workflow_dispatch` 验收成功路径。
- 来源 fixture 能防止已知 DOM 回归，但源站未来改版仍依赖运行时 audit 和失败快照发现；新增来源时必须同步 fixture 合同。
- 本轮没有执行真实网络或真实 LLM smoke，避免污染生产 SQLite 和产生 API 成本；媒体下载与模型调用由隔离单元测试覆盖。
- `resources/notice_records.csv` 的既有工作区修改不属于本轮任务，复审和后续提交都应继续排除，除非用户明确要求纳入。

## 7. 审批建议

当前 Task 1-14 可进入用户审批检查点。建议审批时重点查看 `daily_report.yml` 的状态机、`docs/architecture.md` 的模块边界，以及本文件第 6 节剩余风险；批准后再决定提交与推送。
