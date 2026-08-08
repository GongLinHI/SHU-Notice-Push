from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from notice_push.observability.github_actions import GitHubActionsApiClient, GitHubActionsApiError
from notice_push.observability.publication_manifest import PublicationManifest
from notice_push.observability.workflow_monitor import classify_workflow_run
from scripts.workflow._outputs import append_github_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a completed Daily Report workflow run.")
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--artifacts-root", type=Path, default=None)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--decision-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    event = json.loads(args.event_json.read_text(encoding="utf-8"))
    run = event.get("workflow_run", {}) if isinstance(event, dict) else {}
    run_id = run.get("id") if isinstance(run, dict) else None
    context = _fetch_context(args, run_id)
    args.context_json.parent.mkdir(parents=True, exist_ok=True)
    args.context_json.write_text(
        json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    publication = _find_publication(args.artifacts_root)
    decision = classify_workflow_run(event, context, publication)
    args.decision_json.parent.mkdir(parents=True, exist_ok=True)
    args.decision_json.write_text(decision.to_json_text(), encoding="utf-8")
    append_github_outputs(args.github_output, decision.workflow_outputs())
    print(f"monitor_status={decision.status.value}")
    print(f"failure_type={decision.failure_type.value if decision.failure_type else ''}")
    print(f"summary={decision.summary}")
    return 0


def _fetch_context(args, run_id: object) -> dict[str, object]:
    token = os.getenv(args.token_env, "").strip()
    if not token or not isinstance(run_id, int):
        return {"jobs": [], "annotations": [], "collection_error": "missing token or run id"}
    try:
        return GitHubActionsApiClient(
            repository=args.repository,
            token=token,
            api_url=args.api_url,
        ).fetch_run_context(run_id)
    except GitHubActionsApiError as exc:
        return {"jobs": [], "annotations": [], "collection_error": str(exc)}


def _find_publication(root: Path | None) -> PublicationManifest | None:
    if root is None or not root.is_dir():
        return None
    for path in sorted(root.rglob("publication.json")):
        try:
            return PublicationManifest.from_json_text(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
