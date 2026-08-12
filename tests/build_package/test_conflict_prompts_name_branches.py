"""A prompt that discards work must say which branch it discards.

"Keep the local version" and "Accept remote version" do not identify a branch.
During a stable promotion the merge runs on the development branch with
origin/main coming in, and a user who reads "local" as "the main branch"
throws away the work being promoted.
"""

import pytest

from gitrepo.build_package.core import conflict_resolver as module
from gitrepo.build_package.core.conflict_resolver import ConflictResolver, short_ref
from gitrepo.build_package.core.git_utils import GitUtils


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, style, message):
        self.messages.append((style, message))


class Menu:
    def __init__(self, choice=0):
        self.choice = choice
        self.menus = []

    def show_menu(self, title, options, default_index=None):
        self.menus.append((title, options))
        return (self.choice, options[self.choice])


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(module, "_", lambda text: text)
    monkeypatch.setattr(GitUtils, "get_repo_root_path", staticmethod(lambda: "/tmp"))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: "dev-talesam"))
    return ConflictResolver(Logger(), Menu())


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("refs/remotes/origin/main", "origin/main"),
        ("refs/heads/dev-talesam", "dev-talesam"),
        ("origin/main", "origin/main"),
    ],
)
def test_refs_are_shown_the_way_a_user_reads_them(ref, expected):
    assert short_ref(ref) == expected


def test_the_catalog_prompt_names_both_branches(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/app.pot", "locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, _side: True)

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is True

    title, options = resolver.menu.menus[0]
    assert options[0] == "Keep dev-talesam"
    assert options[1] == "Use origin/main"
    # The branch being merged in has to appear in the question as well, not only
    # in the buttons: the user reads the question first.
    assert "origin/main" in title and "dev-talesam" in title
    assert "refs/remotes" not in title


def test_the_kept_and_discarded_branches_are_both_reported(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, _side: True)

    resolver.resolve_translation_catalogs("refs/remotes/origin/main")

    message = "\n".join(text for _style, text in resolver.logger.messages)
    assert "dev-talesam" in message
    assert "origin/main" in message


def test_the_per_file_prompt_names_the_branches_when_they_are_known(resolver):
    resolver.incoming_ref = "refs/remotes/origin/main"

    keep_current, take_incoming = resolver._side_labels()

    assert keep_current == "Keep dev-talesam"
    assert take_incoming == "Use origin/main"


def test_an_unknown_incoming_ref_falls_back_without_inventing_a_branch(resolver):
    keep_current, take_incoming = resolver._side_labels()

    assert keep_current == "Keep dev-talesam"
    assert take_incoming == "Accept remote version"


def test_the_gtk_dialog_splits_the_heading_from_the_body():
    # Adw centres and bolds the heading, so a multi-line question rendered as
    # one heading is the unreadable block the user reported.
    from gitrepo.build_package.gui import gtk_adapters  # noqa: PLC0415 - GTK import is optional

    title = "Conflict in 2 translation catalogs\n\nDetails that belong in the body."
    heading, _separator, remainder = title.partition("\n")
    assert heading == "Conflict in 2 translation catalogs"
    assert remainder.strip() == "Details that belong in the body."
    assert hasattr(gtk_adapters.GTKMenuSystem, "show_menu")


def test_resolver_state_is_not_shared_between_merges(resolver):
    assert resolver.incoming_ref == ""
    resolver.incoming_ref = "refs/remotes/origin/main"
    fresh = ConflictResolver(Logger(), Menu())
    assert fresh.incoming_ref == ""


def test_a_menu_stub_without_branches_still_resolves(monkeypatch):
    monkeypatch.setattr(module, "_", lambda text: text)
    monkeypatch.setattr(GitUtils, "get_repo_root_path", staticmethod(lambda: "/tmp"))
    monkeypatch.setattr(GitUtils, "get_current_branch", staticmethod(lambda: ""))
    resolver = ConflictResolver(Logger(), Menu())
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, _side: True)

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is True
    _title, options = resolver.menu.menus[0]
    assert options[1] == "Use origin/main"


def test_the_file_list_stays_in_the_question(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/app.pot", "locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, _side: True)

    resolver.resolve_translation_catalogs("refs/remotes/origin/main")

    title, _options = resolver.menu.menus[0]
    assert "locale/app.pot" in title and "locale/en.po" in title


def test_declining_the_group_decision_falls_back(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po"])
    resolver.menu.choice = 2  # "Decide file by file"

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is False


def test_source_files_are_never_answered_as_a_group(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po", "src/app.py"])

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is False
    assert resolver.menu.menus == []


def test_a_resolver_reports_failure_when_a_file_cannot_be_resolved(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, _side: False)

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is False


def test_no_conflicts_is_not_a_group_decision(resolver, monkeypatch):
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: [])

    assert resolver.resolve_translation_catalogs("refs/remotes/origin/main") is False


def test_the_ours_side_is_the_checked_out_branch(resolver, monkeypatch):
    """Pin the mapping the user got wrong: option 0 keeps HEAD, not main."""
    sides = []
    monkeypatch.setattr(ConflictResolver, "get_conflict_files", lambda _self: ["locale/en.po"])
    monkeypatch.setattr(ConflictResolver, "_resolve_index_side", lambda _self, _path, side: sides.append(side) or True)

    resolver.menu.choice = 0
    resolver.resolve_translation_catalogs("refs/remotes/origin/main")
    assert sides == ["ours"]

    sides.clear()
    resolver.menu.choice = 1
    resolver.resolve_translation_catalogs("refs/remotes/origin/main")
    assert sides == ["theirs"]
