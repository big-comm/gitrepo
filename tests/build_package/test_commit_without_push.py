"""Committing without publishing must record the work and leave origin alone."""

import subprocess
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


def _advance_origin(tmp_path, remote, branch="main"):
    """Move origin ahead from another clone, leaving the first one stale."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-b", branch, str(remote), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.name", "Other Test")
    run_git(other, "config", "user.email", "other@example.invalid")
    (other / "published.txt").write_text("from someone else\n", encoding="utf-8")
    run_git(other, "add", "published.txt")
    run_git(other, "commit", "-m", "remote work")
    run_git(other, "push", "origin", branch)
    return run_git(other, "rev-parse", "HEAD").stdout.strip()


def test_publishing_a_local_commit_integrates_a_moved_origin(tmp_path, monkeypatch):
    """Nothing synced during the commit, so publishing has to sync itself.

    Without it the push is rejected as non-fast-forward the moment anyone else
    pushes -- which is every real branch after a day of work.
    """
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    remote_head = _advance_origin(tmp_path, remote)
    run_git(repository, "fetch", "origin")

    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True

    published = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    assert published == run_git(repository, "rev-parse", "HEAD").stdout.strip()
    # Both histories survived: the local commit and the one origin gained.
    reachable = run_git(repository, "rev-list", "HEAD").stdout.split()
    assert remote_head in reachable
    assert (repository / "local.txt").exists()
    assert (repository / "published.txt").exists()


def test_publishing_rebases_over_work_in_progress(tmp_path, monkeypatch):
    """Editing more files after the local commit is the normal state here.

    Git refuses `pull --rebase` while the tree is dirty, and a plain merge only
    survives it when the incoming files happen not to overlap. The pending work
    is set aside so the integration sees a clean tree, then restored.
    """
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    # Work continued after the commit, on files origin did not touch: a bare
    # `pull --rebase` would have refused this outright.
    (repository / "tracked.txt").write_text("more local edits\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("brand new\n", encoding="utf-8")
    _advance_origin(tmp_path, remote)
    run_git(repository, "fetch", "origin")

    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True

    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == (
        run_git(repository, "rev-parse", "HEAD").stdout.strip()
    )
    # The in-progress edits are back in the tree, and not left in a stash.
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "more local edits\n"
    assert (repository / "untracked.txt").read_text(encoding="utf-8") == "brand new\n"
    assert run_git(repository, "stash", "list").stdout.strip() == ""
    assert (repository / "published.txt").exists()


def test_publish_completes_even_when_the_stash_cannot_be_reapplied(tmp_path, monkeypatch):
    """A conflict restoring the work must not undo a push that succeeded."""
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    # The pending edit lands on the very file origin changed, so the stash
    # cannot be reapplied cleanly.
    (repository / "published.txt").write_text("still editing\n", encoding="utf-8")
    _advance_origin(tmp_path, remote)
    run_git(repository, "fetch", "origin")

    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True

    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == (
        run_git(repository, "rev-parse", "HEAD").stdout.strip()
    )
    # The work is not lost, and the log says where to find it.
    assert "stash" in " ".join(message for _style, message in bp.logger.messages).lower()
    assert run_git(repository, "stash", "list").stdout.strip() != ""


def test_failed_integration_still_restores_work_in_progress(tmp_path, monkeypatch):
    """A stash left behind would hide the user's work after a failed publish."""
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    (repository / "tracked.txt").write_text("work in progress\n", encoding="utf-8")
    _advance_origin(tmp_path, remote)
    run_git(repository, "fetch", "origin")

    def refuse_sync(_bp, _branch):
        raise RuntimeError("integration failed")

    monkeypatch.setattr(commit_handler, "_sync_branch", refuse_sync)

    with pytest.raises(RuntimeError):
        commit_handler.publish_existing_commit(bp, "main", sync=True)

    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "work in progress\n"
    assert run_git(repository, "stash", "list").stdout.strip() == ""


def test_publishing_without_sync_leaves_the_commit_recoverable(tmp_path, monkeypatch):
    """The retry path must keep not touching a branch that was already synced."""
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    local_head = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    remote_head = _advance_origin(tmp_path, remote)
    run_git(repository, "fetch", "origin")

    with pytest.raises(RuntimeError):
        commit_handler.publish_existing_commit(bp, "main")

    assert run_git(repository, "rev-parse", "HEAD").stdout.strip() == local_head
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_head
    assert bp.last_operation_details["local_commit_created"] == local_head


def test_publishing_creates_a_branch_origin_never_had(tmp_path, monkeypatch):
    """The first publication of a personal branch has no upstream to integrate."""
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-fresh")
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "feat: new branch", "dev-fresh", push=False) is True

    assert commit_handler.publish_existing_commit(bp, "dev-fresh", sync=True) is True

    assert run_git(remote, "rev-parse", "refs/heads/dev-fresh").stdout.strip() == (
        run_git(repository, "rev-parse", "HEAD").stdout.strip()
    )


def test_several_local_commits_publish_together(tmp_path, monkeypatch):
    """Committing locally more than once must stay publishable as one push."""
    repository, remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        for index in range(3):
            (repository / f"step{index}.txt").write_text(f"step {index}\n", encoding="utf-8")
            assert commit_handler.execute_commit(bp, f"fix: step {index}", "main", push=False) is True

    assert RepositorySnapshot.capture().unpushed_commits == 3
    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True

    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == (
        run_git(repository, "rev-parse", "HEAD").stdout.strip()
    )
    assert RepositorySnapshot.capture().unpushed_commits == 0


def test_publishing_an_already_published_branch_is_harmless(tmp_path, monkeypatch):
    """Pressing publish twice must not fail or invent work."""
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "local.txt").write_text("local work\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    bp = _bp()

    with monkeypatch.context() as no_push:
        no_push.setattr(commit_handler, "_push_branch", lambda _bp, _branch: None)
        assert commit_handler.execute_commit(bp, "fix: keep it local", "main", push=False) is True

    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True
    published = run_git(remote, "rev-parse", "refs/heads/main").stdout.strip()

    assert commit_handler.publish_existing_commit(bp, "main", sync=True) is True
    assert run_git(remote, "rev-parse", "refs/heads/main").stdout.strip() == published


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
