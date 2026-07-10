from scripts.workflow.evaluate_publication import evaluate_pipeline_output


def test_evaluate_pipeline_output_accepts_complete_reportable_run(tmp_path):
    report_path = tmp_path / "resources" / "results" / "2026-07-10.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("## 日报\n", encoding="utf-8")
    output = "\n".join(
        [
            "new_count=2",
            "updated_count=1",
            "retried_count=0",
            "summarized_count=3",
            "failed_count=0",
            "manual_review_count=0",
            "source_error_count=0",
            "audit_error_count=0",
            "audit_warning_count=0",
            "refresh_seen_error_count=0",
            "report_path=resources/results/2026-07-10.md",
            "run_summary_path=resources/results/json/2026-07-10.json",
        ]
    )

    evaluation = evaluate_pipeline_output(output, raw_exit_code=0, workspace=tmp_path)

    assert evaluation.decision.status.value == "published"
    assert evaluation.pipeline_exit_code == 0
    assert evaluation.report_exists is True
    assert evaluation.counters.new_count == 2
    assert evaluation.run_summary_path == "resources/results/json/2026-07-10.json"


def test_evaluate_pipeline_output_blocks_source_failure_even_when_report_exists(tmp_path):
    report_path = tmp_path / "report.md"
    report_path.write_text("partial report", encoding="utf-8")
    output = "\n".join(
        [
            "new_count=1",
            "updated_count=0",
            "retried_count=0",
            "summarized_count=1",
            "failed_count=0",
            "manual_review_count=0",
            "source_error_count=1",
            "audit_error_count=0",
            "audit_warning_count=0",
            "refresh_seen_error_count=0",
            "report_path=report.md",
        ]
    )

    evaluation = evaluate_pipeline_output(output, raw_exit_code=0, workspace=tmp_path)

    assert evaluation.decision.status.value == "blocked"
    assert evaluation.decision.blockers == ("source_error_count=1",)
    assert evaluation.pipeline_exit_code == 0


def test_evaluate_pipeline_output_blocks_missing_counts_and_normalizes_exit_code(tmp_path):
    evaluation = evaluate_pipeline_output("Traceback: startup failed", raw_exit_code=1, workspace=tmp_path)

    assert evaluation.decision.status.value == "blocked"
    assert evaluation.decision.blockers == ("pipeline_exit_code=2",)
    assert evaluation.pipeline_exit_code == 2
    assert evaluation.counters.source_error_count == 0


def test_evaluate_pipeline_output_blocks_missing_report_from_success_exit(tmp_path):
    output = "\n".join(
        [
            "new_count=1",
            "updated_count=0",
            "retried_count=0",
            "summarized_count=1",
            "failed_count=0",
            "manual_review_count=0",
            "source_error_count=0",
            "audit_error_count=0",
            "audit_warning_count=0",
            "refresh_seen_error_count=0",
            "report_path=resources/results/missing.md",
        ]
    )

    evaluation = evaluate_pipeline_output(output, raw_exit_code=0, workspace=tmp_path)

    assert evaluation.decision.status.value == "blocked"
    assert evaluation.decision.blockers == ("pipeline_exit_code=2",)
