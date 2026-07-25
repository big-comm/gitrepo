"""One repository journey at a time, and partial success says so."""

import importlib
import threading
from types import SimpleNamespace

import pytest

from .git_fixtures import Logger, create_repository_with_remote, run_git


@pytest.fixture
def repository_lock(build_package_modules):
    return importlib.import_module("gitrepo.build_package.core.repository_lock")


def test_a_second_thread_is_refused_while_a_journey_runs(repository_lock, tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    inside = threading.Event()
    release = threading.Event()
    refused = []

    def holder():
        with repository_lock.repository_operation("publishing changes"):
            inside.set()
            release.wait(timeout=10)

    def contender():
        inside.wait(timeout=10)
        try:
            with repository_lock.repository_operation("downloading updates"):
                refused.append(None)
        except repository_lock.RepositoryBusy as busy:
            refused.append(str(busy))

    first = threading.Thread(target=holder)
    second = threading.Thread(target=contender)
    first.start()
    second.start()
    second.join(timeout=15)
    release.set()
    first.join(timeout=15)

    assert refused and refused[0] is not None
    assert "publishing changes" in refused[0]


def test_the_owning_thread_re_enters_because_journeys_nest(repository_lock, tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    # Generating a package commits first; the inner journey must not deadlock.
    with repository_lock.repository_operation("generating a package"):
        with repository_lock.repository_operation("publishing changes"):
            assert repository_lock.current_holder().startswith("generating a package")


def test_the_lock_is_released_even_when_the_journey_raises(repository_lock, tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    with pytest.raises(RuntimeError):
        with repository_lock.repository_operation("restoring a commit"):
            raise RuntimeError("boom")

    with repository_lock.repository_operation("publishing changes"):
        assert repository_lock.current_holder().startswith("publishing changes")


def test_a_decorated_journey_refuses_while_another_one_holds_the_repository(repository_lock, tmp_path, monkeypatch):
    commit_operations = importlib.import_module("gitrepo.build_package.core.commit_operations")
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    bp = SimpleNamespace(logger=Logger(), is_git_repo=True)
    inside = threading.Event()
    release = threading.Event()

    def holder():
        with repository_lock.repository_operation("downloading updates"):
            inside.set()
            release.wait(timeout=10)

    worker = threading.Thread(target=holder)
    worker.start()
    try:
        assert inside.wait(timeout=10)
        # No Git command may run: the journey is refused before it starts.
        monkeypatch.setattr(
            commit_operations.GitUtils,
            "has_changes",
            staticmethod(lambda: pytest.fail("the journey must be refused before touching Git")),
        )
        assert commit_operations.commit_and_push(bp) is False
    finally:
        release.set()
        worker.join(timeout=10)

    assert any("downloading updates" in message for _style, message in bp.logger.messages)


def test_a_failed_publish_keeps_the_local_branch_and_says_how_to_retry(build_package_modules, tmp_path, monkeypatch):
    branch_handler = importlib.import_module("gitrepo.build_package.core.branch_handler")
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    bp = SimpleNamespace(logger=Logger())

    original_run = branch_handler.subprocess.run_git

    def fail_push(command, **kwargs):
        if command[:2] == ["git", "push"]:
            import subprocess as std

            return std.CompletedProcess(command, 1, stdout="", stderr="remote rejected")
        return original_run(command, **kwargs)

    monkeypatch.setattr(branch_handler.subprocess, "run_git", fail_push)

    assert branch_handler.create_branch_and_push(bp, "main", "feature-x") is False

    # The work that succeeded is still there, and the retry command is stated.
    assert "feature-x" in run_git(repository, "branch", "--format=%(refname:short)").stdout.split()
    assert bp.last_operation_details["local_branch_created"] == "feature-x"
    assert bp.last_operation_details["remote_unchanged"] is True
    assert "git push -u origin" in bp.last_operation_details["retry_command"]
