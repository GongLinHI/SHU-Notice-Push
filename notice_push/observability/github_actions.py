from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import requests

from notice_push.http_retry import is_retryable_http_status, retry_delay_seconds


class GitHubActionsApiError(RuntimeError):
    pass


@dataclass
class GitHubActionsApiClient:
    repository: str
    token: str
    api_url: str = "https://api.github.com"
    timeout: float = 15.0
    max_attempts: int = 3
    session_factory: Callable[[], requests.Session] = requests.Session

    def __post_init__(self) -> None:
        self._session = self.session_factory()

    def fetch_run_context(self, run_id: int) -> dict[str, object]:
        jobs_payload = self._get_json(
            f"/repos/{self.repository}/actions/runs/{run_id}/jobs?per_page=100"
        )
        jobs = jobs_payload.get("jobs", []) if isinstance(jobs_payload, dict) else []
        annotations: list[object] = []
        annotation_errors: list[str] = []
        if isinstance(jobs, list):
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                check_run_url = job.get("check_run_url")
                if not isinstance(check_run_url, str) or not check_run_url:
                    continue
                try:
                    payload = self._get_json(f"{check_run_url}/annotations?per_page=100")
                except GitHubActionsApiError as exc:
                    annotation_errors.append(str(exc))
                    continue
                if isinstance(payload, list):
                    annotations.extend(payload)
        return {
            "jobs": jobs if isinstance(jobs, list) else [],
            "annotations": annotations,
            "annotation_errors": annotation_errors,
        }

    def fetch_scheduled_runs(self, workflow_id: str, *, per_page: int = 20) -> dict[str, object]:
        return self.fetch_workflow_runs(workflow_id, event="schedule", per_page=per_page)

    def fetch_workflow_runs(
        self,
        workflow_id: str,
        *,
        event: str = "",
        per_page: int = 20,
    ) -> dict[str, object]:
        event_query = f"&event={event}" if event else ""
        payload = self._get_json(
            f"/repos/{self.repository}/actions/workflows/{workflow_id}/runs"
            f"?per_page={max(1, min(per_page, 100))}{event_query}"
        )
        if not isinstance(payload, dict):
            raise GitHubActionsApiError("GitHub workflow runs response is not an object")
        return payload

    def _get_json(self, path_or_url: str) -> object:
        url = path_or_url if path_or_url.startswith("https://") else f"{self.api_url.rstrip('/')}{path_or_url}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "SHU-Notice-Push-Monitor/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        attempts = max(1, self.max_attempts)
        for attempt in range(attempts):
            try:
                response = self._session.get(url, headers=headers, timeout=self.timeout)
                if response.status_code < 400:
                    return response.json()
                retryable = is_retryable_http_status(response.status_code)
                if not retryable or attempt + 1 >= attempts:
                    response.raise_for_status()
                delay = retry_delay_seconds(
                    response.headers.get("Retry-After"),
                    fallback_delay=0.5 * (2**attempt),
                    max_delay=5.0,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt + 1 >= attempts:
                    raise GitHubActionsApiError(f"GitHub API request failed: {exc}") from exc
                delay = min(0.5 * (2**attempt), 5.0)
            except (requests.RequestException, ValueError) as exc:
                raise GitHubActionsApiError(f"GitHub API request failed: {exc}") from exc
            time.sleep(delay)
        raise GitHubActionsApiError("GitHub API retry loop exited unexpectedly")
