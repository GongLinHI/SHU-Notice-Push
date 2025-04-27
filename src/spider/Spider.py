from datetime import datetime
from pathlib import Path

from src.entry.notice import Notice
from src.spider.notice_getter import NoticeGetter
from src.spider.deepseek import DeepSeekSummary
from src.spider.page_parser import PageParser


class Spider:
    @staticmethod
    def run():
        notice_list = NoticeGetter.get_notice_list()
        parsed_notice_list: list[Notice] = []
        for notice in notice_list:
            # print(f"Title: {notice.title}")
            # print(f"URL: {notice.url}")
            # print(f"Upload Time: {notice.upload_time}")
            # print("-" * 40)
            parsed_notice = PageParser.parse(notice)
            parsed_notice.summary = DeepSeekSummary.get_summary(parsed_notice)
            parsed_notice_list.append(parsed_notice)
            print(parsed_notice.summary)
        today_str = datetime.today().strftime("%Y-%m-%d")
        file_path = Path(__file__).parent.parent.parent.joinpath(f"resources/results/{today_str}.md")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            if parsed_notice_list:
                f.write(f"# {today_str} Notice Summary\n")                for notice in parsed_notice_list:
                    f.write(f"{notice.summary}\n\n")
            else:
                f.write(f"## No new notices found today ({today_str}).\n")


if __name__ == '__main__':
    Spider().run()
