import sqlite3

from notice_push.observability.sqlite_backup import backup_sqlite


def test_backup_sqlite_creates_integrity_checked_copy(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "nested" / "copy.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("create table notices (id integer primary key, title text not null)")
        connection.execute("insert into notices(title) values ('测试通知')")

    copied = backup_sqlite(source, destination)

    assert copied is True
    with sqlite3.connect(destination) as connection:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("select title from notices").fetchone()[0] == "测试通知"


def test_backup_sqlite_returns_false_when_source_does_not_exist(tmp_path):
    copied = backup_sqlite(tmp_path / "missing.sqlite3", tmp_path / "copy.sqlite3")

    assert copied is False
