"""Committing without publishing must record the work and leave origin alone."""

from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import build_package, commit_handler, commit_operations
from gitrepo.build_package.core.repository_snapshot import RepositorySnapshot

from .git_fixtures import AlwaysConfirm, Logger, create_repository_with_remote, run_git


class NoConflicts:
    def has_conflicts(self):
        return False

    def resolve(self, *_args):
        return False


class RecordingMenu:
    def __init__(self, answer=True):
        self.answer = answer
        self.questions = []

    def confirm(self, question, default_yes=True):
        self.questions.append(question)
        return self.answer


def _bp(menu=None):
    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu or AlwaysConfirm(),
        conflict_resolver=NoConflicts(),
        dry_run_mode=False,
    )


def _forbid_push(monkeypatch):
    """Fail loudly instead of silently reaching the remote."""

    def refuse(bp, branch):
        raise AssertionError(f"push attempted for {branch}")

    monkeypatch.setattr(commit_handler, "_push_branch", refuse)
    return refuse


def test_commit_only_creates_the_commit_and_never_pushes(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    remote_before = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    _forbid_push(monkeypatch)
    bp = _bp()

    assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert local_head != remote_before
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_before
    assert run_git(repository, "status", "--porcelain").stdout.strip() == ""


def test_commit_only_records_the_pending_publication(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    _forbid_push(monkeypatch)
    bp = _bp()

    assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert bp.last_operation_details == {
        "local_commit_created": local_head,
        "current_branch": "main",
        "remote_unchanged": True,
        "retry_command": "git push -u origin refs/heads/main:refs/heads/main",
        "commit_only": True,
    }


def test_commit_only_skips_the_remote_sync(tmp_path, monkeypatch):
    """A rebase or merge would move history the user asked to leave alone."""
    repository, _remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    _forbid_push(monkeypatch)

    def refuse_sync(_bp, branch):
        raise AssertionError(f"sync attempted for {branch}")

    monkeypatch.setattr(commit_handler, "_sync_branch", refuse_sync)

    assert commit_handler.execute_commit(_bp(), "fix: keep it local", "main", push=False) is True


def test_pending_commit_is_publishable_afterwards(tmp_path, monkeypatch):
    """The commit-only state must resolve through the ordinary push path."""
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    assert commit_handler.publish_existing_commit(bp, "main") is True
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == local_head


def test_commit_only_journey_confirms_without_promising_a_push(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    remote_before = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(commit_operations, "_", lambda message: message)
    _forbid_push(monkeypatch)

    menu = RecordingMenu(answer=True)
    bp = _bp(menu)
    bp.args = SimpleNamespace(commit="fix: keep it local", commit_file=None)
    bp.settings = {"auto_version_bump": False}
    bp.github_user_name = "tester"
    bp.repo_path = str(repository)

    assert commit_operations.commit_and_push(bp, push=False) is True

    question = str(menu.questions[0])
    assert "git push" not in question
    assert "git commit" in question
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_before


def test_commit_only_journey_leaves_a_clean_tree_unpublished(tmp_path, monkeypatch):
    """Nothing to commit must not turn into a push the caller declined."""
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    _forbid_push(monkeypatch)

    def refuse_retry(_bp):
        raise AssertionError("publication retry offered while pushing was declined")

    monkeypatch.setattr(commit_operations, "_retry_pending_publication", refuse_retry)

    bp = _bp()
    bp.args = SimpleNamespace(commit="fix: nothing here", commit_file=None)
    bp.settings = {"auto_version_bump": False}
    bp.github_user_name = "tester"
    bp.repo_path = str(repository)

    assert commit_operations.commit_and_push(bp, push=False) is True


def test_no_push_flag_is_refused_together_with_build():
    """A package build reads the branch from origin, so it needs the push."""
    with pytest.raises(SystemExit):
        build_package.parse_arguments(["--no-push", "--build", "testing"])


def test_no_push_flag_routes_to_a_local_commit():
    args = build_package.parse_arguments(["--commit-only", "-c", "fix: local"])

    assert args.no_push is True
    assert args.commit == "fix: local"


def test_publish_defaults_to_pushing():
    assert build_package.parse_arguments(["-c", "fix: publish"]).no_push is False


def test_snapshot_counts_commits_origin_has_never_seen(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    assert RepositorySnapshot.capture().unpushed_commits == 0

    (repository / "tracked.txt").write_text("local work\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "local only")

    snapshot = RepositorySnapshot.capture()
    assert snapshot.unpushed_commits == 1
    assert snapshot.remote_branch_exists is True


def test_snapshot_treats_an_unpublished_branch_as_fully_unpushed(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-fresh")
    (repository / "tracked.txt").write_text("branch work\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "branch work")
    monkeypatch.chdir(repository)

    snapshot = RepositorySnapshot.capture()

    assert snapshot.remote_branch_exists is False
    assert snapshot.unpushed_commits == snapshot.commit_count == 2
