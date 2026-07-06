from pathlib import Path


def test_ci_workflow_uses_resolvable_actionlint_invocation():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "rhysd/actionlint@v1" not in workflow
    assert "actionlint" in workflow


def test_ci_doctor_uses_temporary_state_database():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m notice_push --doctor --state-path \"$RUNNER_TEMP/ci-state.sqlite3\"" in workflow
