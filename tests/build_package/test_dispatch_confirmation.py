"""An accepted dispatch is only reported as started once a run exists.

GitHub answers 204 as soon as it accepts a repository_dispatch, even when no
workflow run is ever created — during an Actions outage, or when no workflow
listens to that event type. The tool used to call that "triggered
successfully" and say nothing more.
"""

from datetime import datetime, timedelta, timezone

import pytest

from gitrepo.build_package.core import github_api
from gitrepo.build_package.core.git_utils import GitUtils


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(github_api, "_", lambda message: message)
    monkeypatch.setattr(github_api.time, "sleep", lambda _seconds: None)
    # One lookup is enough here; the polling window itself is not under test.
    monkeypatch.setattr(github_api, "RUN_LOOKUP_TIMEOUT", 0)
    monkeypatch.setattr(GitUtils, "get_repo_name", staticmethod(lambda: "big-comm/ashyterm"))
    return github_api.GitHubAPI("token", "big-comm")


def install_requests(monkeypatch, runs, posted):
    def post(url, headers=None, json=None, timeout=None):
        posted.append((url, json))
        return Response(204)

    def get(url, headers=None, params=None, timeout=None):
        return Response(200, {"workflow_runs": runs})

    monkeypatch.setattr(github_api.requests, "post", post)
    monkeypatch.setattr(github_api.requests, "get", get)


def test_started_run_is_reported_with_its_number_and_url(api, monkeypatch):
    logger = Logger()
    posted = []
    started_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    install_requests(
        monkeypatch,
        [
            {
                "created_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "display_title": "ashyterm",
                "run_number": 2193,
                "html_url": "https://github.com/big-comm/build-package/actions/runs/1",
            }
        ],
        posted,
    )

    assert api.trigger_workflow("ashyterm", "stable", "", False, False, logger) is True

    assert posted[0][1]["event_type"] == "ashyterm"
    assert "2193" in logger.text()
    assert "https://github.com/big-comm/build-package/actions/runs/1" in logger.text()


def test_accepted_dispatch_without_a_run_is_not_called_started(api, monkeypatch):
    logger = Logger()
    install_requests(monkeypatch, [], [])

    assert api.trigger_workflow("ashyterm", "stable", "", False, False, logger) is True

    text = logger.text()
    assert "no workflow run appeared" in text
    assert "not confirmed as started" in text
    assert github_api.GITHUB_STATUS_URL in text


def test_a_run_from_before_the_dispatch_is_not_claimed_as_this_one(api, monkeypatch):
    logger = Logger()
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    install_requests(
        monkeypatch,
        [
            {
                "created_at": stale.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "display_title": "ashyterm",
                "run_number": 2191,
                "html_url": "https://github.com/big-comm/build-package/actions/runs/0",
            }
        ],
        [],
    )

    assert api.trigger_workflow("ashyterm", "stable", "", False, False, logger) is True

    text = logger.text()
    assert "2191" not in text
    assert "no workflow run appeared" in text


def test_a_run_for_another_package_is_not_claimed_as_this_one(api, monkeypatch):
    logger = Logger()
    started_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    install_requests(
        monkeypatch,
        [
            {
                "created_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "display_title": "layout-switcher",
                "run_number": 2194,
                "html_url": "https://github.com/big-comm/build-package/actions/runs/2",
            }
        ],
        [],
    )

    assert api.trigger_workflow("ashyterm", "stable", "", False, False, logger) is True

    assert "2194" not in logger.text()
    assert "no workflow run appeared" in logger.text()


def test_a_failed_lookup_never_turns_an_accepted_dispatch_into_an_error(api, monkeypatch):
    logger = Logger()

    def post(url, headers=None, json=None, timeout=None):
        return Response(204)

    def get(url, headers=None, params=None, timeout=None):
        raise github_api.requests.RequestException("network down")

    monkeypatch.setattr(github_api.requests, "post", post)
    monkeypatch.setattr(github_api.requests, "get", get)

    assert api.trigger_workflow("ashyterm", "stable", "", False, False, logger) is True
    assert "no workflow run appeared" in logger.text()
