# 新增通知源指南

本文档用于给 `SHU-Notice-Push` 增加新的通知源。新增来源时，请优先复用现有 `src.notice_push` 分层：`runtime.yml` 负责配置，`sources/` 下的 Adapter 负责解析，pipeline 负责抓取、详情、摘要和报告。

## 1. 在 runtime.yml 添加来源

在 [resources/config/runtime.yml](../resources/config/runtime.yml) 的 `sources` 下增加一个 source id：

```yaml
sources:
  new_source:
    name: 新通知源名称
    base_url: https://example.shu.edu.cn/
    list_url: https://example.shu.edu.cn/notices.htm
    adapter: src.notice_push.sources.new_source.NewSourceAdapter
    enabled: true
```

字段要求：

- `name`：日报和告警里展示的来源名。
- `base_url`：源站根地址，用于解析相对链接。
- `list_url`：通知目录页地址。
- `adapter`：Adapter 的 Python import path。
- `enabled`：是否默认参与 daily/backfill。

## 2. 实现 Adapter

在 `src/notice_push/sources/` 下新增文件，例如 `new_source.py`，实现 `NoticeSourceAdapter`：

```python
from __future__ import annotations

from bs4 import BeautifulSoup

from src.notice_push.html_utils import clean_text
from src.notice_push.models import NoticeDetail, NoticeListItem
from src.notice_push.sources.base import NoticeSourceAdapter


class NewSourceAdapter(NoticeSourceAdapter):
    def parse_list_page(self, html: str, page_url: str) -> list[NoticeListItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[NoticeListItem] = []
        for anchor in soup.select("a[href]"):
            title = clean_text(anchor.get_text())
            if not title:
                continue
            url = self._absolute_url(anchor["href"], page_url)
            items.append(
                NoticeListItem(
                    source_id=self.source.id,
                    url=url,
                    canonical_url=url,
                    title=title,
                )
            )
        return items

    def parse_detail(self, html: str, item: NoticeListItem) -> NoticeDetail:
        return self.detail_parser.parse(
            html=html,
            item=item,
            content_selector=".v_news_content",
        )
```

实现要点：

- `parse_list_page()` 只负责从目录页提取通知条目，不用在这里做摘要。
- `parse_detail()` 必须进入详情页正文，不能用目录页摘要代替正文。
- `canonical_url` 应尽量稳定，用于 SQLite 去重。
- 如果源站分页按钮不是通用的“下页”，重写 `find_next_page_url()`。
- PDF、图片、视频等正文主体交给 `DetailParser` 识别；必要时补源站专用选择器。

## 3. 添加 fixture 和测试

fixture 放在：

```text
tests/fixtures/source_pages/
```

命名约定：

```text
<source_id>_list.html
<source_id>_detail.html
<source_id>_next_page.html
<source_id>_pdf_detail.html
<source_id>_image_detail.html
<source_id>_video_detail.html
```

至少覆盖：

- 目录页解析：能解析标题、URL、发布时间。
- 详情页解析：正文来自详情页主体。
- 翻页解析：能找到下一页，或明确返回 `None`。
- PDF/图片/视频：如果源站存在此类通知，必须保留对应 fixture。
- 空结构/改版保护：目录页解析不到条目时，source audit 应能暴露问题。

建议把真实页面保存为 HTML fixture 后再写测试，不要让单元测试依赖公网实时页面。

## 4. 本地验证命令

新增或调整来源后，至少运行：

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_sources.py -q
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q src
```

需要做真实抓取 smoke test 时，请使用隔离状态库，避免污染真实数据：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --dry-run --source new_source --state-path .tmp/new-source-smoke/state.sqlite3 --output-dir .tmp/new-source-smoke/results
```

提交前再运行 doctor：

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --doctor
```
