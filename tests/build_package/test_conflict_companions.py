"""Keeping both conflict versions never destroys what is already there."""

import importlib
import subprocess
from pathlib import Path

from .git_fixtures import Logger, create_repository_with_remote, run_git


def _conflicted_repository(tmp_path: Path) -> Path:
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "incoming")
    (repository / "tracked.txt").write_text("theirs\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "theirs")
    run_git(repository, "checkout", "main")
    (repository / "tracked.txt").write_text("ours\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "ours")
    subprocess.run(["git", "merge", "incoming"], cwd=repository, capture_output=True, text=True)
    return repository


class ChoosingMenu:
    def __init__(self, choice):
        self.choice = choice
        self.questions = []

    def show_menu(self, title, options):
        self.questions.append(title)
        return (self.choice, options[self.choice])

    def confirm(self, question, default_yes=True):
        return True


def test_keep_both_never_overwrites_an_existing_companion(build_package_modules, tmp_path, monkeypatch):
    conflict_resolver = importlib.import_module("gitrepo.build_package.core.conflict_resolver")
    repository = _conflicted_repository(tmp_path)

    # Work the user already owns under the name the resolver wants.
    (repository / "tracked.txt.ours").write_text("precious\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    menu = ChoosingMenu(0)
    resolver = conflict_resolver.ConflictResolver(Logger(), menu)
    assert resolver._keep_both_versions("tracked.txt") is True

    assert (repository / "tracked.txt.ours").read_text(encoding="utf-8") == "precious\n"
    assert (repository / "tracked.txt.ours.1").read_text(encoding="utf-8") == "ours\n"
    assert (repository / "tracked.txt.theirs").read_text(encoding="utf-8") == "theirs\n"


def test_keep_both_never_writes_through_a_symlinked_companion(build_package_modules, tmp_path, monkeypatch):
    conflict_resolver = importlib.import_module("gitrepo.build_package.core.conflict_resolver")
    repository = _conflicted_repository(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch\n", encoding="utf-8")
    (repository / "tracked.txt.theirs").symlink_to(outside)
    monkeypatch.chdir(repository)

    menu = ChoosingMenu(0)
    resolver = conflict_resolver.ConflictResolver(Logger(), menu)
    assert resolver._keep_both_versions("tracked.txt") is True

    assert outside.read_text(encoding="utf-8") == "do not touch\n"
    assert (repository / "tracked.txt.theirs.1").read_text(encoding="utf-8") == "theirs\n"


def test_keep_both_requires_an_explicit_choice_for_the_resolved_file(build_package_modules, tmp_path, monkeypatch):
    conflict_resolver = importlib.import_module("gitrepo.build_package.core.conflict_resolver")
    repository = _conflicted_repository(tmp_path)
    monkeypatch.chdir(repository)

    # Choosing "our version" must not silently leave the incoming one in place.
    menu = ChoosingMenu(0)
    resolver = conflict_resolver.ConflictResolver(Logger(), menu)
    assert resolver._keep_both_versions("tracked.txt") is True

    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "ours\n"
    assert any("tracked.txt" in question for question in menu.questions)


def test_keep_both_leaves_the_file_conflicted_when_the_choice_is_cancelled(
    build_package_modules, tmp_path, monkeypatch
):
    conflict_resolver = importlib.import_module("gitrepo.build_package.core.conflict_resolver")
    repository = _conflicted_repository(tmp_path)
    monkeypatch.chdir(repository)

    class CancellingMenu:
        def show_menu(self, title, options):
            return None

    resolver = conflict_resolver.ConflictResolver(Logger(), CancellingMenu())
    assert resolver._keep_both_versions("tracked.txt") is False

    # Both sides are saved, and the conflict is still recorded in the index.
    assert (repository / "tracked.txt.ours").read_text(encoding="utf-8") == "ours\n"
    assert (repository / "tracked.txt.theirs").read_text(encoding="utf-8") == "theirs\n"
    status = run_git(repository, "status", "--porcelain", "tracked.txt").stdout
    assert status.startswith("UU")
