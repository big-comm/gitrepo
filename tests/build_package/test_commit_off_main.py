"""Publishing from main in the terminal asks first; the personal branch is the default.

A user on main chose a commit type, wrote the message and confirmed: GitRepo
committed and pushed straight to origin/main, never offering the dev branch
the graphical commit dialog suggests.
"""

from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import commit_operations

from .git_fixtures import Logger, create_repository_with_remote, run_git


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")


class _Menu:
    def __init__(self, choice):
        self.choice = choice
        self.menus = []

    def show_menu(self, title, options, default_index=None, **_kwargs):
        self.menus.append((title, options, default_index))
        return None if self.choice is None else (self.choice, options[self.choice])

    def confirm(self, question, default_yes=True):
        return True


def _context(repository, menu):
    return SimpleNamespace(
        is_git_repo=True,
        logger=Logger(),
        menu=menu,
        conflict_resolver=None,
        dry_run_mode=False,
        args=SimpleNamespace(commit_file="", commit="fix: change SDK version"),
        settings={"auto_version_bump": False},
        repo_path=str(repository),
        github_user_name="narayans",
        last_commit_type=None,
    )


@pytest.fixture
def on_main_with_changes(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    return repository, remote


def _remote_head(remote, branch):
    return run_git(remote, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()


def test_the_personal_branch_is_offered_first_and_main_stays_untouched(on_main_with_changes):
    repository, remote = on_main_with_changes
    main_before = _remote_head(remote, "main")
    menu = _Menu(choice=0)

    assert commit_operations.commit_and_push(_context(repository, menu))

    title, options, default = menu.menus[0]
    assert title == "You are on main. Where should these changes go?"
    assert options == [
        "To dev-narayans, then open a pull request to main (recommended)",
        "Straight to main",
    ]
    assert default == 0
    assert _remote_head(remote, "main") == main_before
    assert _remote_head(remote, "dev-narayans")
    assert run_git(repository, "branch", "--show-current").stdout.strip() == "dev-narayans"


def test_straight_to_main_is_still_possible_when_chosen(on_main_with_changes):
    repository, remote = on_main_with_changes
    main_before = _remote_head(remote, "main")

    assert commit_operations.commit_and_push(_context(repository, _Menu(choice=1)))

    assert _remote_head(remote, "main") != main_before
    assert run_git(repository, "ls-remote", "--heads", "origin", "dev-narayans").stdout == ""


def test_backing_out_changes_nothing(on_main_with_changes):
    repository, remote = on_main_with_changes
    main_before = _remote_head(remote, "main")
    bp = _context(repository, _Menu(choice=None))

    assert not commit_operations.commit_and_push(bp)

    assert _remote_head(remote, "main") == main_before
    assert run_git(repository, "status", "--porcelain").stdout.strip() == "M tracked.txt"
    assert ("yellow", "Commit cancelled.") in bp.logger.messages


def test_a_personal_branch_is_not_asked_about(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-narayans")
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    menu = _Menu(choice=1)

    assert commit_operations.commit_and_push(_context(repository, menu))
    assert menu.menus == []
