"""Branch cleanup deletes only what Git proves is already merged."""

import importlib
import subprocess

from .git_fixtures import AlwaysConfirm, Logger, create_repository_with_remote, run_git


def test_branch_cleanup_never_offers_a_branch_with_unmerged_commits(build_package_modules, tmp_path, monkeypatch):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    repository, _remote = create_repository_with_remote(tmp_path)

    # Merged: nothing on it that main does not already have.
    run_git(repository, "branch", "chore-old")
    # Unmerged: holds the only copy of a commit.
    run_git(repository, "checkout", "-b", "feature-release-fix")
    (repository / "only-here.txt").write_text("unique work\n", encoding="utf-8")
    run_git(repository, "add", "only-here.txt")
    run_git(repository, "commit", "-m", "unique work")
    run_git(repository, "push", "origin", "feature-release-fix")
    run_git(repository, "checkout", "main")
    run_git(repository, "push", "origin", "chore-old")
    monkeypatch.chdir(repository)

    class Menu:
        def __init__(self):
            self.question = ""

        def confirm(self, question, default_yes=True):
            self.question = question
            return False

    menu = Menu()
    logger = Logger()
    assert git_utils.GitUtils.cleanup_old_branches(logger, menu) is False

    assert "chore-old" in menu.question
    assert "feature-release-fix" not in menu.question
    # The branch is not silently omitted: the user is told why it was kept.
    assert any("feature-release-fix" in message for _style, message in logger.messages)


def test_branch_cleanup_deletes_only_the_merged_branches(build_package_modules, tmp_path, monkeypatch):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    repository, remote = create_repository_with_remote(tmp_path)

    run_git(repository, "branch", "chore-old")
    run_git(repository, "checkout", "-b", "feature-release-fix")
    (repository / "only-here.txt").write_text("unique work\n", encoding="utf-8")
    run_git(repository, "add", "only-here.txt")
    run_git(repository, "commit", "-m", "unique work")
    unique = run_git(repository, "rev-parse", "HEAD").stdout.strip()
    run_git(repository, "push", "origin", "feature-release-fix")
    run_git(repository, "checkout", "main")
    run_git(repository, "push", "origin", "chore-old")
    monkeypatch.chdir(repository)

    assert git_utils.GitUtils.cleanup_old_branches(Logger(), AlwaysConfirm()) is True

    local_branches = run_git(repository, "branch", "--format=%(refname:short)").stdout.split()
    assert "chore-old" not in local_branches
    assert "feature-release-fix" in local_branches
    # The unique commit still exists on both sides.
    assert run_git(repository, "cat-file", "-t", unique).stdout.strip() == "commit"
    remote_branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=remote, check=True, capture_output=True, text=True
    ).stdout.split()
    assert "feature-release-fix" in remote_branches
    assert "chore-old" not in remote_branches


def test_branch_cleanup_refuses_without_a_base_to_compare_against(build_package_modules, tmp_path, monkeypatch):
    git_utils = importlib.import_module("gitrepo.build_package.core.git_utils")
    repository = tmp_path / "solo"
    repository.mkdir()
    run_git(repository, "init", "-b", "trunk")
    run_git(repository, "config", "user.name", "Safety Test")
    run_git(repository, "config", "user.email", "safety@example.invalid")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(repository, "add", "tracked.txt")
    run_git(repository, "commit", "-m", "base")
    run_git(repository, "branch", "side")
    monkeypatch.chdir(repository)

    class Menu:
        def confirm(self, question, default_yes=True):
            raise AssertionError("nothing may be confirmed without a merge base")

    assert git_utils.GitUtils.cleanup_old_branches(Logger(), Menu()) is False
    assert "side" in run_git(repository, "branch", "--format=%(refname:short)").stdout.split()
