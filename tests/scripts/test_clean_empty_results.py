from scripts.clean_empty_results import find_empty_result_files, is_empty_result_report


def test_detects_known_empty_report_formats():
    assert is_empty_result_report(
        "2025-04-28.md",
        "## No new notices found today (2025-04-28).\r\n",
    )
    assert is_empty_result_report("2026-01-29.md", "2026-01-29没有新通知.\n")


def test_rejects_reports_with_real_content_or_wrong_date():
    assert not is_empty_result_report(
        "2025-04-28.md",
        "## No new notices found today (2025-04-28).\n\n## 运行概览\n- 新增通知: 1\n",
    )
    assert not is_empty_result_report("2025-04-28.md", "2025-04-29没有新通知.\n")
    assert not is_empty_result_report("notes.md", "2025-04-28没有新通知.\n")


def test_finds_only_direct_markdown_empty_reports(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "2025-04-28.md").write_text(
        "## No new notices found today (2025-04-28).\n",
        encoding="utf-8",
    )
    (results_dir / "2026-01-29.md").write_text(
        "2026-01-29没有新通知.\n",
        encoding="utf-8",
    )
    (results_dir / "2026-01-30.md").write_text(
        "# SHU Notice Report\n\n正文\n",
        encoding="utf-8",
    )
    nested = results_dir / "html"
    nested.mkdir()
    (nested / "2026-01-31.md").write_text(
        "2026-01-31没有新通知.\n",
        encoding="utf-8",
    )

    matches = find_empty_result_files(results_dir)

    assert matches == [results_dir / "2025-04-28.md", results_dir / "2026-01-29.md"]
