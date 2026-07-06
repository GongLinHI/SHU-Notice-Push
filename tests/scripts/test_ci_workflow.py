from pathlib import Path


def test_ci_workflow_avoids_external_actionlint_invocation():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "rhysd/actionlint@v1" not in workflow
    assert "download-actionlint.bash" not in workflow
    assert "./actionlint" not in workflow


def test_ci_doctor_uses_temporary_state_database():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m notice_push --doctor --state-path \"$RUNNER_TEMP/ci-state.sqlite3\"" in workflow


def test_ci_creates_pytest_basetemp_parent_directory():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "mkdir -p .tmp" in workflow
    assert workflow.index("mkdir -p .tmp") < workflow.index("pytest tests/notice_push/test_cli.py")


def test_daily_report_workflow_captures_updated_count():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    assert "updated_count=$(echo \"$output\" | awk -F= '/^updated_count=/{print $2}' | tail -n1)" in workflow
    assert 'echo "updated_count=${updated_count:-0}" >> "$GITHUB_OUTPUT"' in workflow
    assert "--metadata=updated_count:${{ steps.run_python_script.outputs.updated_count }}" in workflow


def test_daily_report_bot_commit_message_uses_chinese_run_context():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    assert "git commit \\" in workflow
    assert (
        '日报 ${{ steps.date.outputs.date }}: 新增 '
        '${{ steps.run_python_script.outputs.new_count }} 更新 '
        '${{ steps.run_python_script.outputs.updated_count }} 复核 '
        '${{ steps.run_python_script.outputs.manual_review_count }} [bot]'
    ) in workflow
    assert "重试通知: ${{ steps.run_python_script.outputs.retried_count }}" in workflow
    assert "成功摘要: ${{ steps.run_python_script.outputs.summarized_count }}" in workflow
    assert "失败通知: ${{ steps.run_python_script.outputs.failed_count }}" in workflow
    assert "源站异常: ${{ steps.run_python_script.outputs.source_error_count }}" in workflow
    assert "巡检异常: ${{ steps.run_python_script.outputs.audit_error_count }}" in workflow
    assert "巡检警告: ${{ steps.run_python_script.outputs.audit_warning_count }}" in workflow
    assert "详情刷新异常: ${{ steps.run_python_script.outputs.refresh_seen_error_count }}" in workflow
