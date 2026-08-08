from __future__ import annotations

import argparse
import os
from pathlib import Path

from notice_push.observability.github_actions import GitHubActionsApiClient, GitHubActionsApiError
from notice_push.observability.heartbeat import evaluate_daily_heartbeat
from scripts.workflow._outputs import append_github_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the scheduled Daily Report run appeared.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-id", default="daily_report.yml")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--lookback-hours", type=float, default=8.0)
    parser.add_argument("--stalled-after-minutes", type=float, default=180.0)
    parser.add_argument("--decision-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise ValueError(f"{args.token_env} must be provided")
    runs = GitHubActionsApiClient(
        repository=args.repository,
        token=token,
        api_url=args.api_url,
    )
    scheduled_runs = runs.fetch_scheduled_runs(args.workflow_id)
    try:
        monitor_runs = runs.fetch_workflow_runs("daily_report_monitor.yml", per_page=50)
    except GitHubActionsApiError:
        monitor_runs = {"workflow_runs": []}
    decision = evaluate_daily_heartbeat(
        scheduled_runs,
        monitor_runs_payload=monitor_runs,
        lookback_hours=args.lookback_hours,
        stalled_after_minutes=args.stalled_after_minutes,
    )
    args.decision_json.parent.mkdir(parents=True, exist_ok=True)
    args.decision_json.write_text(decision.to_json_text(), encoding="utf-8")
    append_github_outputs(args.github_output, decision.workflow_outputs())
    print(f"monitor_status={decision.status.value}")
    print(f"summary={decision.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
