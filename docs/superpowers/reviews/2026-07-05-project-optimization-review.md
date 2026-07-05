# SHU Notice Push 项目级代码审查与优化建议

审查日期：2026-07-05

审查范围：

- 当前 `src/notice_push` 新架构实现。
- `rebuild.md` 中的重构目标。
- `docs/superpowers/plans/2026-07-03-multimodal-llm-routing.md` 中的多模态 LLM 路由目标。
- GitHub Actions 日常运行链路。
- 旧 `src/spider` 兼容层。

验证记录：

- `conda run -n spider pytest tests/notice_push -q --basetemp .tmp/pytest-review`：84 passed。
- `conda run -n spider pytest -q --basetemp .tmp/pytest-review-all`：98 passed。
- 直接使用默认 `pytest.ini` 的 `--basetemp=.pytest_tmp` 在本机出现 Windows 权限清理错误；换到 `.tmp/...` 后测试通过。

## 总体结论

当前重构方向是正确的：项目已经从单体 spider 迁移到“配置加载、源站适配器、HTTP、SQLite、Pipeline、LLM Summarizer、Report、GitHub Actions”分层架构。三类通知源、分页、详情页抓取、失败重试、SQLite 状态、多模型路由都已经具备基本实现。

没有发现会让日常文本通知推送必然不可用的 Critical 问题。但多模态链路和生产运维韧性还没有完全收口，建议在下一轮修复中优先处理“凭据懒加载、媒体元数据可见与可追溯、测试临时目录稳定性、SQLite 并发写入边界”。

## 做得好的地方

- 架构分层清楚，新增通知源主要落在 `src/notice_push/sources/` 适配器和 `runtime.yml` 配置。
- `resources/config/runtime.yml` 已承载核心运行配置，符合后续调页数、并发、重试、模型路由的需要。
- 详情页正文是摘要输入主体，没有再用目录摘要替代正文。
- SQLite 已承担来源、通知、摘要、失败状态和重试状态。
- `HttpClient` 已支持线程本地 session、超时、重试和编码推断。
- DeepSeek 文本摘要与 Kimi PDF/图片摘要已通过 `SummarizerRouter` 分流。
- GitHub Actions 已区分每日通知邮件和运行异常告警邮件。
- 单元测试覆盖较多核心路径，离线测试可通过。

## 需要审批的优化项

### P0：让 dry-run / bootstrap 不再强制要求 DeepSeek Key

位置：

- `src/notice_push/__main__.py:48`
- `src/notice_push/llm.py:26`

问题：

当前 `build_pipeline()` 对 DeepSeek 使用 `resolve_provider()`，这会在 pipeline 构建阶段强制要求 `DEEPSEEK_API_KEY`。因此即使只是 `--dry-run`、`--bootstrap-seen`、或者未来只想跑解析检查，也会在未配置 DeepSeek Key 时失败。

影响：

- 本地“只验证爬取和解析”不够轻量。
- 新用户 quick start 容易在还没测试源站解析前就卡在 LLM Key。
- 和 Kimi 已经改成懒要求的行为不一致。

建议：

- 新增统一的 `LLMProviderResolver` 或直接让 DeepSeek 也使用 optional provider。
- 真正调用 `NoticeSummarizer._get_client()` 时再检查 `DEEPSEEK_API_KEY`。
- 为 CLI 增加测试：无 DeepSeek Key 时，`--dry-run --limit 1` 可以构建 pipeline；真实摘要调用仍然报清晰错误。

审批建议：

- 优先修。

### P0：把 PDF/图片资产作为用户可见链接输出

位置：

- `src/notice_push/sources/management_school.py:44`
- `src/notice_push/sources/shu_official.py:38`
- `src/notice_push/summarizer.py:33`
- `src/notice_push/report.py:53`

问题：

当前 PDF/图片被放进 `detail.assets`，但 report 和 prompt 中“附件”主要读取 `detail.attachments`。研究生院适配器会把部分 asset 转成 attachment，但管理学院、官网适配器没有统一转换。结果是 PDF/图片正文虽然可以被 Kimi 处理，但邮件报告中可能不展示原始 PDF/图片链接。

影响：

- 用户收到摘要后难以回到原始 PDF/图片核对。
- 人工复核失败项时信息不完整。
- 多模态摘要的可追溯性不足。

建议：

- 统一一个用户可见资源模型，或在 report/prompt 中合并 `attachments + assets`。
- PDF、图片、普通附件都应展示名称、URL、类型。
- 对图片正文，报告中至少展示“图片正文链接”；不建议把图片直接嵌入邮件。

审批建议：

- 优先修。

### P0：SQLite 持久化 content_kind / assets / attachments

位置：

- `src/notice_push/models.py:53`
- `src/notice_push/storage.py:34`
- `src/notice_push/storage.py:186`

问题：

运行时模型已有 `content_kind`、`assets`、`attachments`，但 SQLite 只保存 `content`、`content_hash` 和摘要状态，没有保存媒体正文类型和资源列表。

影响：

- PDF/图片摘要生成后，无法仅凭状态库追踪当时使用了哪个文件或图片。
- 源站页面变化后，历史摘要难以审计。
- 后续要做失败重放、成本统计、按正文类型统计时数据不足。

建议：

- 在 `notices` 表增加：
  - `content_kind text not null default 'text'`
  - `assets_json text not null default '[]'`
  - `attachments_json text not null default '[]'`
- `save_detail()` 同步保存这些字段。
- `_ensure_notice_columns()` 负责旧库迁移。
- 对 `content_hash` 计算加入 `content_kind + assets_json`，避免 PDF/图片正文变更但纯文本 content 仍为空时无法感知。

审批建议：

- 优先修。

### P1：解决默认 pytest 临时目录不稳定

位置：

- `pytest.ini:3`

问题：

`pytest.ini` 固定 `--basetemp=.pytest_tmp`。本机这次运行时 pytest 清理该目录出现 Windows `PermissionError`，导致大量测试在 setup 阶段失败。改用 `.tmp/pytest-review` 后同一套测试通过。

影响：

- 默认 `pytest -q` 偶发失败会降低验证信心。
- Windows 本地开发体验不稳定。

建议：

- 把 `pytest.ini` 改为 `--basetemp=.tmp/pytest`。
- 或移除固定 `--basetemp`，让 pytest 使用系统临时目录。
- 保持 `.tmp/` 在 `.gitignore` 中。

审批建议：

- 建议和 P0 一起修，成本很低。

### P1：SQLite 并发写入边界需要收紧

位置：

- `src/notice_push/pipeline.py:313`
- `src/notice_push/pipeline.py:370`
- `src/notice_push/storage.py:402`

问题：

详情抓取和摘要处理都使用 `ThreadPoolExecutor`。当前每个 storage 方法都会新建 SQLite 连接，SQLite 可以处理一定并发，但 Windows 和 GitHub Actions 上仍可能遇到 `database is locked`。尤其是 future 里直接调用 `_fetch_and_store_detail()`，其中包含 `upsert_seen_item()`、`save_detail()`、`mark_failed()` 等写操作。

影响：

- 并发调高或源站失败重试多时，可能出现偶发数据库锁。
- 一旦锁发生，会被当成通知失败写入，造成误报。

建议：

- 将“网络抓取/LLM 调用”并发化，“SQLite 写入”集中回主线程串行提交。
- 或在 `NoticeStorage` 内加写锁，并设置 `PRAGMA journal_mode=WAL`、`PRAGMA busy_timeout`。
- 短期建议先加写锁和 WAL；长期再拆成 fetch outcome -> main thread persist。

审批建议：

- 建议修。

### P1：临时媒体下载失败时可能遗留空文件

位置：

- `src/notice_push/media.py:13`

问题：

`download_asset_to_temp()` 先创建临时文件，再调用 `http_client.get_bytes()`。如果下载失败，函数会抛异常，但已创建的临时文件不会被清理。

影响：

- backfill 或源站不稳定时可能积累临时垃圾文件。
- 本地运行更明显，GitHub Actions 单次 runner 影响较小。

建议：

- 先下载 bytes，再创建并写入临时文件。
- 或在 `except` 中 unlink 已创建 path。

审批建议：

- 建议修，成本很低。

### P1：混合“文本 + 视频”的页面会被过早归类为视频

位置：

- `src/notice_push/html_utils.py:247`

问题：

`infer_content_kind()` 只要发现 video/external_video，就优先返回 `video`，即使页面同时有足够文本正文。

影响：

- 有些新闻页可能有文字报道和视频，当前会跳过 DeepSeek 文本摘要，进入 unsupported video。

建议：

- 优先判断是否有足够正文文本。
- 只有正文为空或仅为资产标签时，再按 PDF、图片、视频判断。

审批建议：

- 建议修。

### P1：新增数与重试数应分开统计

位置：

- `src/notice_push/pipeline.py:189`
- `.github/workflows/daily_report.yml:158`

问题：

`new_count += len(selected_items)` 会把 retryable failed notice 也计入新增通知。邮件标题 `新增 N 条` 在失败重试场景可能夸大“新增”数量。

影响：

- 用户看到的每日新增数不够准确。
- 后续判断“今天是否真有新通知”会混入历史失败重试。

建议：

- 在 storage 过滤时区分 `is_new` 与 `is_retry`。
- `PipelineResult` 增加 `retried_count`、`manual_review_count`。
- GitHub Actions 邮件标题仍用真实新通知数，报告概览展示重试数。

审批建议：

- 建议修。

### P2：清理旧 spider 兼容层的维护债务

位置：

- `src/spider/deepseek.py:14`
- `src/spider/deepseek.py:79`
- `src/spider/notice_getter.py:18`
- `src/spider/Spider.py:1`

问题：

旧 `src/spider` 已大多变成兼容层，但仍保留 `DeepSeekClient` 直接初始化 OpenAI 客户端、CSV 显式去重等旧接口。虽然测试已 fake 掉，不含真实 Key，但长期保留会让维护入口变多。

影响：

- 新贡献者可能误用旧 API。
- 文档和实际推荐入口不完全一致。

建议：

- 如果不再需要兼容旧脚本，删除 `src/spider` 和 `src/entry` 旧链路及对应测试。
- 如果仍需兼容，给旧模块加明确 deprecation 注释，并让所有旧接口只委托 `src.notice_push`。

审批建议：

- 可放到第二轮。

### P2：配置模型仍保留少量历史字段

位置：

- `src/notice_push/models.py:132`
- `src/notice_push/config.py:254`
- `src/notice_push/config.py:297`

问题：

`AppConfig.deepseek_model` 和 `deepseek_model` 旧 YAML 兼容逻辑仍在。短期为了迁移可以理解，但项目现在已经多 provider 化，继续保留会让“模型配置到底在哪里生效”不够干净。

影响：

- 后续新增 provider 时容易继续绕过 `llm.providers`。

建议：

- 等当前稳定后移除 `AppConfig.deepseek_model`。
- 旧 `deepseek_model` 兼容逻辑保留一个版本周期即可，并在 README 或 changelog 中说明。

审批建议：

- 可放到第二轮。

### P2：外部视频域名和图片噪声规则建议配置化

位置：

- `src/notice_push/html_utils.py:46`
- `src/notice_push/html_utils.py:47`

问题：

`EXTERNAL_VIDEO_DOMAINS` 和 `NOISE_IMAGE_MARKERS` 是代码常量。后续如果新增源站或发现新噪声图片，需要改代码。

建议：

- 放到 `runtime.yml` 的 `parsing` 配置中。
- 默认值仍保留在代码中，YAML 可覆盖或追加。

审批建议：

- 可放到第二轮。

## 建议修复顺序

### 第一批：生产韧性修复

- [ ] DeepSeek provider 改为懒加载，dry-run/bootstrap 不要求 API Key。
- [ ] report/prompt 统一展示 `assets + attachments`。
- [ ] SQLite 持久化 `content_kind/assets/attachments`。
- [ ] pytest basetemp 改到 `.tmp/pytest` 或移除固定 basetemp。
- [ ] 媒体临时文件下载失败清理。

验收：

- `conda run -n spider pytest -q`
- `conda run -n spider python -m src.notice_push --dry-run --limit 1` 在无 LLM Key 场景下至少能完成抓取解析路径。
- PDF/图片 fixture 生成的 report 中能看到原始资源链接。

### 第二批：统计与并发稳定性

- [ ] SQLite 写入加锁或改为主线程串行写。
- [ ] SQLite 启用 WAL 和 busy timeout。
- [ ] `new_count` 与 `retried_count` 分离。
- [ ] 混合文本/视频页面优先文本摘要。

验收：

- 并发详情抓取和摘要测试仍通过。
- 历史失败重试不会污染“新增 N 条”的邮件标题。

### 第三批：清理迁移债务

- [ ] 删除或 deprecate 旧 `src/spider` / `src/entry` 链路。
- [ ] 移除 `AppConfig.deepseek_model` 等旧兼容字段。
- [ ] 将外部视频域名、图片噪声规则配置化。

验收：

- README 只推荐 `python -m src.notice_push`。
- 新增第四个通知源仍只需要 YAML 配置和 adapter。

## 建议审批结论

建议批准第一批修复。第一批修复不改变业务目标，只补齐当前多模态架构最薄的环节：凭据懒加载、资源可见性、媒体审计、测试稳定性和临时文件清理。

第二批和第三批可以在第一批稳定后继续做，避免一次改动过大。
