"""Auto-merge stops waiting as soon as GitHub reports a failed check, instead of polling for minutes."""

import importlib

import pytest


@pytest.fixture
def github_api(build_package_modules, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")
    module = importlib.import_module("gitrepo.build_package.core.github_api")
    monkeypatch.setattr(module.GitUtils, "get_repo_name", staticmethod(lambda: "acme/widgets"))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = "x"

    def json(self):
        return self.payload


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class FakeGitHub:
    """Answers the PR, check-run, and status endpoints from scripted states."""

    def __init__(self, pull_states, check_runs=(), statuses=()):
        self.pull_states = list(pull_states)
        self.check_runs = list(check_runs)
        self.statuses = list(statuses)
        self.pull_reads = 0
        self.merged = False

    def get(self, url, params=None, **kwargs):
        if url.endswith("/check-runs"):
            runs = self.check_runs.pop(0) if len(self.check_runs) > 1 else self.check_runs[0]
            return Response({"check_runs": runs})
        if url.endswith("/status"):
            return Response({"statuses": self.statuses[0] if self.statuses else []})
        self.pull_reads += 1
        state = self.pull_states.pop(0) if len(self.pull_states) > 1 else self.pull_states[0]
        return Response({"mergeable": state != "dirty", "mergeable_state": state, "head": {"sha": "abc123"}})

    def put(self, url, **kwargs):
        self.merged = True
        return Response({"sha": "merged"})


FAILED_BUILD = {
    "name": "Build Package / build (push)",
    "status": "completed",
    "conclusion": "failure",
    "html_url": "https://github.com/acme/widgets/actions/runs/1",
}
RUNNING_BUILD = {"name": "Build Package / build (push)", "status": "in_progress", "conclusion": None}
PASSED_BUILD = {"name": "Build Package / build (push)", "status": "completed", "conclusion": "success"}


def _install(github_api, monkeypatch, fake):
    monkeypatch.setattr(github_api.requests, "get", fake.get)
    monkeypatch.setattr(github_api.requests, "put", fake.put)


def test_a_failed_check_stops_the_wait_at_once_and_names_it(github_api, monkeypatch):
    fake = FakeGitHub(["unstable"], check_runs=[[FAILED_BUILD]])
    _install(github_api, monkeypatch, fake)
    logger = Logger()

    ready, state = github_api.GitHubAPI("token", "acme").wait_for_pr_checks(5, logger)

    assert (ready, state) == (False, "checks-failed")
    assert fake.pull_reads == 1
    assert "A check failed on GitHub: Build Package / build (push)" in logger.text()
    assert "https://github.com/acme/widgets/actions/runs/1" in logger.text()
    assert "left open and not merged" in logger.text()


def test_auto_merge_with_a_failed_check_does_not_merge(github_api, monkeypatch):
    fake = FakeGitHub(["unstable"], check_runs=[[FAILED_BUILD]])
    _install(github_api, monkeypatch, fake)
    pr_info = {"number": 5}

    github_api.GitHubAPI("token", "acme")._merge_ready_pull_request(
        "acme/widgets", pr_info, "dev-me", "main", Logger()
    )

    assert not fake.merged
    assert pr_info["auto_merged"] is False
    assert pr_info["merge_error"] == "PR not ready: a check failed on GitHub"


def test_running_checks_are_waited_for_until_the_pr_is_clean(github_api, monkeypatch):
    fake = FakeGitHub(
        ["unstable", "unstable", "clean"],
        check_runs=[[RUNNING_BUILD], [RUNNING_BUILD], [PASSED_BUILD]],
    )
    _install(github_api, monkeypatch, fake)

    ready, state = github_api.GitHubAPI("token", "acme").wait_for_pr_checks(5, Logger())

    assert (ready, state) == (True, "clean")
    assert fake.pull_reads == 3


def test_a_failed_commit_status_also_stops_the_wait(github_api, monkeypatch):
    status = {"context": "ci/legacy", "state": "failure", "target_url": "https://ci.example/1"}
    fake = FakeGitHub(["unstable"], check_runs=[[]], statuses=[[status]])
    _install(github_api, monkeypatch, fake)
    logger = Logger()

    ready, state = github_api.GitHubAPI("token", "acme").wait_for_pr_checks(5, logger)

    assert (ready, state) == (False, "checks-failed")
    assert "ci/legacy" in logger.text()


def test_a_block_nothing_can_lift_stops_the_wait(github_api, monkeypatch):
    fake = FakeGitHub(["blocked"], check_runs=[[PASSED_BUILD]])
    _install(github_api, monkeypatch, fake)
    logger = Logger()

    ready, state = github_api.GitHubAPI("token", "acme").wait_for_pr_checks(5, logger)

    assert (ready, state) == (False, "blocked")
    assert fake.pull_reads == 1
    assert "required review" in logger.text()


def test_a_block_while_checks_run_keeps_waiting(github_api, monkeypatch):
    fake = FakeGitHub(["blocked", "clean"], check_runs=[[RUNNING_BUILD], [PASSED_BUILD]])
    _install(github_api, monkeypatch, fake)

    assert github_api.GitHubAPI("token", "acme").wait_for_pr_checks(5, Logger()) == (True, "clean")
