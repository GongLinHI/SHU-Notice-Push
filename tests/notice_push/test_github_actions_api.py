from __future__ import annotations

import requests

from notice_push.observability.github_actions import GitHubActionsApiClient


class _Response:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return next(self.responses)


def test_github_actions_client_collects_jobs_and_check_annotations():
    session = _Session(
        [
            _Response({"jobs": [{"id": 7, "check_run_url": "https://api.github.com/check-runs/7"}]}),
            _Response([{"message": "runner unavailable"}]),
        ]
    )
    client = GitHubActionsApiClient(
        repository="owner/repo",
        token="secret",
        session_factory=lambda: session,
    )

    context = client.fetch_run_context(123)

    assert context["jobs"][0]["id"] == 7
    assert context["annotations"] == [{"message": "runner unavailable"}]
    assert session.requests[0][1]["headers"]["Authorization"] == "Bearer secret"


def test_github_actions_client_filters_workflow_page_size():
    session = _Session([_Response({"workflow_runs": []})])
    client = GitHubActionsApiClient(
        repository="owner/repo",
        token="secret",
        session_factory=lambda: session,
    )

    assert client.fetch_scheduled_runs("daily_report.yml", per_page=500) == {"workflow_runs": []}
    assert "per_page=100" in session.requests[0][0]


def test_github_actions_client_preserves_jobs_when_annotations_are_unavailable():
    session = _Session(
        [
            _Response({"jobs": [{"id": 7, "check_run_url": "https://api.github.com/check-runs/7"}]}),
            _Response({}, status_code=404),
        ]
    )
    client = GitHubActionsApiClient(
        repository="owner/repo",
        token="secret",
        session_factory=lambda: session,
    )

    context = client.fetch_run_context(123)

    assert context["jobs"][0]["id"] == 7
    assert context["annotations"] == []
    assert context["annotation_errors"]
