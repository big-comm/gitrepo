"""A pull request to a branch GitHub does not have is explained, or the branch is published first.

talesam/AshyTV never published main: GitHub had only dev-* branches, and main
lived on this computer. Opening dev-talesam -> main failed with an empty log,
because GitHub's 422 ("base: invalid") was read as "a pull request exists".
"""

import subprocess

import pytest

from gitrepo.build_package.core import branch_handler
from gitrepo.build_package.core.github_api import GitHubAPI

from .git_fixtures import Logger, create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")


class _Menu:
    def __init__(self, answer):
        self.answer = answer
        self.questions = []

    def confirm(self, question, default_yes=True):
        self.questions.append(question)
        return self.answer


class _Bp:
    def __init__(self, answer=True):
        self.logger = Logger()
        self.menu = _Menu(answer)

    def text(self):
        return "\n".join(message for _style, message in self.logger.messages)


def _on_remote(remote, branch):
    return (
        subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.fixture
def main_never_published(tmp_path, monkeypatch):
    """main exists only here; GitHub has dev-me alone."""
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    (repository / "work.txt").write_text("x\n", encoding="utf-8")
    run_git(repository, "add", "work.txt")
    run_git(repository, "commit", "-m", "work")
    run_git(repository, "push", "-u", "origin", "dev-me")
    subprocess.run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/dev-me"], check=True)
    subprocess.run(["git", "--git-dir", str(remote), "update-ref", "-d", "refs/heads/main"], check=True)
    monkeypatch.chdir(repository)
    return repository, remote


def test_a_local_only_target_is_published_after_the_user_agrees(main_never_published):
    _repository, remote = main_never_published
    bp = _Bp(answer=True)

    assert branch_handler.ensure_pull_request_branches(bp, "dev-me", "main")

    assert _on_remote(remote, "main")
    assert "main exists only on this computer" in bp.text()
    assert bp.menu.questions == ["Publish the local main to GitHub and continue with the pull request?"]


def test_declining_publishes_nothing_and_stops(main_never_published):
    _repository, remote = main_never_published
    bp = _Bp(answer=False)

    assert not branch_handler.ensure_pull_request_branches(bp, "dev-me", "main")

    assert not _on_remote(remote, "main")
    assert "Operation cancelled by user." in bp.text()


def test_a_target_that_exists_nowhere_is_explained(main_never_published):
    repository, _remote = main_never_published
    run_git(repository, "branch", "-D", "main")
    bp = _Bp()

    assert not branch_handler.ensure_pull_request_branches(bp, "dev-me", "main")

    assert "The branch main does not exist on GitHub or on this computer." in bp.text()
    assert "Publish to origin now" in bp.text()
    assert bp.menu.questions == []


def test_published_branches_ask_nothing(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    run_git(repository, "push", "-u", "origin", "dev-me")
    monkeypatch.chdir(repository)
    bp = _Bp()

    assert branch_handler.ensure_pull_request_branches(bp, "dev-me", "main")
    assert bp.menu.questions == []
    assert bp.logger.messages == []


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "x"

    def json(self):
        return self._payload


def test_github_refusing_the_base_is_logged(monkeypatch):
    api = GitHubAPI.__new__(GitHubAPI)
    api.headers = {}
    refused = _Response(
        422,
        {
            "message": "Validation Failed",
            "errors": [{"resource": "PullRequest", "field": "base", "code": "invalid"}],
        },
    )
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: refused)
    monkeypatch.setattr(api, "_find_existing_pr", lambda *args: {})
    logger = Logger()

    assert api._create_or_find_pull_request("talesam/AshyTV", "dev-talesam", "main", logger) == {}

    assert logger.messages == [("red", "Failed to create PR: Validation Failed — base invalid")]


def test_an_existing_pull_request_is_still_reused(monkeypatch):
    api = GitHubAPI.__new__(GitHubAPI)
    api.headers = {}
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: _Response(422, {"message": "exists"}))
    monkeypatch.setattr(api, "_find_existing_pr", lambda *args: {"number": 7})
    logger = Logger()

    assert api._create_or_find_pull_request("o/r", "dev-me", "main", logger) == {"number": 7}
    assert logger.messages == [("yellow", "Using existing PR #7")]
