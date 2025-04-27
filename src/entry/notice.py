from datetime import date
from typing import Optional


class Notice:
    brief: bool = True

    def __init__(self, url: str,
                 title: Optional[str] = None,
                 content: Optional[str] = None,
                 upload_time: Optional[date] = None,
                 summary: Optional[str] = None):
        self._url = url
        self._title = title
        self._content = content
        self._upload_time = upload_time if upload_time else date.today()
        self._summary = summary

    # region Getters
    @property
    def url(self) -> str:
        return self._url

    @property
    def title(self) -> Optional[str]:
        return self._title

    @property
    def content(self) -> Optional[str]:
        return self._content

    @property
    def upload_time(self) -> date:
        return self._upload_time

    @property
    def summary(self) -> Optional[str]:
        return self._summary

    # endregion

    # region Setters
    @url.setter
    def url(self, value: str) -> None:
        self._url = value

    @title.setter
    def title(self, value: Optional[str]) -> None:
        self._title = value

    @content.setter
    def content(self, value: Optional[str]) -> None:
        self._content = value

    @upload_time.setter
    def upload_time(self, value: Optional[date]) -> None:
        self._upload_time = value if value else date.today()

    @summary.setter
    def summary(self, value: Optional[str]) -> None:
        self._summary = value

    def __repr__(self):
        if not self.brief:
            return (f"Notice(url={self.url!r}, title={self.title!r}, content={self.content!r}, "
                    f"upload_time={self.upload_time!r}, summary={self.summary!r})")
        # 只打印非None属性
        attrs = []
        if self.url is not None:
            attrs.append(f"url={self.url!r}")
        if self.title is not None:
            attrs.append(f"title={self.title!r}")
        if self.content is not None:
            attrs.append(f"content={self.content!r}")
        if self.upload_time is not None:
            attrs.append(f"upload_time={self.upload_time!r}")
        if self.summary is not None:
            attrs.append(f"summary={self.summary!r}")
        return f"Notice({', '.join(attrs)})"

    class Builder:
        def __init__(self):
            self._url = None
            self._title = None
            self._content = None
            self._upload_time = date.today()
            self._summary = None

        def set_url(self, url: str) -> "Notice.Builder":
            self._url = url
            return self

        def set_title(self, title: Optional[str]) -> "Notice.Builder":
            self._title = title
            return self

        def set_content(self, content: Optional[str]) -> "Notice.Builder":
            self._content = content
            return self

        def set_upload_time(self, upload_time: Optional[date]) -> "Notice.Builder":
            if upload_time is not None:
                self._upload_time = upload_time
            return self

        def set_summary(self, summary: Optional[str]) -> "Notice.Builder":
            self._summary = summary
            return self

        def build(self) -> "Notice":
            if not self._url:
                raise ValueError("URL is required")

            return Notice(
                url=self._url,
                title=self._title,
                content=self._content,
                upload_time=self._upload_time,
                summary=self._summary
            )
