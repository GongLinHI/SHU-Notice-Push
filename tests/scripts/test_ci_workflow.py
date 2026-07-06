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
