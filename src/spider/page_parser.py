import requests

from bs4 import BeautifulSoup
from datetime import datetime

from entry.notice import Notice


class PageParser:
    _default_encoding = "utf-8"

    @classmethod
    def parse(cls, notice: Notice) -> Notice:
        """
        请求指定url，解析响应内容，返回包含title、content、upload_time的Notice对象。
        """
        url = notice.url
        response = requests.get(url)
        response.raise_for_status()
        html = response.content.decode(cls._default_encoding)

        soup = BeautifulSoup(html, "html.parser")

        # 解析标题
        h1 = soup.find("h1", align="center")
        title = h1.get_text(strip=True) if h1 else None

        # 解析正文内容，去除多余换行
        content_div = soup.find("div", class_="v_news_content")
        content = None
        if content_div:
            # 提取所有文本段落，去除空行，合并为合理段落
            paragraphs = [
                p.get_text(strip=True)
                for p in content_div.find_all("p")
            ]
            # 去除全空的段落
            paragraphs = [p for p in paragraphs if p and p.strip()]
            content = "\n".join(paragraphs)

        # 解析发布时间
        xx_div = soup.find("div", class_="xx", align="center")
        upload_time = None
        if xx_div:
            text = xx_div.get_text(strip=True)
            # 查找“发布时间：YYYY-MM-DD”
            import re
            m = re.search(r"发布时间[:：]\s*(\d{4}-\d{2}-\d{2})", text)
            if m:
                try:
                    upload_time = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                except Exception:
                    upload_time = None

        return Notice(
            url=notice.url,
            title=title,
            content=content,
            upload_time=upload_time,
        )
