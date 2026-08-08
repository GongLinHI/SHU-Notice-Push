from pathlib import Path

import yaml


def _workflow(name: str):
    workflow = yaml.safe_load(Path(f".github/workflows/{name}").read_text(encoding="utf-8"))
    if "on" not in workflow and True in workflow:
        workflow["on"] = workflow[True]
    return workflow


def test_monitor_uses_completed_workflow_run_and_skips_successful_source_runs():
    workflow = _workflow("daily_report_monitor.yml")
    source = Path(".github/workflows/daily_report_monitor.yml").read_text(encoding="utf-8")

    assert workflow["on"]["workflow_run"]["workflows"] == ["Daily Report"]
    assert workflow["on"]["workflow_run"]["types"] == ["completed"]
    assert "github.event.workflow_run.conclusion != 'success'" in source
    assert "github.event.workflow_run.head_branch == github.event.repository.default_branch" in source


def test_monitor_downloads_cross_run_evidence_before_classification():
    source = Path(".github/workflows/daily_report_monitor.yml").read_text(encoding="utf-8")

    assert "run-id: ${{ github.event.workflow_run.id }}" in source
    assert "pattern: notice-publication-*" in source
    assert "pattern: notice-failure-snapshot-*" in source
    assert source.index("Download publication manifest") < source.index("Classify completed run")
    assert "python -m scripts.workflow.publish_monitor_snapshot" in source
    assert "python -m scripts.workflow.render_monitor_alert" in source


def test_watchdog_checks_for_missing_or_stalled_scheduled_run():
    workflow = _workflow("daily_report_watchdog.yml")
    source = Path(".github/workflows/daily_report_watchdog.yml").read_text(encoding="utf-8")

    assert "schedule" in workflow["on"]
    assert "python -m scripts.workflow.evaluate_daily_heartbeat" in source
    assert "--stalled-after-minutes 180" in source
    assert "daily_report_monitor.yml" in Path(
        "scripts/workflow/evaluate_daily_heartbeat.py"
    ).read_text(encoding="utf-8")
    assert "Upload watchdog snapshot" in source
    assert "Send watchdog alert email" in source
