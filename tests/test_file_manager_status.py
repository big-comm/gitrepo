"""Repository emblems follow real Git state without modifying it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gitrepo.file_manager.status import repository_state


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True).stdout


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "tracked").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return repo


def test_only_repository_roots_get_emblems(repository, tmp_path):
    nested = repository / "nested"
    nested.mkdir()
    assert repository_state(tmp_path) is None
    assert repository_state(nested) is None
    assert repository_state(repository) == "clean"


@pytest.mark.parametrize("staged", [False, True])
def test_modified_and_staged_files(repository, staged):
    (repository / "tracked").write_text("changed\n")
    if staged:
        git(repository, "add", ".")
    index = (repository / ".git/index").read_bytes()
    assert repository_state(repository) == "modified"
    assert (repository / ".git/index").read_bytes() == index


def test_untracked_and_ignored_files(repository):
    (repository / ".git/info/exclude").write_text("ignored\n")
    (repository / "ignored").write_text("ignored")
    assert repository_state(repository) == "clean"
    (repository / "new\nfile").write_text("new")
    assert repository_state(repository) == "modified"


def test_commit_and_push_update_emblem(repository):
    (repository / "tracked").write_text("changed\n")
    git(repository, "commit", "-am", "local")
    assert repository_state(repository) == "unpushed"
    (repository / "extra").write_text("new")
    assert repository_state(repository) == "modified"
    (repository / "extra").unlink()
    git(repository, "push")
    assert repository_state(repository) == "clean"


def test_missing_upstream_uses_origin_same_name(repository):
    git(repository, "branch", "--unset-upstream")
    assert repository_state(repository) == "clean"
    (repository / "tracked").write_text("local\n")
    git(repository, "commit", "-am", "local")
    assert repository_state(repository) == "unpushed"


def test_new_branch_without_remote_counterpart(repository):
    git(repository, "checkout", "-b", "unpublished")
    assert repository_state(repository) == "unpushed"


def test_deleted_upstream_is_pending_publication(repository):
    git(repository, "update-ref", "-d", "refs/remotes/origin/main")
    assert repository_state(repository) == "unpushed"


def test_empty_repository_and_repository_without_remote(tmp_path):
    git(tmp_path, "init", "-b", "main")
    assert repository_state(tmp_path) == "clean"
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "local",
    )
    assert repository_state(tmp_path) == "unpushed"


def test_linked_worktree_and_detached_head(repository, tmp_path):
    worktree = tmp_path / "worktree"
    git(repository, "worktree", "add", "-b", "linked", str(worktree))
    assert (worktree / ".git").is_file()
    assert repository_state(worktree) == "unpushed"
    git(worktree, "checkout", "--detach")
    assert repository_state(worktree) == "clean"


def test_conflict_has_priority_over_other_changes(repository):
    git(repository, "checkout", "-b", "other")
    (repository / "tracked").write_text("other\n")
    git(repository, "commit", "-am", "other")
    git(repository, "checkout", "main")
    (repository / "tracked").write_text("main\n")
    git(repository, "commit", "-am", "main")
    subprocess.run(["git", "-C", str(repository), "merge", "other"], capture_output=True)
    (repository / "new").write_text("new")
    assert repository_state(repository) == "conflict"


def test_git_environment_cannot_redirect_probe(repository, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init")
    (other / "dirty").touch()
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert repository_state(repository) == "clean"


def test_status_does_not_execute_fsmonitor(repository, tmp_path):
    marker = tmp_path / "executed"
    hook = tmp_path / "monitor"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o755)
    git(repository, "config", "core.fsmonitor", str(hook))
    assert repository_state(repository) == "clean"
    assert not marker.exists()


def test_failed_probe_never_claims_clean(tmp_path):
    (tmp_path / ".git").mkdir()
    assert repository_state(tmp_path) is None


def test_rename_source_cannot_be_parsed_as_a_conflict(repository):
    source = repository / "u fake\nname"
    source.write_text("content")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "source")
    git(repository, "mv", source.name, "destination")
    assert repository_state(repository) == "modified"


def test_upstream_on_another_remote(repository):
    git(repository, "remote", "rename", "origin", "upstream")
    assert repository_state(repository) == "clean"
    (repository / "tracked").write_text("new\n")
    git(repository, "commit", "-am", "local")
    assert repository_state(repository) == "unpushed"


def test_batch_helper_preserves_paths_and_reads_multiple_states(repository, tmp_path):
    other = tmp_path / "repository with\na newline"
    other.mkdir()
    git(other, "init", "-b", "main")
    (other / "new").touch()
    script = Path(__file__).parents[1] / "usr/share/gitrepo/file_manager/scan.py"
    paths = [str(repository), str(other), str(tmp_path)]
    result = subprocess.run(
        [sys.executable, str(script)], input=json.dumps(paths), capture_output=True, text=True, check=True, timeout=5
    )
    assert json.loads(result.stdout) == {paths[0]: "clean", paths[1]: "modified", paths[2]: None}


def test_native_scanner_delivers_results_through_glib(repository, tmp_path):
    from gi.repository import GLib
    from gitrepo.file_manager.scanner import ScanJob

    loop = GLib.MainLoop()
    results = []

    def complete(states):
        results.append(states)
        loop.quit()

    job = ScanJob([str(repository), str(tmp_path)], complete)
    assert not results
    watchdog = GLib.timeout_add_seconds(5, lambda: loop.quit() or False)
    loop.run()
    if not results:
        job.cancel()
        pytest.fail("Native scanner did not deliver results")
    GLib.source_remove(watchdog)
    assert results == [{str(repository): "clean", str(tmp_path): None}]
