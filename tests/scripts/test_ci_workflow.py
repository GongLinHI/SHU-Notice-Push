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
    evaluator = Path("scripts/workflow/evaluate_publication.py").read_text(encoding="utf-8")

    assert 'publication.workflow_outputs(prefix="initial_")' in evaluator
    assert "--metadata=updated_count:${{ steps.initial_publication.outputs.initial_updated_count }}" in workflow


def test_daily_report_bot_commit_message_uses_chinese_run_context():
    publisher = Path("scripts/workflow/publish_master.py").read_text(encoding="utf-8")

    assert 'f"日报 {request.report_date}: 新增 {counts.new_count} 更新 {counts.updated_count} 复核 {counts.manual_review_count} [bot]"' in publisher
    assert 'f"重试通知: {counts.retried_count}"' in publisher
    assert 'f"成功摘要: {counts.summarized_count}"' in publisher
    assert 'f"失败通知: {counts.failed_count}"' in publisher
    assert 'f"源站异常: {counts.source_error_count}"' in publisher
    assert 'f"巡检异常: {counts.audit_error_count}"' in publisher
    assert 'f"巡检警告: {counts.audit_warning_count}"' in publisher
    assert 'f"详情刷新异常: {counts.refresh_seen_error_count}"' in publisher


def test_daily_report_workflow_uses_single_publication_decision_for_release_paths():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    assert "- name: Evaluate initial publication" in workflow
    assert "- name: Finalize publication" in workflow
    assert "id: initial_publication" in workflow
    assert "id: publication" in workflow
    assert "python -m scripts.workflow.evaluate_publication" in workflow
    assert "python -m scripts.workflow.finalize_publication" in workflow
    assert "python -m scripts.workflow.write_blocked_publication_fallback" in workflow
    assert "publication_status" in workflow
    assert "publication_blockers" in workflow
    manifest = Path("notice_push/observability/publication_manifest.py").read_text(encoding="utf-8")
    assert '"snapshot_path"' in manifest
    assert '"artifact_name"' in manifest
    assert "steps.publication.outputs.publication_status == 'published'" in workflow
    assert "steps.initial_publication.outputs.initial_publication_status == 'no_report'" in workflow
    assert workflow.count('--failure-snapshot-branch "$FAILURE_SNAPSHOT_BRANCH"') == 4


def test_daily_report_workflow_recovers_when_initial_evaluation_fails():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    initial_index = workflow.index("- name: Evaluate initial publication")
    fallback_index = workflow.index("python -m scripts.workflow.write_blocked_publication_fallback")
    final_index = workflow.index("- name: Finalize publication")

    assert initial_index < fallback_index < final_index
    assert 'candidate-publication.json' in workflow
    assert 'if: always()' in workflow[initial_index:final_index]
    assert "python -m scripts.workflow.validate_publication_result" in workflow[final_index:]


def test_daily_report_workflow_does_not_publish_master_when_html_render_fails():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    publish_index = workflow.index("- name: Publish formal master state")
    final_index = workflow.index("- name: Finalize publication")
    email_index = workflow.index("- name: Send daily report email")

    assert "steps.render_html.outcome == 'success'" in workflow[publish_index:final_index]
    assert "MASTER_PUBLISH_ERROR: ${{ steps.publish_master.outputs.error }}" in workflow[publish_index:email_index]
    assert '--master-publish-error "${MASTER_PUBLISH_ERROR:-}"' in workflow[publish_index:email_index]
    assert publish_index < final_index < email_index


def test_daily_report_workflow_distinguishes_email_failure_after_master_publish():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    assert "id: send_report_email" in workflow
    assert "steps.send_report_email.outcome == 'failure'" in workflow
    assert "正式数据已发布到 master，但日报邮件投递失败" in workflow


def test_daily_report_workflow_isolates_blocked_runs_from_master_and_preserves_snapshots():
    workflow = Path(".github/workflows/daily_report.yml").read_text(encoding="utf-8")

    assert "bot/failure-snapshots" in workflow
    assert "if: always() && steps.publication.outputs.publication_status == 'blocked'" in workflow
    assert "notice-failure-snapshot-${{ steps.date.outputs.date }}-${{ github.run_id }}" in workflow
    assert "path: .failure-snapshot-repo" in workflow
    helper = Path("scripts/workflow/publish_failure_snapshot.py").read_text(encoding="utf-8")
    assert "python -m scripts.workflow.publish_failure_snapshot" in workflow
    assert '"add", "--", *add_paths' in helper
    assert '"add", "-A"' not in helper
    assert '"commit", "-am"' not in helper
    assert "git add -A" not in workflow
    assert "git commit -am" not in workflow
    assert "set +e" not in workflow[workflow.index("- name: Push failure snapshot"):]
    assert workflow.index("Upload failure snapshot") < workflow.index("Push failure snapshot")
    assert workflow.index("Push failure snapshot") < workflow.index("Send operational alert email")
    assert workflow.index("Send operational alert email") < workflow.index("Fail blocked publication")
    build_section = workflow[
        workflow.index("- name: Build failure snapshot") : workflow.index("- name: Upload failure snapshot")
    ]
    assert '--run-summary-path "${{ steps.publication.outputs.run_summary_path }}"' in build_section
    assert '--partial-report-path "${{ steps.publication.outputs.report_path }}"' in build_section
    assert "$GITHUB_WORKSPACE/" not in build_section

    upload_section = workflow[
        workflow.index("- name: Upload failure snapshot") : workflow.index("- name: Checkout failure snapshot branch workspace")
    ]
    assert "sanitized-notice_pipeline.log" in upload_section
    assert "${{ runner.temp }}/notice_pipeline.log" not in upload_section
