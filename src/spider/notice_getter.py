from pathlib import Path

import requests
from bs4 import BeautifulSoup
from src.entry.notice import Notice
import os
import csv


class NoticeGetter:
    _base_url = "https://www.shu.edu.cn/"
    _notice_list_url = "https://www.shu.edu.cn/tzgg.htm"
    _default_encoding = "utf-8"

    @classmethod
    def fetch_notice_list(cls):
        """
        获取所有通知，返回Notice对象列表
        """
        response = requests.get(cls._notice_list_url)
        response.raise_for_status()
        htmlcontent = response.content.decode(cls._default_encoding)
        soup = BeautifulSoup(htmlcontent, "html.parser")
        ej_main = soup.find("div", class_="ej_main")
        if not ej_main:
            return []
        ul = ej_main.find("ul")
        if not ul:
            return []
        notices = []
        for li in ul.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            url = a["href"]
            if not url.startswith("http"):
                url = cls._base_url + url.lstrip("/")
            title_tag = a.find("p", class_="bt")
            title = title_tag.get_text(strip=True) if title_tag else None
            summary_tag = a.find("p", class_="zy")
            summary = summary_tag.get_text(strip=True) if summary_tag else None
            date_tag = a.find("p", class_="sj")
            upload_time = None
            if date_tag:
                try:
                    # 日期格式如 2025.04.21
                    from datetime import datetime
                    upload_time = datetime.strptime(date_tag.get_text(strip=True), "%Y.%m.%d").date()
                except Exception:
                    upload_time = None
            notice = Notice(
                url=url,
                title=title,
                # summary=summary,
                upload_time=upload_time
            )
            notices.append(notice)
        return notices

    @classmethod
    def dedup_and_save_to_csv(cls, notices, csv_path="resources/notice_records.csv"):
        """
        对传入的Notice列表进行去重，依据csv中的记录进行去重，并更新csv内容，返回去重后的Notice列表。
        csv只存储url和hash值。忽略空行，写入时去除潜在空行。
        """
        csv_path = Path(__file__).parent.parent.parent.joinpath(csv_path)
        print(f"CSV Path: {csv_path}")
        abs_csv_path = os.path.abspath(csv_path)
        existing_records = []
        existing_hashes = set()
        # 读取已存在的记录，忽略空行
        if os.path.exists(abs_csv_path):
            with open(abs_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and len(row) >= 2 and row[0] and row[1]:
                        existing_records.append((row[0], row[1]))
                        existing_hashes.add(row[1])

        def notice_hash(x: Notice):
            import hashlib
            h = hashlib.sha256()
            h.update((x.url or "").encode("utf-8"))
            h.update((x.title or "").encode("utf-8"))
            return h.hexdigest()

        deduped = []
        new_records = []
        for notice in notices:
            h = notice_hash(notice)
            if h not in existing_hashes:
                deduped.append(notice)
                new_records.append((notice.url, h))

        # 更新csv，去除潜在空行，只保留有效记录+新记录
        all_records = existing_records + new_records
        if new_records or (os.path.exists(abs_csv_path) and len(existing_records) != sum(
                1 for _ in open(abs_csv_path, encoding="utf-8"))):
            os.makedirs(os.path.dirname(abs_csv_path), exist_ok=True)
            with open(abs_csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for rec in all_records:
                    if rec[0] and rec[1]:
                        writer.writerow(rec)

        return deduped

    @classmethod
    def get_notice_list(cls) -> list[Notice]:
        """
        获取通知公告列表
        """
        notices = cls.fetch_notice_list()
        deduped_notices = cls.dedup_and_save_to_csv(notices)
        return deduped_notices
