"""A testing build whose branch is behind origin says why the push was refused and what fixes it."""

import subprocess

import pytest

from gitrepo.build_package.core import main_sync, package_operations

from .git_fixtures import create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    # The assertions read the English labels; gettext consults LANGUAGE on every call.
    monkeypatch.setenv("LANGUAGE", "en")


class _Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class _Menu:
    def confirm(self, question, default_yes=True):
        return True


class _Bp:
    def __init__(self):
        self.logger = _Logger()
        self.menu = _Menu()


def _commit(repository, filename):
    (repository / filename).write_text("x\n", encoding="utf-8")
    run_git(repository, "add", filename)
    run_git(repository, "commit", "-m", f"add {filename}")


def _branch_moved_on_origin(tmp_path, remote, branch):
    """Another computer (or a stable build) publishes a commit on origin/BRANCH."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-b", branch, str(remote), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.name", "Other")
    run_git(other, "config", "user.email", "other@example.invalid")
    _commit(other, "elsewhere.txt")
    run_git(other, "push", "origin", branch)


@pytest.fixture
def behind(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    _commit(repository, "work.txt")
    run_git(repository, "push", "-u", "origin", "dev-me")
    _branch_moved_on_origin(tmp_path, remote, "dev-me")
    monkeypatch.chdir(repository)
    return repository


def test_a_branch_only_behind_origin_is_sent_to_synchronize(behind):
    bp = _Bp()

    assert not package_operations._publish_testing_branch(bp, "dev-me")

    text = bp.logger.text()
    assert "origin/dev-me has 1 commit(s) that your dev-me does not have yet" in text
    assert "Go to Organize Branches and click Synchronize" in text
    assert "Push failed" not in text


def test_commits_on_both_sides_are_sent_to_download_updates(behind):
    _commit(behind, "mine.txt")
    bp = _Bp()

    assert not package_operations._publish_testing_branch(bp, "dev-me")

    text = bp.logger.text()
    assert "(1 only here, 1 only on origin)" in text
    assert "Use Download updates to merge origin/dev-me into dev-me" in text
    assert "Synchronize" not in text


def test_after_synchronize_the_testing_branch_is_published(behind):
    assert main_sync.sync_with_main(_Bp(), confirm=False)
    bp = _Bp()

    assert package_operations._publish_testing_branch(bp, "dev-me")
