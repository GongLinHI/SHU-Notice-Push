from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

from src.entry.notice import Notice
from src.spider.notice_getter import NoticeGetter
from src.spider.deepseek import DeepSeekSummary
from src.spider.page_parser import PageParser


class Spider:
    @staticmethod
    def run():
        notice_list = NoticeGetter.get_notice_list()
        print(f"Fetched {len(notice_list)} new notices.")
        parsed_notice_list: list[Notice] = []
        for notice in notice_list:
            parsed_notice = PageParser.parse(notice)
            parsed_notice_list.append(parsed_notice)

        # 使用进程池并行获取summary
        pool_size = min(len(parsed_notice_list), 10) if parsed_notice_list else 1
        with ProcessPoolExecutor(max_workers=pool_size) as executor:
            summaries = list(executor.map(DeepSeekSummary.get_summary, parsed_notice_list))

        for notice, summary in zip(parsed_notice_list, summaries):
            notice.summary = summary

        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        file_path = Path(__file__).parent.parent.parent.joinpath(f"resources/results/{today_str}.md")
        print(f"Writing results to {file_path}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            if parsed_notice_list:
                f.write(f"# {today_str} Notice Summary\n")
                for notice in parsed_notice_list:
                    f.write(f"{notice.summary}\n\n")
            else:
                f.write(f"## No new notices found today ({today_str}).\n")


if __name__ == '__main__':
    Spider().run()
