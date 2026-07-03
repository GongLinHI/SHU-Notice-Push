# SHU Notice Push

上海大学通知爬取、正文摘要与邮件推送工具。项目会扫描多个上海大学通知源，进入详情页抓取正文，按正文类型路由到 DeepSeek 或 Kimi 生成结构化摘要，并通过 GitHub Actions 自动发送每日邮件。

## 功能特色

- **多通知源**：默认支持上海大学官网、上海大学管理学院、上海大学研究生院。
- **正文级摘要**：目录页只用于发现通知，摘要基于详情页正文和附件信息生成。
- **多模型路由**：文本通知默认走 DeepSeek，PDF 和图片正文默认走 Kimi K2.7 Code；视频正文会明确标记为暂不支持，进入人工复核。
- **GitHub Actions 自动运行**：每天北京时间 1:00 自动扫描，也支持手动触发。
- **SQLite 状态管理**：记录已见通知、详情内容、摘要结果和失败重试状态，避免重复推送。
- **双运行档位**：`daily` 用于日常增量运行，`backfill` 用于补历史或漏跑场景。
- **可配置并发与重试**：详情抓取、LLM 摘要、HTTP 超时、失败重试都集中在 YAML 中管理。
- **运行异常告警**：源站访问异常会单独发送运行告警邮件，不混入每日通知日报。

## 通知源

当前默认启用 3 个来源：

| source id | 来源 | 目录页 |
| --- | --- | --- |
| `shu_official` | 上海大学官网 | <https://www.shu.edu.cn/tzgg.htm> |
| `management_school` | 上海大学管理学院 | <https://ms.shu.edu.cn/syzl/zytz.htm> |
| `graduate_school` | 上海大学研究生院 | <https://gs.shu.edu.cn/xwlb/sy.htm> |

通知源配置位于 [resources/config/runtime.yml](resources/config/runtime.yml)。

## Quick Start: GitHub Actions

这个项目的主要使用方式是 fork 后交给 GitHub Actions 定时运行。除非你要调试解析逻辑、修改提示词或开发新通知源，一般不需要长期在本地运行。

### 1. Fork 项目

在 GitHub 上 fork 本仓库到你的账号下，然后进入 fork 后的仓库。

### 2. 创建 GitHub Actions Environment

本项目的 workflow 运行在 Ubuntu runner 上，并绑定了 GitHub Actions Environment：

```yaml
runs-on: ubuntu-latest
environment: Ubuntu-Python
```

进入 `Settings` -> `Environments`，创建名为 `Ubuntu-Python` 的 environment。名称需要和 [.github/workflows/daily_report.yml](.github/workflows/daily_report.yml) 中保持一致。

### 3. 配置 Environment Secrets

进入 `Settings` -> `Environments` -> `Ubuntu-Python`，在 `Environment secrets` 中添加以下 secrets：

| Secret | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key，用于文本通知摘要 |
| `DEEPSEEK_MODEL` | 可选，文本摘要模型名，默认 `deepseek-v4-flash` |
| `KIMI_API_KEY` | Kimi API Key，用于 PDF 和图片正文摘要 |
| `KIMI_MODEL` | 可选，多模态摘要模型名，默认 `kimi-k2.7-code` |
| `MAIL_SERVER_ADDRESS` | SMTP 服务器 |
| `MAIL_SERVER_PORT` | SMTP 端口 |
| `MAIL_USERNAME` | SMTP 用户名和发件人 |
| `MAIL_PASSWORD` | SMTP 密码 |
| `MAIL_TO` | 收件人 |

### 4. 启用 GitHub Actions

进入 `Actions` 页面，启用 workflow。可以等待定时运行，也可以手动执行 `Daily Report` 的 `workflow_dispatch`。

触发方式：

- 定时：每天 UTC 17:00，即北京时间 1:00。
- 手动：在 Actions 页面点击 `Daily Report` -> `Run workflow`。

### 5. 查看运行结果

每次运行后，workflow 会：

1. 执行 `python -m src.notice_push --profile daily`。
2. 如果发现新通知或需要人工复核的失败通知，生成 `resources/results/YYYY-MM-DD.md`。
3. 使用 `pandoc` 和 [resources/templates/daily_report.html](resources/templates/daily_report.html) 渲染 HTML 邮件。
4. 发送每日通知邮件。
5. 如果源站访问异常或 pipeline 异常，发送单独的运行异常告警邮件。
6. 提交更新后的 SQLite 状态库和 Markdown 日报。

没有新通知且没有需要人工复核的失败通知时，通常不会发送每日通知邮件；源站异常只会进入运行异常告警。

## 配置

主要配置文件：

- [resources/config/runtime.yml](resources/config/runtime.yml)：业务配置、通知源、运行档位。
- [resources/prompts/notice_summary_v1.md](resources/prompts/notice_summary_v1.md)：摘要提示词。
- [.env.example](.env.example)：本地环境变量示例，只保留 API Key 和模型名。

`.env` 和 GitHub Secrets 只负责密钥及模型名。通知源、页数、并发、超时、重试等业务参数请放在 `runtime.yml`。

### 模型路由

默认模型配置在 `runtime.yml` 的 `llm` 下：

```yaml
llm:
  providers:
    deepseek:
      default_model: deepseek-v4-flash
    kimi:
      default_model: kimi-k2.7-code
  routing:
    text: deepseek
    pdf: kimi
    image: kimi
```

`.env` 或 GitHub Secrets 中的 `DEEPSEEK_MODEL`、`KIMI_MODEL` 可覆盖默认模型名。`deepseek-chat` 与 `deepseek-reasoner` 将于北京时间 2026-07-24 23:59 弃用；新配置建议直接使用 `deepseek-v4-flash`。

视频正文目前只做检测和失败分类，不会调用 LLM 摘要。

### 运行档位

运行档位在 `runtime.yml` 的 `profiles` 下配置。

#### daily

用于 GitHub Actions 日常增量运行：

- 默认每个来源最多扫描 5 页。
- 连续 2 页没有可处理通知后提前停止。
- 默认只处理近 365 天通知。
- 详情抓取并发为 2，摘要并发为 3。
- 到期失败通知会自动重试。

#### backfill

用于补历史或漏跑：

- 不设置固定页数上限，但仍受 `lookback_days: 365` 约束。
- 详情抓取并发为 4，摘要并发为 3。
- 会刷新部分已见通知详情，适合修复早期状态或补充详情内容。

## 本地开发与测试

本地运行主要用于调试、开发新通知源、修改提示词或验证 GitHub Actions 前的行为。

### 1. 准备环境

推荐使用 Python 3.12。项目当前在 `spider` conda 环境中开发和测试：

```powershell
conda create -n spider python=3.12
conda activate spider
pip install -r requirements.txt
```

如果已经存在 `spider` 环境，可以直接安装依赖：

```powershell
conda run --no-capture-output -n spider pip install -r requirements.txt
```

### 2. 配置本地环境变量

复制环境变量示例文件：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_MODEL=deepseek-v4-flash
KIMI_API_KEY=your_kimi_api_key_here
KIMI_MODEL=kimi-k2.7-code
```

### 3. 试运行

不写入 SQLite 和报告，只验证抓取解析流程：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --dry-run --profile daily
```

运行日常档位：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --profile daily
```

运行补历史/漏跑档位：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --profile backfill
```

只运行某个通知源：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --source shu_official
```

指定日期和输出目录：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --date 2026-07-01 --output-dir resources/results
```

可以通过 CLI 临时覆盖部分参数：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --profile daily --max-pages-per-source 2 --detail-max-workers 1
```

## 输出文件

默认输出位置：

- SQLite 状态库：`resources/notice_state.sqlite3`
- Markdown 日报：`resources/results/YYYY-MM-DD.md`
- GitHub Actions 渲染的 HTML：`resources/results/html/YYYY-MM-DD.html`

## 添加新通知源

通常需要：

1. 在 `runtime.yml` 的 `sources` 中添加来源配置。
2. 在 `src/notice_push/sources/` 下实现新的 Adapter。
3. 为目录页解析、详情页解析和翻页逻辑添加测试。
4. 根据需要调整提示词和日报模板。

## 开发命令

运行完整测试：

```powershell
conda run --no-capture-output -n spider pytest -q
```

编译检查：

```powershell
conda run --no-capture-output -n spider python -m compileall -q src
```

清理空日报文件：

```powershell
conda run --no-capture-output -n spider python scripts/clean_empty_results.py
```

## 项目结构

```text
src/notice_push/
  __main__.py          CLI 入口
  config.py            YAML 和环境变量加载
  pipeline.py          抓取、详情解析、摘要、报告主流程
  storage.py           SQLite 状态管理
  summarizer.py        LLM 摘要客户端与模型路由
  media.py             PDF/图片下载与转换
  report.py            Markdown 日报渲染
  sources/             各通知源 Adapter

resources/
  config/runtime.yml   运行配置
  prompts/             摘要提示词
  templates/           HTML 邮件模板
  results/             日报输出

tests/
  notice_push/         主流程、配置、存储、通知源测试
  scripts/             脚本测试
```
