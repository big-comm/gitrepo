"""The automatic divergence merge must announce what it discards."""

import os
import subprocess
from pathlib import Path

from gitrepo.build_package.core.git_utils import GitUtils

from .test_destructive_git_safety import create_repository_with_remote, run_git


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))

    def text(self):
        return "\n".join(message for _style, message in self.messages)


class Menu:
    def __init__(self, answer=True):
        self.answer = answer
        self.questions = []

    def confirm(self, question, default_yes=False):
        self.questions.append(question)
        return self.answer


def _diverge(tmp_path: Path) -> Path:
    """Return a repository whose branch conflicts with its remote."""
    repository, remote = create_repository_with_remote(tmp_path)

    clone = tmp_path / "clone"
    # The bare remote still has the init default HEAD, so the branch is explicit.
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(clone)], check=True, capture_output=True)
    run_git(clone, "config", "user.name", "Remote Author")
    run_git(clone, "config", "user.email", "remote@example.invalid")
    (clone / "tracked.txt").write_text("remote line\n", encoding="utf-8")
    (clone / "remote-only.txt").write_text("only remote\n", encoding="utf-8")
    run_git(clone, "add", "-A")
    run_git(clone, "commit", "-m", "remote change")
    run_git(clone, "push", "origin", "main")

    (repository / "tracked.txt").write_text("local line\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "local change")
    run_git(repository, "fetch", "origin")
    return repository


def test_divergence_merge_names_the_discarded_files_before_writing(tmp_path, monkeypatch):
    repository = _diverge(tmp_path)
    monkeypatch.chdir(repository)
    logger, menu = Logger(), Menu(answer=True)

    assert GitUtils.resolve_divergence("main", "merge-keep-current", logger, menu)

    # The question names the file and the version being dropped.
    assert menu.questions, "the discard must be confirmed first"
    question = menu.questions[0]
    assert "tracked.txt" in question
    assert "origin/main" in question
    # The recovery command is identical in every language.
    assert "git diff HEAD^2" in question

    # The current branch wins the conflict, the rest of the remote work lands.
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "local line\n"
    assert (repository / "remote-only.txt").read_text(encoding="utf-8") == "only remote\n"

    # And the outcome is reported, not silent.
    assert "tracked.txt" in logger.text()
    assert "git diff HEAD^2" in logger.text()


def test_declined_divergence_merge_changes_nothing(tmp_path, monkeypatch):
    repository = _diverge(tmp_path)
    monkeypatch.chdir(repository)
    head_before = run_git(repository, "rev-parse", "HEAD").stdout.strip()

    assert not GitUtils.resolve_divergence("main", "merge-keep-current", Logger(), Menu(answer=False))

    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == head_before
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "local line\n"
    assert not (repository / "remote-only.txt").exists()
    assert not os.path.exists(repository / ".git" / "MERGE_HEAD")


def test_discarded_remote_version_stays_readable(tmp_path, monkeypatch):
    repository = _diverge(tmp_path)
    monkeypatch.chdir(repository)

    assert GitUtils.resolve_divergence("main", "merge-keep-current", Logger(), Menu(answer=True))

    recovered = run_git(repository, "show", "HEAD^2:tracked.txt").stdout
    assert recovered == "remote line\n"
