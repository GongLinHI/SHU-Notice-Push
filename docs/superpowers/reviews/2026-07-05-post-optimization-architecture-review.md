# SHU Notice Push 后续架构审查

审查日期：2026-07-05

审查范围：

- 已完成第一批和剩余优化后的 `src.notice_push` 当前实现。
- `src/notice_push/pipeline.py`、`storage.py`、`summarizer.py`、`config.py`、`html_utils.py`、三个 source adapter、GitHub Actions 日常链路。
- 不审查旧 `src/spider` / `src/entry` 源码，因为它们已在工作树中删除。

## 总体判断

上一轮优化已经解决了生产韧性和迁移债务中的大块问题：LLM Key 懒加载、媒体资源可见、SQLite 媒体元数据、WAL/write lock、新增/重试计数拆分、旧入口删除、解析规则 YAML 化都已经落地。

当前代码可以继续运行，但如果目标是“后续更容易增加通知源、增加正文类型、调整 LLM 和提示词”，还应继续做一轮架构收口。重点不是加新功能，而是把已经长大的模块拆成更明确的边界，减少隐藏全局状态和统计口径分叉。

## Findings

### P0：Markdown 报告正文仍用旧的新增统计口径

位置：

- `src/notice_push/report.py:21`
- `src/notice_push/report.py:32`
- `src/notice_push/pipeline.py:240`
- `.github/workflows/daily_report.yml:147`

问题：

`PipelineResult` 已经有 `new_count`、`retried_count`、`manual_review_count`，CLI 和邮件标题也使用这些值。但 `render_report()` 仍然只接收 `entries` 和 `failures`，并写出 `新增通知: len(entries) + len(failures)`。如果当天只是历史失败通知重试成功，报告正文仍会显示新增通知，这和邮件标题、HTML 元数据不一致。

影响：

- 用户打开 Markdown/HTML 正文时会看到旧口径。
- 后续自动分析历史报告时，`运行概览` 不是可信统计源。

建议：

- 引入 `ReportStats` 或复用 `PipelineResult` 中的统计字段。
- `render_report()` 显式接收 `new_count`、`retried_count`、`summarized_count`、`manual_review_count`。
- 按来源统计也要区分 `new/retry`，至少不要把 retry 写成新增。

### P1：运行时仍保留 CSV 迁移兼容链路

位置：

- `src/notice_push/pipeline.py:124`
- `src/notice_push/storage.py:398`
- `tests/notice_push/test_storage.py:273`

问题：

旧 `src/spider` / `src/entry` 已删除，但 pipeline 每次非 dry-run 仍调用 `migrate_legacy_csv(resources/notice_records.csv)`。这属于旧 CSV 状态兼容逻辑，和当前“SQLite 是唯一运行状态”的目标不一致。

影响：

- 新读者会误以为 `notice_records.csv` 仍是运行链路的一部分。
- 工作树里这个文件经常处于 modified 状态，继续把它放在主链路中会制造维护噪声。
- 每次运行都重复扫描旧 CSV，虽然成本不高，但语义不干净。

建议：

- 删除自动迁移调用和 `NoticeStorage.migrate_legacy_csv()`。
- 如果还需要保留历史导入能力，改成单独脚本或文档中的一次性迁移步骤，而不是 pipeline 默认行为。

### P1：`NoticePipeline.run()` 参数和职责过重

位置：

- `src/notice_push/pipeline.py:55`
- `src/notice_push/pipeline.py:76`
- `src/notice_push/pipeline.py:124`
- `src/notice_push/pipeline.py:240`

问题：

`NoticePipeline.run()` 同时负责 profile 默认值合并、源选择、分页扫描、新/重试选择、详情并发抓取、失败记录、摘要并发、已见详情刷新、报告渲染和输出。参数数量也较多，CLI 需要把 profile 展平成一长串关键字参数。

影响：

- 新增 profile 配置或运行模式时，CLI、pipeline、测试都要同步改很多地方。
- 单元测试需要造很大的 FakePipeline/FakeAdapter，导致测试文件膨胀。
- 后续如果加入更多正文类型或失败策略，pipeline 会继续变胖。

建议：

- 新增 `PipelineRunOptions`，把运行参数收束成一个对象。
- 新增 `PipelineCounters` / `PipelineRunStats`，统一统计口径。
- 把“扫描单个 source”拆成 `_run_source()`，返回 `SourceRunResult`。

### P1：解析规则通过模块级全局状态注入

位置：

- `src/notice_push/html_utils.py:52`
- `src/notice_push/__main__.py:43`
- `tests/notice_push/test_html_utils.py:100`

问题：

`configure_parsing()` 修改 `html_utils` 的模块级全局变量。当前单进程 CLI 能工作，但它让配置生效依赖 build 顺序，也让测试必须 finally 恢复默认状态。

影响：

- 多配置测试或未来多 pipeline 实例并存时容易相互污染。
- source adapter 表面上没有依赖解析配置，实际依赖了全局状态。

建议：

- 引入 `HtmlParsingRules` / `DetailParser` 对象。
- adapter 初始化时接收 parser 或 parsing config。
- `html_utils` 保留纯函数默认参数，不再需要运行时全局配置。

### P1：三个详情页 adapter 重复同一套正文解析流程

位置：

- `src/notice_push/sources/shu_official.py:33`
- `src/notice_push/sources/management_school.py:39`
- `src/notice_push/sources/graduate_school.py:34`

问题：

三个 adapter 的 `parse_detail()` 都重复了：选择主内容、提取 assets、提取正文、推断 content_kind、提升 primary assets。不同点主要是标题和发布时间选择器，以及研究生院外部视频页面的特殊处理。

影响：

- 新增第四个通知源时容易复制粘贴。
- PDF/图片/视频解析规则调整时需要检查多个 adapter。

建议：

- 抽出 `DetailParser.parse(...)` 或 `parse_common_detail_parts(...)`。
- adapter 只负责 source-specific 的 list 解析、title/date 元信息和少量特殊规则。

### P2：LLM 摘要层仍混合了 prompt、重试、OpenAI SDK、媒体下载和 Kimi 文件生命周期

位置：

- `src/notice_push/summarizer.py:62`
- `src/notice_push/summarizer.py:149`
- `src/notice_push/summarizer.py:315`

问题：

`summarizer.py` 已经承担文本摘要、PDF 上传/解析、图片 base64、OpenAI SDK 调用、指数退避、prompt 渲染、资源渲染和路由。它还能维护，但随着更多 provider 或模型策略加入，会继续膨胀。

影响：

- 新增第三个 LLM provider 时会复制 retry/chat 逻辑。
- 单元测试 fake client 类型越来越多。

建议：

- 抽出共享的 `chat_with_retry()` 或 `OpenAIChatClient` 包装层。
- 把 `visible_notice_resources()` 这类报告/prompt 共享展示逻辑移到独立模块，例如 `resources.py`。
- 保持 `NoticeSummarizer` / `KimiMultimodalSummarizer` 只负责“如何组织消息”。

### P2：SQLite detail 更新 SQL 重复度偏高

位置：

- `src/notice_push/storage.py:208`
- `src/notice_push/storage.py:265`

问题：

`save_detail()` 与 `update_seen_detail_if_changed()` 都在组装 `assets_json`、`attachments_json`、`content_hash`，并写入同一组 detail 字段。差异主要在状态转移。

影响：

- 后续 detail 字段增加时容易漏改一个分支。

建议：

- 引入内部 `_detail_values(detail)`，返回统一字段字典。
- 或引入 `_update_detail_columns(conn, notice_id, detail, status_sql_fragment)` 之类的内部 helper。

## 建议后续优化轮次

### Round 1：统计口径和旧迁移收口

- 修正 Markdown 报告统计口径。
- 移除自动 CSV 迁移链路，让 SQLite 成为唯一运行状态。
- 清理对应测试和文档引用。

### Round 2：pipeline 与解析边界整理

- 引入 `PipelineRunOptions` 和 `PipelineRunStats`。
- 拆分 `_run_source()`，降低 `NoticePipeline.run()` 复杂度。
- 抽出 `DetailParser`，让 source adapter 少写重复 detail 解析代码。
- 去掉 `configure_parsing()` 运行时全局状态。

### Round 3：LLM 和资源展示层整理

- 抽出资源展示 helper 到独立模块。
- 抽出 OpenAI-compatible chat retry helper。
- 让文本/Kimi summarizer 只负责构造消息和处理 provider-specific 文件能力。

## 验证建议

每轮完成后至少运行：

```powershell
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q src
```

每轮都不应提交或推送，除非用户明确要求。
