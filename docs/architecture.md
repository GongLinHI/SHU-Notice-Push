# 项目架构

## 运行链路

```text
CLI / GitHub Actions
        |
        v
app_factory -> NoticePipeline
                  |
                  +-> SourceAuditor
                  +-> source_scan.scan_source_pages
                  +-> NoticeProcessor
                  |     +-> detail_fetcher
                  |     +-> refresh_seen
                  |     +-> SummarizerRouter
                  +-> pipeline_result.finalize_pipeline_result
                              |
                              +-> Markdown / run summary / SQLite checkpoint
```

`NoticePipeline` 只负责应用编排。目录分页不访问 SQLite，通知处理不负责生成最终报告，结果装配不抓取网页。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `crawler/source_scan.py` | 目录请求、分页、重复页保护、页数与时间窗口截断 |
| `crawler/notice_processing.py` | 新通知、失败重试、正文更新、详情和摘要协调 |
| `pipeline_result.py` | 计数合并、日报、run summary 和 checkpoint |
| `storage/database.py` | 稳定存储门面与连接生命周期 |
| `storage/selection.py` | 分块批量读取状态并保持输入顺序 |
| `storage/source_repository.py` | `sources` 表写入 |
| `storage/notice_repository.py` | 详情、摘要、失败、baseline 和 checkpoint |
| `parsing/content.py` | 正文选择和文本清洗 |
| `parsing/assets.py` | PDF、图片、视频和附件资源 |
| `parsing/pdfjs.py` | PDFJS viewer 与脚本参数 |
| `parsing/dates.py` | 日期格式 |
| `parsing/urls.py` | URL、文件名和外部视频域名 |
| `llm/registry.py` | provider kind 到 builder 的注册与构造 |
| `llm/summary_format.py` | 摘要规范化、校验和修复 |
| `observability/publication_manifest.py` | 最终发布清单 Pydantic 合同 |
| `observability/run_summary_contract.py` | 正常与 fallback run summary 合同 |

## 配置职责

- `resources/config/runtime.yml`：通知源、profile、HTTP/LLM 参数、路由和业务策略。
- `.env` / GitHub Environment Secrets：API key 和模型名覆盖。
- `resources/prompts/`：可独立更新的摘要提示词。

Python 中不提供生产 URL、模型名或 profile 参数的静默默认值。缺失生产配置应在启动阶段明确失败。

## 新增通知源

1. 在 `runtime.yml` 添加 source。
2. 在 `notice_push/sources/` 实现 Adapter。
3. 在 `tests/fixtures/sources/<source_id>/` 保存最小脱敏页面结构。
4. 增加列表、分页、文本和媒体正文合同测试。

详细约定见 [add-source-guide.md](add-source-guide.md)。

## 新增 LLM Provider

1. 实现 summarizer，构造器只接收解析后的 provider 和依赖，不读取环境变量。
2. 在 `llm/registry.py` 注册新的 builder。
3. 在配置校验允许新的 `kind`，并在 `runtime.yml` 添加 provider/routing。
4. 增加 registry、缺失 key、路由和摘要格式测试。

`app_factory.py` 不应增加 `if provider.kind` 分支。

## JSON 与状态兼容

- workflow 发布清单、run summary 和发布结果使用 Pydantic 进行严格校验。
- 合同带有 `schema_version`，未知字段或错误类型不会被静默接受。
- 最终器故障时的 blocked fallback 仅依赖标准库，确保业务包导入失败时仍能输出完整 Actions 状态；其 JSON 在正常模块恢复后仍由 Pydantic 合同校验。
- SQLite 媒体 JSON 使用 Pydantic 校验读取结构，但继续使用稳定的键排序输出，因为序列化结果参与 `content_hash`。
- SQLite schema 变更必须通过 migration，不得依赖删除并重建真实状态库。
