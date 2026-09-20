"""Creating, renaming and deleting branches never loses commits without an explicit choice."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from gitrepo.build_package.core import branch_handler, branch_menu

from .git_fixtures import Logger, create_repository_with_remote, run_git

PROJECT_ROOT = Path(__file__).parents[2]
GUI_ROOT = PROJECT_ROOT / "usr/share/gitrepo/build_package/gui"


def _bp(menu=None):
    return SimpleNamespace(logger=Logger(), menu=menu, is_git_repo=True, conflict_resolver=None)


def _local_branches(repository):
    return set(run_git(repository, "for-each-ref", "refs/heads", "--format=%(refname:short)").stdout.split())


def _remote_branches(remote):
    return set(run_git(remote, "for-each-ref", "refs/heads", "--format=%(refname:short)").stdout.split())


def _current(repository):
    return run_git(repository, "branch", "--show-current").stdout.strip()


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_branch_from_another_branch_keeps_uncommitted_work(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    (repository / "tracked.txt").write_text("edited\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    assert branch_handler.create_branch(_bp(), "feature-x", "main", checkout=True, publish=False)

    assert _current(repository) == "feature-x"
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "edited\n"
    assert "feature-x" not in _remote_branches(remote)


def test_create_branch_can_publish_and_refuses_duplicates(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    assert branch_handler.create_branch(_bp(), "feature-y", "main", checkout=False, publish=True)
    assert _current(repository) == "main"
    assert "feature-y" in _remote_branches(remote)
    assert run_git(repository, "config", "branch.feature-y.merge").stdout.strip() == "refs/heads/feature-y"

    bp = _bp()
    assert not branch_handler.create_branch(bp, "feature-y", "main")
    assert ("red", True) in ((style, "feature-y" in message) for style, message in bp.logger.messages)


def test_create_branch_rejects_invalid_names_and_missing_sources(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)

    assert not branch_handler.create_branch(_bp(), "bad name", "main")
    assert not branch_handler.create_branch(_bp(), "fine", "nowhere")
    assert _local_branches(repository) == {"main"}


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def test_rename_branch_locally_leaves_origin_alone(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-old")
    run_git(repository, "push", "-u", "origin", "dev-old")
    monkeypatch.chdir(repository)

    bp = _bp()
    assert branch_handler.rename_branch(bp, "dev-old", "dev-new", rename_remote=False)

    assert _current(repository) == "dev-new"
    assert "dev-old" not in _local_branches(repository)
    assert _remote_branches(remote) == {"main", "dev-old"}
    assert any(style == "yellow" and "origin/dev-old" in message for style, message in bp.logger.messages)


def test_rename_branch_on_origin_publishes_new_name_then_deletes_old(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-old")
    run_git(repository, "push", "-u", "origin", "dev-old")
    run_git(repository, "checkout", "main")
    monkeypatch.chdir(repository)

    assert branch_handler.rename_branch(_bp(), "dev-old", "dev-new", rename_remote=True)

    assert _remote_branches(remote) == {"main", "dev-new"}
    assert _local_branches(repository) == {"main", "dev-new"}


@pytest.mark.parametrize("shared", ["main", "master", "dev"])
def test_rename_refuses_shared_branches(tmp_path, monkeypatch, shared):
    repository, _remote = create_repository_with_remote(tmp_path)
    if shared != "main":
        run_git(repository, "branch", shared)
    monkeypatch.chdir(repository)

    bp = _bp()
    assert not branch_handler.rename_branch(bp, shared, "renamed")
    assert shared in _local_branches(repository)
    assert any(style == "red" and shared in message for style, message in bp.logger.messages)


def test_rename_refuses_names_that_already_exist_on_origin(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "taken")
    run_git(repository, "push", "origin", "taken")
    run_git(repository, "branch", "-D", "taken")
    run_git(repository, "branch", "mine")
    monkeypatch.chdir(repository)

    assert not branch_handler.rename_branch(_bp(), "mine", "taken")
    assert "mine" in _local_branches(repository)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def _unmerged_branch(repository, name="feature-unmerged"):
    run_git(repository, "checkout", "-b", name)
    (repository / "only-here.txt").write_text("unique\n", encoding="utf-8")
    run_git(repository, "add", "only-here.txt")
    run_git(repository, "commit", "-m", "unique work")
    run_git(repository, "checkout", "main")


def test_delete_refuses_unmerged_branch_unless_forced(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    _unmerged_branch(repository)
    monkeypatch.chdir(repository)

    bp = _bp()
    assert not branch_handler.delete_branch(bp, "feature-unmerged")
    assert "feature-unmerged" in _local_branches(repository)
    assert any(style == "red" and "feature-unmerged" in message for style, message in bp.logger.messages)

    assert branch_handler.delete_branch(_bp(), "feature-unmerged", force=True)
    assert "feature-unmerged" not in _local_branches(repository)


def test_delete_merged_branch_even_when_not_merged_into_head(tmp_path, monkeypatch):
    # ``git branch -d`` would refuse this from dev-other; the merge check is against main.
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "chore-merged")
    run_git(repository, "checkout", "-b", "dev-other")
    (repository / "tracked.txt").write_text("other\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "other work")
    run_git(repository, "checkout", "main")
    (repository / "tracked.txt").write_text("main moved\n", encoding="utf-8")
    run_git(repository, "commit", "-am", "main moved")
    run_git(repository, "checkout", "dev-other")
    monkeypatch.chdir(repository)

    assert branch_handler.delete_branch(_bp(), "chore-merged")
    assert "chore-merged" not in _local_branches(repository)


def test_delete_can_remove_origin_copy_and_remote_only_branches(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "branch", "published")
    run_git(repository, "push", "origin", "published")
    run_git(repository, "branch", "remote-only")
    run_git(repository, "push", "origin", "remote-only")
    run_git(repository, "branch", "-D", "remote-only")
    monkeypatch.chdir(repository)

    bp = _bp()
    assert branch_handler.delete_branch(bp, "published", delete_remote=False)
    assert "published" not in _local_branches(repository)
    assert "published" in _remote_branches(remote)
    assert any(style == "cyan" and "origin/published" in message for style, message in bp.logger.messages)

    assert branch_handler.delete_branch(_bp(), "published", delete_remote=True)
    assert branch_handler.delete_branch(_bp(), "remote-only", delete_remote=True)
    assert _remote_branches(remote) == {"main"}


def test_delete_refuses_current_and_shared_branches(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-me")
    monkeypatch.chdir(repository)

    assert not branch_handler.delete_branch(_bp(), "dev-me", force=True)
    assert not branch_handler.delete_branch(_bp(), "main", force=True)
    assert _local_branches(repository) == {"main", "dev-me"}


def test_describe_branch_reports_where_the_branch_lives(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    _unmerged_branch(repository)
    monkeypatch.chdir(repository)

    facts = branch_handler.describe_branch("feature-unmerged")

    assert facts["local"] and not facts["remote"] and not facts["current"] and not facts["protected"]
    assert facts["unmerged_commits"] == 1
    assert branch_handler.describe_branch("main")["protected"]


# ---------------------------------------------------------------------------
# CLI menu
# ---------------------------------------------------------------------------


class ScriptedMenu:
    """Answer show_menu by option label and confirm by scripted booleans."""

    def __init__(self, picks, confirms):
        self.picks = list(picks)
        self.confirms = list(confirms)
        self.questions = []

    def show_menu(self, title, options, default_index=0, additional_content=None):
        wanted = self.picks.pop(0)
        # Labels are translated; the actions are addressed by position, branches by name.
        if isinstance(wanted, int):
            return wanted, options[wanted]
        return options.index(wanted), wanted

    def confirm(self, question, default_yes=True):
        self.questions.append(question)
        return self.confirms.pop(0)


def test_cli_create_flow_runs_the_announced_commands(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    monkeypatch.chdir(repository)
    monkeypatch.setattr(branch_menu.Prompt, "ask", staticmethod(lambda *_a, **_k: "feature-cli"))
    # picks: action, source; confirms: switch?, publish?, run?
    menu = ScriptedMenu([1, "main", 4], [True, True, True])

    branch_menu.branch_menu(_bp(menu))

    assert _current(repository) == "feature-cli"
    assert "feature-cli" in _remote_branches(remote)
    assert (
        "git branch feature-cli main → git checkout feature-cli → git push -u origin feature-cli" in menu.questions[-1]
    )


def test_cli_delete_flow_asks_before_losing_commits_and_honours_no(tmp_path, monkeypatch):
    repository, _remote = create_repository_with_remote(tmp_path)
    _unmerged_branch(repository)
    monkeypatch.chdir(repository)
    menu = ScriptedMenu([3, "feature-unmerged", 4], [False])

    branch_menu.branch_menu(_bp(menu))

    assert "feature-unmerged" in _local_branches(repository)
    assert len(menu.questions) == 1 and "feature-unmerged" in menu.questions[0]


def test_cli_rename_flow_offers_origin_only_when_published(tmp_path, monkeypatch):
    repository, remote = create_repository_with_remote(tmp_path)
    run_git(repository, "checkout", "-b", "dev-old")
    run_git(repository, "push", "-u", "origin", "dev-old")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(branch_menu.Prompt, "ask", staticmethod(lambda *_a, **_k: "dev-new"))
    # confirms: rename on origin?, run?
    menu = ScriptedMenu([2, "dev-old", 4], [True, True])

    branch_menu.branch_menu(_bp(menu))

    assert _current(repository) == "dev-new"
    assert _remote_branches(remote) == {"main", "dev-new"}
    assert "git push origin --delete dev-old" in menu.questions[-1]


# ---------------------------------------------------------------------------
# GUI wiring
# ---------------------------------------------------------------------------


def test_gui_branch_page_exposes_the_three_actions_with_their_commands():
    widget = (GUI_ROOT / "widgets/branch_widget.py").read_text(encoding="utf-8")
    actions = (GUI_ROOT / "branch_actions.py").read_text(encoding="utf-8")
    window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    for signal in ("create-branch-requested", "rename-branch-requested", "delete-branch-requested"):
        assert f'"{signal}"' in widget
        assert f'"{signal}"' in window
    assert '"git branch NEW SOURCE"' in widget
    assert '"git branch -m OLD NEW"' in widget
    assert '"git branch -D BRANCH"' in widget
    # The dialogs call the same core functions the CLI uses.
    for function in ("create_branch", "rename_branch", "delete_branch", "describe_branch"):
        assert f"branch_handler.{function}" in actions or f"import {function}" in actions
    assert "Adw.ResponseAppearance.DESTRUCTIVE" in actions
