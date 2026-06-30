from src.notice_push.__main__ import main


class Spider:
    @staticmethod
    def run():
        return main()


if __name__ == "__main__":
    raise SystemExit(Spider.run())
