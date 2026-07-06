# 功能与健壮性修复计划

## Summary

修复上一轮审查发现的功能风险：已见通知正文更新后不重新摘要、失败重试语义过粗、Kimi PDF 上传/抽取缺少重试、backfill 缺少硬兜底、PDFJS 解析偏窄、`.env` 加载不稳定，以及 LLM 工厂仍硬编码 provider。执行时不提交、不推送，除非另行要求。

## Key Changes

- **已见通知更新重新摘要**
  - `refresh_seen_details` 发现正文变化后，同轮生成新的 `PreparedNotice` 并进入摘要流程。
  - 若运行中断后留下 `updated_seen` 状态，下次运行也会重新进入摘要队列。
  - 新增 `updated_count`，同步输出到 CLI、Markdown 运行概览、run summary JSON、GitHub Actions 元数据。

- **失败重试策略收紧**
  - 新增 failure retry helper：`unsupported_video_content` 作为永久不可重试失败。
  - 网络、超时、429、LLM/API 临时错误继续遵循 profile 的 `failed_retry_limit` 与 `failed_retry_after_hours`。
  - 补充分类型：API key 缺失、Kimi 文件处理失败、媒体下载失败，用于 run summary 和人工排查。

- **Kimi PDF/图片链路增强**
  - 抽出通用 `call_with_retry`，让 chat、PDF 文件上传、PDF 文件抽取都使用同一套指数退避。
  - `files.create` 与 `files.content` 显式传入 `timeout=self.timeout`。
  - 保持远端文件删除和本地临时文件清理为 best-effort，但不会吞掉主流程失败原因。

- **backfill 与解析鲁棒性**
  - `backfill.max_pages_per_source` 默认设为 `80`，同时保留 `lookback_days: 365` 作为主要截断条件。
  - PDFJS 解析支持 `file=xxx.pdf?token=...`、脚本参数中带 query 的 PDF URL。
  - `.env` 固定从项目根目录加载：`load_dotenv(root / ".env")`。

- **LLM provider 架构**
  - `runtime.yml` 中每个 provider 增加 `kind`：`openai_text` 或 `kimi_multimodal`。
  - `app_factory` 改为遍历 provider 配置，通过 registry 构造 summarizer。
  - `SummarizerRouter` 改为接收 `provider_id -> summarizer` 字典，不再写死 deepseek/kimi。
  - 配置加载时校验 `llm.routing` 指向已定义 provider，未知 provider 或未知 kind 直接报配置错误。

## Public Interfaces

- CLI 新增输出行：`updated_count=<int>`。
- run summary JSON 新增字段：`updated_count`。
- Markdown 报告运行概览新增：`正文更新通知`。
- `resources/config/runtime.yml` 的 `llm.providers.*` 新增必填/默认字段 `kind`。
- `.env.example` 不新增业务配置，仍只保留 API key 与模型名。

## Test Plan

- `tests/notice_push/test_pipeline.py`
  - 已见通知正文变化后，同轮重新摘要并生成报告。
  - `updated_seen` 遗留状态在下次运行中进入摘要队列。
  - `unsupported_video_content` 不再被重试。
  - 临时失败仍按 retry limit 重试。

- `tests/notice_push/test_summarizer.py`
  - Kimi `files.create` 失败后按指数退避重试。
  - Kimi `files.content` 失败后按指数退避重试。
  - 文件上传/抽取调用携带 timeout。
  - 失败时本地临时文件仍被清理。

- `tests/notice_push/test_config_models.py`
  - provider `kind` 从 YAML 读取。
  - routing 指向未知 provider 时抛出明确错误。
  - backfill 默认最大页数为 80。

- `tests/notice_push/test_html_utils.py`
  - PDFJS URL 带 query 时仍能识别 PDF。
  - `showVsbpdfIframe(...)` 参数带 query 时仍能提取 PDF。

- `tests/notice_push/test_cli.py` 与 `tests/scripts/test_ci_workflow.py`
  - CLI 打印 `updated_count`。
  - GitHub Actions 解析并传递 `updated_count`。

- 最终验证命令：
  - `conda run --no-capture-output -n spider pytest -q`
  - `conda run --no-capture-output -n spider python -m compileall -q notice_push`
  - `conda run --no-capture-output -n spider python -m notice_push --doctor --state-path .tmp\review-doctor.sqlite3`

## Assumptions

- backfill 默认兜底最大翻页数采用已确认的 `80` 页。
- 本批次只把 `unsupported_video_content` 视为永久不可重试，避免误伤后续补 key、源站恢复、代码修复后的重跑能力。
